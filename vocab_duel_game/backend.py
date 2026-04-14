
import os
import json
import time
import uuid
import sqlite3
import random
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    import firebase_admin
    from firebase_admin import auth as fb_auth
    from firebase_admin import credentials as fb_credentials
except Exception:
    firebase_admin = None
    fb_auth = None
    fb_credentials = None

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(APP_DIR))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "vocab_duel.db"))).resolve()
STATIC_DIR = APP_DIR / "static"
SAMPLE_CSV = APP_DIR / "sample_words.csv"

FIREBASE_SERVICE_ACCOUNT = os.getenv("FIREBASE_SERVICE_ACCOUNT", "").strip()

FIREBASE_PUBLIC_CONFIG = {
    "apiKey": os.getenv("FIREBASE_API_KEY", ""),
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
    "projectId": os.getenv("FIREBASE_PROJECT_ID", ""),
    "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", ""),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
    "appId": os.getenv("FIREBASE_APP_ID", ""),
}

AUTH_MODE = "firebase" if FIREBASE_SERVICE_ACCOUNT else "guest"

app = FastAPI(title="Vocab Duel")

if firebase_admin and FIREBASE_SERVICE_ACCOUNT and Path(FIREBASE_SERVICE_ACCOUNT).exists():
    if not firebase_admin._apps:
        cred = fb_credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
        firebase_admin.initialize_app(cred)
