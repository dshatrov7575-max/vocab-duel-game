#!/usr/bin/env python3
"""Parallel fail-soft wrapper around the frozen Stage 6 source list."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stage6_base", HERE / "acquire.py")
base = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(base)


def fast_session() -> requests.Session:
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        status=1,
        backoff_factor=0.4,
        status_forcelist=(408, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fast_download(url: str, landing: str, target: Path) -> dict[str, Any]:
    headers = {
        "User-Agent": base.UA,
        "Accept": "application/pdf,text/html,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Referer": landing,
    }
    started = time.monotonic()
    with fast_session().get(url, headers=headers, stream=True, timeout=(15, 45), allow_redirects=True) as response:
        response.raise_for_status()
        total = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(1 << 20):
                if not chunk:
                    continue
                total += len(chunk)
                if total > base.MAX_BYTES:
                    raise RuntimeError("MAX_BYTES_EXCEEDED")
                handle.write(chunk)
        return {
            "status": response.status_code,
            "final_url": response.url,
            "headers": dict(response.headers),
            "seconds": round(time.monotonic() - started, 3),
            "bytes": total,
        }


def acquire_component(out: Path, source: dict[str, Any], component: tuple[str, str, str, int | None]) -> dict[str, Any]:
    cid, fmt, url, expected = component
    directory = out / source["id"]
    directory.mkdir(parents=True, exist_ok=True)
    extension = ".pdf" if fmt == "PDF" else ".html"
    target = directory / f"{cid}{extension}"
    snapshot = directory / f"{cid}.derived.txt"
    receipt: dict[str, Any] = {
        "source_id": source["id"],
        "component_id": cid,
        "component_key": f"{source['id']}::{cid}",
        "format": fmt,
        "official_url": url,
        "expected_pages": expected,
        "status": "FAILED",
        "case_selection_allowed": False,
    }
    try:
        receipt["download"] = fast_download(url, source["landing"], target)
        receipt["local_path"] = str(target)
        receipt["size_bytes"] = target.stat().st_size
        receipt["source_sha256"] = base.sha(target)
        if fmt == "PDF":
            receipt.update(base.inspect_pdf(target, snapshot, expected))
        else:
            receipt.update(base.inspect_html(target, snapshot))
        receipt["snapshot_path"] = str(snapshot)
        receipt["status"] = "SUCCESS"
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback_tail"] = traceback.format_exc()[-2500:]
    return receipt


def duplicates(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for item in items:
        if item.get(field):
            groups.setdefault(item[field], []).append(item["component_key"])
    return [{"value": value, "components": keys} for value, keys in sorted(groups.items()) if len(keys) > 1]


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "vault")
    out.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[dict[str, Any], tuple[str, str, str, int | None]]] = []
    for source in base.SOURCES:
        for component in source["components"]:
            tasks.append((source, component))

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(acquire_component, out, source, component): (source, component) for source, component in tasks}
        for future in as_completed(future_map):
            result = future.result()
            results[result["component_key"]] = result
            print(f"{result['status']} {result['component_key']} {result.get('size_bytes', 0)}", flush=True)

    source_receipts: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for source in base.SOURCES:
        components = [results[f"{source['id']}::{component[0]}"] for component in source["components"]]
        ok = [item for item in components if item["status"] == "SUCCESS"]
        material = "\n".join(f"{item['component_id']}:{item['source_sha256']}" for item in sorted(ok, key=lambda item: item["component_id"]))
        source_receipt = {
            "id": source["id"],
            "publisher": source["publisher"],
            "title": source["title"],
            "edition": source["edition"],
            "landing": source["landing"],
            "status": "SUCCESS" if len(ok) == len(components) else ("PARTIAL" if ok else "FAILED"),
            "component_set_sha256": hashlib.sha256(material.encode()).hexdigest() if material else None,
            "case_selection_allowed": False,
            "components": components,
        }
        directory = out / source["id"]
        (directory / "ACQUISITION_RECEIPT.json").write_text(json.dumps(source_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        source_receipts.append(source_receipt)
        flat.extend(components)

    ok = [item for item in flat if item["status"] == "SUCCESS"]
    bad = [item for item in flat if item["status"] != "SUCCESS"]
    root = {
        "work_id": base.WORK_ID,
        "generated_at_utc": base.now(),
        "status": "COMPLETE" if not bad else "PARTIAL_WITH_FAILURES",
        "source_count": len(source_receipts),
        "source_success_count": sum(item["status"] == "SUCCESS" for item in source_receipts),
        "component_count": len(flat),
        "component_success_count": len(ok),
        "component_failure_count": len(bad),
        "original_byte_lock_count": len(ok),
        "derived_snapshot_lock_count": sum(bool(item.get("snapshot_sha256")) for item in ok),
        "exact_byte_duplicates": duplicates(ok, "source_sha256"),
        "derived_text_duplicates": duplicates(ok, "snapshot_sha256"),
        "case_selection_allowed": False,
        "source_only_schema_changed": False,
        "semantic_rules_changed": False,
        "automatic_merge": False,
        "merge_performed": False,
        "sources": source_receipts,
    }
    (out / "ROOT_RECEIPT.json").write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = "\n".join([
        f"STATUS={root['status']}",
        f"SOURCE_SUCCESS={root['source_success_count']}/{root['source_count']}",
        f"COMPONENT_SUCCESS={root['component_success_count']}/{root['component_count']}",
        f"ORIGINAL_BYTE_LOCK={root['original_byte_lock_count']}",
        f"DERIVED_SNAPSHOT_LOCK={root['derived_snapshot_lock_count']}",
        "CASE_SELECTION_ALLOWED=false",
    ]) + "\n"
    (out / "SUMMARY.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
