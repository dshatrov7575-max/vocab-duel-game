#!/usr/bin/env python3
"""Recover the three Stage 6 sources that failed in the first network run.

Acquisition only. This script never selects corpus cases and never changes the
frozen SOURCE_ONLY protocol or semantic rules.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

WORK_ID = "MORSE-STAGE6-MISSING-SOURCE-RECOVERY-20260730-01"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36"
VKT9_ROOT = "https://teplocom-sale.ru/support/rukovodstvo-po-ekspluatacii-vkt-9/"
ELEMER = [
    {
        "source_id": "NEW300-ELEMER-AIR10L-RU",
        "title": "АИР-10L. Руководство по эксплуатации",
        "landing": "https://www.elemer.ru/catalog/datchiki-davleniya-i-manometry/datchiki-davleniya/air-10l/",
        "url": "https://www.elemer.ru/upload/iblock/c4e/l9x2lcabu82v0wasblvgpk3r645t5u1n/re_air_10l.pdf",
    },
    {
        "source_id": "NEW300-ELEMER-IPM0399M0-RU",
        "title": "ИПМ 0399/М0 и ИПМ 0399Ex/М0. Руководство по эксплуатации",
        "landing": "https://www.elemer.ru/catalog/funktsionalnaya-apparatura/modulnye-preobrazovateli/ipm-0399-m0/",
        "url": "https://www.elemer.ru/upload/iblock/f3f/re_ipm_0399_m0.pdf",
    },
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=(408, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def curl_ipv4(url: str, landing: str, target: Path) -> dict[str, Any]:
    header_path = target.with_suffix(target.suffix + ".headers")
    command = [
        "curl", "-4", "--http1.1", "--fail", "--location",
        "--retry", "3", "--retry-all-errors", "--retry-delay", "2",
        "--connect-timeout", "30", "--max-time", "300",
        "--user-agent", UA, "--referer", landing,
        "--header", "Accept: application/pdf,text/html,*/*;q=0.8",
        "--header", "Accept-Language: ru-RU,ru;q=0.9,en;q=0.5",
        "--dump-header", str(header_path), "--output", str(target), url,
    ]
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"curl rc={completed.returncode}: {completed.stderr[-1500:]}")
    return {
        "method": "curl-ipv4-http1.1",
        "requested_url": url,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "size_bytes": target.stat().st_size,
        "response_headers": header_path.read_text(encoding="utf-8", errors="replace") if header_path.exists() else "",
    }


def inspect_pdf(path: Path, snapshot: Path) -> dict[str, Any]:
    if path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError("PDF_MAGIC_MISMATCH")
    reader = PdfReader(str(path))
    parts: list[str] = []
    chars: list[int] = []
    errors: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, 1):
        try:
            extracted = page.extract_text() or ""
        except Exception as exc:
            extracted = ""
            errors.append({"page": index, "error": f"{type(exc).__name__}: {exc}"})
        extracted = canonical(extracted) if extracted.strip() else ""
        chars.append(len(extracted))
        parts.append(f"=== PAGE {index} / {len(reader.pages)} ===\n{extracted}")
    snapshot.write_text(canonical("\n".join(parts)), encoding="utf-8")
    return {
        "page_count": len(reader.pages),
        "pages_with_text": sum(value > 0 for value in chars),
        "text_chars_total": sum(chars),
        "text_layer_status": "VERIFIED" if sum(chars) > 200 else "WEAK_OR_SCANNED",
        "source_sha256": sha256(path),
        "derived_snapshot_sha256": sha256(snapshot),
        "extraction_errors": errors,
    }


def fetch_html(client: requests.Session, url: str, target: Path) -> dict[str, Any]:
    headers = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5"}
    started = time.monotonic()
    response = client.get(url, headers=headers, timeout=(20, 90), allow_redirects=True)
    response.raise_for_status()
    target.write_bytes(response.content)
    return {
        "status_code": response.status_code,
        "requested_url": url,
        "final_url": response.url,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "size_bytes": len(response.content),
        "response_headers": dict(response.headers),
    }


def html_snapshot(path: Path, snapshot: Path, label: str) -> dict[str, Any]:
    soup = BeautifulSoup(path.read_bytes().decode("utf-8", errors="replace"), "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = canonical(soup.get_text("\n", strip=True))
    snapshot.write_text(canonical(f"=== {label} ===\nTITLE: {title}\n\n{text}"), encoding="utf-8")
    return {
        "source_sha256": sha256(path),
        "derived_snapshot_sha256": sha256(snapshot),
        "text_chars_total": len(text),
        "text_layer_status": "VERIFIED" if len(text) > 500 else "WEAK",
    }


def recover_elemer(out: Path, item: dict[str, str]) -> dict[str, Any]:
    directory = out / item["source_id"]
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / "main.pdf"
    snapshot = directory / "main.derived.txt"
    receipt: dict[str, Any] = {
        "source_id": item["source_id"],
        "publisher": "ЭЛЕМЕР",
        "document_title": item["title"],
        "official_landing_url": item["landing"],
        "official_file_url": item["url"],
        "status": "FAILED",
        "case_selection_allowed": False,
        "identity_change": False,
        "attempts": [],
    }
    candidates = [item["url"], item["url"].replace("https://www.elemer.ru", "https://elemer.ru")]
    for candidate in candidates:
        try:
            pdf.unlink(missing_ok=True)
            metadata = curl_ipv4(candidate, item["landing"], pdf)
            receipt["attempts"].append({"url": candidate, "status": "SUCCESS", "metadata": metadata})
            receipt.update(inspect_pdf(pdf, snapshot))
            receipt["local_path"] = str(pdf)
            receipt["derived_snapshot_path"] = str(snapshot)
            receipt["retrieved_url"] = candidate
            receipt["status"] = "SUCCESS"
            break
        except Exception as exc:
            receipt["attempts"].append({"url": candidate, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
            receipt["error"] = f"{type(exc).__name__}: {exc}"
    (directory / "RECOVERY_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def recover_vkt9(out: Path) -> dict[str, Any]:
    source_id = "NEW300-TEPLOCOM-VKT9-ONLINE-RU"
    directory = out / source_id
    directory.mkdir(parents=True, exist_ok=True)
    client = session()
    receipt: dict[str, Any] = {
        "source_id": source_id,
        "publisher": "Теплоком",
        "document_title": "ВКТ-9. Официальное сетевое руководство по эксплуатации",
        "official_root_url": VKT9_ROOT,
        "status": "FAILED",
        "case_selection_allowed": False,
        "identity_change": True,
        "replaces_failed_candidate": "NEW300-TEPLOCOM-VKT9-RU",
        "replacement_reason": "Замороженный PDF URL вернул HTTP 404; использован отдельный официальный HTML-комплект, опубликованный изготовителем.",
        "components": [],
    }
    try:
        root_path = directory / "00_root.html"
        root_download = fetch_html(client, VKT9_ROOT, root_path)
        root_soup = BeautifulSoup(root_path.read_bytes().decode("utf-8", errors="replace"), "lxml")
        prefix = urlparse(VKT9_ROOT).path.rstrip("/") + "/"
        links: set[str] = set()
        for anchor in root_soup.find_all("a", href=True):
            absolute = urljoin(VKT9_ROOT, anchor["href"])
            parsed = urlparse(absolute)
            if parsed.netloc == "teplocom-sale.ru" and parsed.path.startswith(prefix) and parsed.path.rstrip("/") != prefix.rstrip("/"):
                links.add(absolute.split("#", 1)[0])
        links = set(sorted(links))
        if len(links) < 12:
            raise RuntimeError(f"EXPECTED_AT_LEAST_12_CHILD_PAGES_GOT_{len(links)}")

        root_snapshot = directory / "00_root.derived.txt"
        root_component = {
            "component_id": "root",
            "official_url": VKT9_ROOT,
            "download": root_download,
            "local_path": str(root_path),
            "derived_snapshot_path": str(root_snapshot),
            "status": "SUCCESS",
        }
        root_component.update(html_snapshot(root_path, root_snapshot, "VKT9 ROOT"))
        receipt["components"].append(root_component)

        for index, url in enumerate(sorted(links), 1):
            html_path = directory / f"{index:02d}_section.html"
            text_path = directory / f"{index:02d}_section.derived.txt"
            component: dict[str, Any] = {"component_id": f"section-{index:02d}", "official_url": url, "status": "FAILED"}
            try:
                component["download"] = fetch_html(client, url, html_path)
                component["local_path"] = str(html_path)
                component["derived_snapshot_path"] = str(text_path)
                component.update(html_snapshot(html_path, text_path, f"VKT9 SECTION {index:02d}"))
                component["status"] = "SUCCESS"
            except Exception as exc:
                component["error"] = f"{type(exc).__name__}: {exc}"
            receipt["components"].append(component)

        successful = [component for component in receipt["components"] if component["status"] == "SUCCESS"]
        material = "\n".join(f"{component['component_id']}:{component['source_sha256']}" for component in successful)
        receipt["component_set_sha256"] = hashlib.sha256(material.encode("utf-8")).hexdigest()
        receipt["discovered_child_urls"] = sorted(links)
        receipt["expected_child_count"] = len(links)
        receipt["successful_component_count"] = len(successful)
        receipt["status"] = "SUCCESS" if len(successful) == len(receipt["components"]) else "PARTIAL"
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback_tail"] = traceback.format_exc()[-3000:]
    (directory / "RECOVERY_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def duplicate_groups(receipts: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for source in receipts:
        if source.get(field):
            groups.setdefault(source[field], []).append(source["source_id"])
        for component in source.get("components", []):
            if component.get(field):
                groups.setdefault(component[field], []).append(f"{source['source_id']}::{component['component_id']}")
    return [{"value": value, "items": items} for value, items in sorted(groups.items()) if len(items) > 1]


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "recovery-vault")
    out.mkdir(parents=True, exist_ok=True)
    receipts = [recover_elemer(out, item) for item in ELEMER]
    receipts.append(recover_vkt9(out))
    root = {
        "work_id": WORK_ID,
        "generated_at_utc": now(),
        "status": "COMPLETE" if all(item["status"] == "SUCCESS" for item in receipts) else "PARTIAL_WITH_FAILURES",
        "source_count": len(receipts),
        "source_success_count": sum(item["status"] == "SUCCESS" for item in receipts),
        "source_partial_count": sum(item["status"] == "PARTIAL" for item in receipts),
        "source_failure_count": sum(item["status"] == "FAILED" for item in receipts),
        "case_selection_allowed": False,
        "source_only_schema_changed": False,
        "semantic_rules_changed": False,
        "automatic_merge": False,
        "merge_performed": False,
        "exact_byte_duplicates": duplicate_groups(receipts, "source_sha256"),
        "derived_text_duplicates": duplicate_groups(receipts, "derived_snapshot_sha256"),
        "sources": receipts,
    }
    (out / "ROOT_RECOVERY_RECEIPT.json").write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = "\n".join([
        f"STATUS={root['status']}",
        f"SOURCE_SUCCESS={root['source_success_count']}/{root['source_count']}",
        f"SOURCE_PARTIAL={root['source_partial_count']}",
        f"SOURCE_FAILURE={root['source_failure_count']}",
        "CASE_SELECTION_ALLOWED=false",
    ]) + "\n"
    (out / "SUMMARY.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")
    return 0 if root["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