elif firebase_admin and FIREBASE_SERVICE_ACCOUNT:
    # service account path provided but file missing -> keep guest mode
    AUTH_MODE = "guest"

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        auth_provider TEXT NOT NULL,
        email TEXT,
        name TEXT,
        gender TEXT,
        about TEXT,
        level_band TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS theme_attempts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        seconds REAL NOT NULL,
        mode TEXT NOT NULL,
        played_at TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS queues (
        queue_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        level_band TEXT NOT NULL,
        status TEXT NOT NULL,
        matched_match_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        match_id TEXT PRIMARY KEY,
        topic TEXT NOT NULL,
        level_band TEXT NOT NULL,
        player1_user_id TEXT NOT NULL,
        player2_user_id TEXT NOT NULL,
        status TEXT NOT NULL,
        winner_user_id TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS match_results (
        id TEXT PRIMARY KEY,
        match_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        seconds REAL NOT NULL,
        submitted_at TEXT NOT NULL,
        UNIQUE(match_id, user_id)
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------------
# Models
# ---------------------------

class ProfilePayload(BaseModel):
    auth_token: Optional[str] = None
    guest_id: Optional[str] = None
    email: Optional[str] = None
    name: str
    gender: str = ""
    about: str = ""
    level_band: str

class QueuePayload(BaseModel):
    auth_token: Optional[str] = None
    guest_id: Optional[str] = None
    email: Optional[str] = None
    topic: str
    level_band: str

class ThemeAttemptPayload(BaseModel):
    auth_token: Optional[str] = None
    guest_id: Optional[str] = None
    email: Optional[str] = None
    topic: str
    seconds: float
    mode: str = "single"

class MatchResultPayload(BaseModel):
    auth_token: Optional[str] = None
    guest_id: Optional[str] = None
    email: Optional[str] = None
    match_id: str
    seconds: float

# ---------------------------
# Helpers
# ---------------------------

def normalize_sheet_url(sheet_url: Optional[str]) -> str:
    if not sheet_url:
        return str(SAMPLE_CSV)
    url = sheet_url.strip()
    if url.startswith("http") and "/edit" in url and "docs.google.com/spreadsheets" in url:
        base = url.split("/edit")[0]
        gid = "0"
        if "gid=" in url:
            gid = url.split("gid=")[-1].split("&")[0]
        return f"{base}/export?format=csv&gid={gid}"
    return url

def load_words(sheet_url: Optional[str]) -> pd.DataFrame:
    source = normalize_sheet_url(sheet_url)
    try:
        if source.startswith("http"):
            df = pd.read_csv(source)
        else:
            df = pd.read_csv(source)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить Google Sheet/CSV: {e}")

    lower_map = {c.lower().strip(): c for c in df.columns}
    required_variants = {
        "topic": ["topic", "тема"],
        "ru": ["ru", "russian", "рус", "русское", "russian_word"],
        "en": ["en", "english", "англ", "english_word"],
        "transcription": ["transcription", "phonetic", "транскрипция", "ipa"],
        "freq_level": ["freq_level", "level", "уровень", "band", "frequency_band"],
    }
    resolved = {}
    for key, variants in required_variants.items():
        for v in variants:
            if v in lower_map:
                resolved[key] = lower_map[v]
                break

    for key in ("topic", "ru", "en", "transcription"):
        if key not in resolved:
            raise HTTPException(
                status_code=400,
                detail=("В таблице нужны столбцы topic, ru, en, transcription. "
                        f"Не найден столбец для '{key}'.")
            )

    out = pd.DataFrame({
        "topic": df[resolved["topic"]].astype(str).str.strip(),
        "ru": df[resolved["ru"]].astype(str).str.strip(),
        "en": df[resolved["en"]].astype(str).str.strip(),
        "transcription": df[resolved["transcription"]].astype(str).str.strip(),
    })
    if "freq_level" in resolved:
        out["freq_level"] = df[resolved["freq_level"]].astype(str).str.strip()
    else:
        out["freq_level"] = ""

    out = out[(out["topic"] != "") & (out["ru"] != "") & (out["en"] != "")]
    return out

def verify_firebase_token(id_token: Optional[str]) -> Optional[Dict[str, Any]]:
    if AUTH_MODE != "firebase" or not id_token or not fb_auth:
        return None
    try:
        decoded = fb_auth.verify_id_token(id_token)
        return decoded
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Google авторизация не прошла: {e}")

def resolve_identity(auth_token: Optional[str], guest_id: Optional[str], email: Optional[str]) -> Dict[str, str]:
    decoded = verify_firebase_token(auth_token)
    if decoded:
        return {
            "user_id": decoded["uid"],
            "auth_provider": "firebase",
            "email": decoded.get("email", email or ""),
        }
    if not guest_id:
        raise HTTPException(status_code=400, detail="Нет auth_token или guest_id.")
    return {
        "user_id": guest_id,
        "auth_provider": "guest",
        "email": email or "",
    }

def ensure_user(identity: Dict[str, str], patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    patch = patch or {}
    conn = db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM users WHERE user_id = ?", (identity["user_id"],)).fetchone()
    timestamp = now_iso()
    if row is None:
        cur.execute("""
            INSERT INTO users (user_id, auth_provider, email, name, gender, about, level_band, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            identity["user_id"],
            identity["auth_provider"],
            identity.get("email", ""),
            patch.get("name", ""),
            patch.get("gender", ""),
            patch.get("about", ""),
            patch.get("level_band", ""),
            timestamp,
            timestamp,
        ))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (identity["user_id"],)).fetchone()
    else:
        updates = {
            "email": identity.get("email", row["email"] or ""),
            "name": patch.get("name", row["name"]),
            "gender": patch.get("gender", row["gender"]),
            "about": patch.get("about", row["about"]),
            "level_band": patch.get("level_band", row["level_band"]),
            "updated_at": timestamp,
        }
        cur.execute("""
            UPDATE users SET email=?, name=?, gender=?, about=?, level_band=?, updated_at=?
            WHERE user_id=?
        """, (
            updates["email"], updates["name"], updates["gender"], updates["about"],
            updates["level_band"], updates["updated_at"], identity["user_id"]
        ))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (identity["user_id"],)).fetchone()
    conn.close()
    return dict(row)

def cleanup_old_queues(conn: sqlite3.Connection):
    # keep waiting entries for 20 minutes max
    cur = conn.cursor()
    rows = cur.execute("SELECT queue_id, created_at FROM queues WHERE status='waiting'").fetchall()
    now_ts = time.time()
    for r in rows:
        try:
            created = datetime.fromisoformat(r["created_at"].replace("Z", ""))
            age = now_ts - created.timestamp()
            if age > 20 * 60:
                cur.execute("UPDATE queues SET status='expired', updated_at=? WHERE queue_id=?",
                            (now_iso(), r["queue_id"]))
        except Exception:
            pass
    conn.commit()

def fetch_user_basic(conn: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
    row = conn.execute("""
        SELECT user_id, name, gender, about, level_band, email
        FROM users WHERE user_id = ?
    """, (user_id,)).fetchone()
    return dict(row) if row else {}

# ---------------------------
# API
# ---------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "auth_mode": AUTH_MODE, "time": now_iso()}

@app.get("/api/config")
def config():
    enabled = AUTH_MODE == "firebase" and all(FIREBASE_PUBLIC_CONFIG.values())
    return {
        "auth_mode": AUTH_MODE,
        "firebase_enabled": enabled,
        "firebase": FIREBASE_PUBLIC_CONFIG if enabled else {},
        "sample_sheet_hint": "Можно оставить пустым и использовать sample_words.csv",
    }

@app.get("/api/topics")
def topics(sheet_url: Optional[str] = Query(default=None)):
    df = load_words(sheet_url)
    counts = (
        df.groupby("topic")
        .size()
        .reset_index(name="count")
        .sort_values(["topic"])
        .to_dict(orient="records")
    )
    return {"topics": counts}

@app.get("/api/topic_words")
def topic_words(topic: str, sheet_url: Optional[str] = Query(default=None)):
    df = load_words(sheet_url)
    topic_df = df[df["topic"] == topic].copy()
    if topic_df.empty:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    words = topic_df[["topic", "ru", "en", "transcription", "freq_level"]].to_dict(orient="records")
    return {"topic": topic, "count": len(words), "words": words}

@app.post("/api/profile")
def save_profile(payload: ProfilePayload):
    identity = resolve_identity(payload.auth_token, payload.guest_id, payload.email)
    user = ensure_user(identity, patch={
        "name": payload.name,
        "gender": payload.gender,
        "about": payload.about,
        "level_band": payload.level_band,
    })
    return {"ok": True, "user": user}

@app.get("/api/profile")
def get_profile(auth_token: Optional[str] = None, guest_id: Optional[str] = None, email: Optional[str] = None):
    identity = resolve_identity(auth_token, guest_id, email)
    user = ensure_user(identity)
    return {"user": user}

@app.post("/api/theme_attempt")
def save_theme_attempt(payload: ThemeAttemptPayload):
    identity = resolve_identity(payload.auth_token, payload.guest_id, payload.email)
    ensure_user(identity)
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO theme_attempts (id, user_id, topic, seconds, mode, played_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), identity["user_id"], payload.topic, payload.seconds, payload.mode, now_iso()))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/theme_history")
def theme_history(
    topic: str,
    auth_token: Optional[str] = None,
    guest_id: Optional[str] = None,
    email: Optional[str] = None
):
    identity = resolve_identity(auth_token, guest_id, email)
    conn = db()
    rows = conn.execute("""
        SELECT topic, seconds, mode, played_at
        FROM theme_attempts
        WHERE user_id = ? AND topic = ?
        ORDER BY seconds ASC, played_at ASC
    """, (identity["user_id"], topic)).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}

@app.post("/api/find_partner")
def find_partner(payload: QueuePayload):
    identity = resolve_identity(payload.auth_token, payload.guest_id, payload.email)
    user = ensure_user(identity)
    conn = db()
    cleanup_old_queues(conn)
    cur = conn.cursor()

    existing_waiting = cur.execute("""
        SELECT * FROM queues
        WHERE user_id = ? AND topic = ? AND level_band = ? AND status = 'waiting'
        ORDER BY created_at DESC
        LIMIT 1
    """, (identity["user_id"], payload.topic, payload.level_band)).fetchone()
    if existing_waiting:
        conn.close()
        return {"status": "waiting", "queue_id": existing_waiting["queue_id"]}

    partner = cur.execute("""
        SELECT * FROM queues
        WHERE topic = ? AND level_band = ? AND status = 'waiting' AND user_id != ?
        ORDER BY created_at ASC
        LIMIT 1
    """, (payload.topic, payload.level_band, identity["user_id"])).fetchone()

    if partner:
        match_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO matches (match_id, topic, level_band, player1_user_id, player2_user_id, status, winner_user_id, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, NULL)
        """, (match_id, payload.topic, payload.level_band, partner["user_id"], identity["user_id"], now_iso()))
        cur.execute("""
            UPDATE queues SET status='matched', matched_match_id=?, updated_at=? WHERE queue_id=?
        """, (match_id, now_iso(), partner["queue_id"]))
        queue_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO queues (queue_id, user_id, topic, level_band, status, matched_match_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'matched', ?, ?, ?)
        """, (queue_id, identity["user_id"], payload.topic, payload.level_band, match_id, now_iso(), now_iso()))
        conn.commit()
        opponent_user = fetch_user_basic(conn, partner["user_id"])
        conn.close()
        return {
            "status": "matched",
            "queue_id": queue_id,
            "match_id": match_id,
            "opponent": opponent_user,
        }

    queue_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO queues (queue_id, user_id, topic, level_band, status, matched_match_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'waiting', NULL, ?, ?)
    """, (queue_id, identity["user_id"], payload.topic, payload.level_band, now_iso(), now_iso()))
    conn.commit()
    conn.close()
    return {"status": "waiting", "queue_id": queue_id}

@app.get("/api/check_queue")
def check_queue(
    queue_id: str,
    auth_token: Optional[str] = None,
    guest_id: Optional[str] = None,
    email: Optional[str] = None
):
    identity = resolve_identity(auth_token, guest_id, email)
    conn = db()
    row = conn.execute("""
        SELECT * FROM queues WHERE queue_id = ? AND user_id = ?
    """, (queue_id, identity["user_id"])).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Очередь не найдена.")
    result = dict(row)
    if row["status"] == "matched" and row["matched_match_id"]:
        match = conn.execute("SELECT * FROM matches WHERE match_id = ?", (row["matched_match_id"],)).fetchone()
        if match:
            match_d = dict(match)
            opponent_id = match["player1_user_id"] if match["player2_user_id"] == identity["user_id"] else match["player2_user_id"]
            opponent = fetch_user_basic(conn, opponent_id)
            conn.close()
            return {"status": "matched", "match_id": match_d["match_id"], "opponent": opponent}
    conn.close()
    return {"status": result["status"], "queue_id": result["queue_id"]}

@app.get("/api/match")
def get_match(
    match_id: str,
    auth_token: Optional[str] = None,
    guest_id: Optional[str] = None,
    email: Optional[str] = None
):
    identity = resolve_identity(auth_token, guest_id, email)
    conn = db()
    match = conn.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)).fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Матч не найден.")
    if identity["user_id"] not in (match["player1_user_id"], match["player2_user_id"]):
        conn.close()
        raise HTTPException(status_code=403, detail="Нет доступа к этому матчу.")
    p1 = fetch_user_basic(conn, match["player1_user_id"])
    p2 = fetch_user_basic(conn, match["player2_user_id"])
    results = conn.execute("""
        SELECT user_id, seconds, submitted_at FROM match_results WHERE match_id = ?
    """, (match_id,)).fetchall()
    conn.close()
    return {
        "match": dict(match),
        "players": [p1, p2],
        "results": [dict(r) for r in results],
    }

@app.post("/api/submit_match_result")
def submit_match_result(payload: MatchResultPayload):
    identity = resolve_identity(payload.auth_token, payload.guest_id, payload.email)
    ensure_user(identity)
    conn = db()
    cur = conn.cursor()
    match = cur.execute("SELECT * FROM matches WHERE match_id = ?", (payload.match_id,)).fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Матч не найден.")
    if identity["user_id"] not in (match["player1_user_id"], match["player2_user_id"]):
        conn.close()
        raise HTTPException(status_code=403, detail="Нет доступа к матчу.")
    cur.execute("""
        INSERT INTO match_results (id, match_id, user_id, seconds, submitted_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(match_id, user_id) DO UPDATE SET
            seconds=excluded.seconds,
            submitted_at=excluded.submitted_at
    """, (str(uuid.uuid4()), payload.match_id, identity["user_id"], payload.seconds, now_iso()))

    # Save theme attempt as well
    cur.execute("""
        INSERT INTO theme_attempts (id, user_id, topic, seconds, mode, played_at)
        VALUES (?, ?, ?, ?, 'network', ?)
    """, (str(uuid.uuid4()), identity["user_id"], match["topic"], payload.seconds, now_iso()))

    results = cur.execute("""
        SELECT user_id, seconds FROM match_results WHERE match_id = ?
        ORDER BY seconds ASC
    """, (payload.match_id,)).fetchall()
    winner_user_id = None
    status = "active"
    finished_at = None
    if len(results) >= 2:
        winner_user_id = results[0]["user_id"]
        status = "finished"
        finished_at = now_iso()
    cur.execute("""
        UPDATE matches SET status=?, winner_user_id=?, finished_at=? WHERE match_id=?
    """, (status, winner_user_id, finished_at, payload.match_id))
    conn.commit()
    conn.close()
    return {"ok": True, "status": status, "winner_user_id": winner_user_id}

@app.get("/api/match_history")
def match_history(
    auth_token: Optional[str] = None,
    guest_id: Optional[str] = None,
    email: Optional[str] = None
):
    identity = resolve_identity(auth_token, guest_id, email)
    conn = db()
    rows = conn.execute("""
        SELECT m.match_id, m.topic, m.level_band, m.player1_user_id, m.player2_user_id,
               m.winner_user_id, m.status, m.created_at, m.finished_at
        FROM matches m
        WHERE m.player1_user_id = ? OR m.player2_user_id = ?
        ORDER BY COALESCE(m.finished_at, m.created_at) DESC
    """, (identity["user_id"], identity["user_id"])).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        opponent_id = d["player1_user_id"] if d["player2_user_id"] == identity["user_id"] else d["player2_user_id"]
        opponent = fetch_user_basic(conn, opponent_id)
        results = conn.execute("""
            SELECT user_id, seconds, submitted_at FROM match_results
            WHERE match_id = ?
            ORDER BY seconds ASC
        """, (d["match_id"],)).fetchall()
        d["opponent"] = opponent
        d["results"] = [dict(x) for x in results]
        items.append(d)
    conn.close()
    return {"items": items}

@app.get("/api/leaderboard")
def leaderboard(topic: str):
    conn = db()
    rows = conn.execute("""
        SELECT u.name, u.level_band, t.seconds, t.mode, t.played_at
        FROM theme_attempts t
        JOIN users u ON u.user_id = t.user_id
        WHERE t.topic = ?
        ORDER BY t.seconds ASC, t.played_at ASC
        LIMIT 50
    """, (topic,)).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}

# ---------------------------
# Static frontend
# ---------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")
