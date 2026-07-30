#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import platform
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyshacl
import rdflib
from pyshacl import validate
from rdflib import Graph, RDF
from rdflib.namespace import SH

from b0_pair_rdf import build_graph, safe_uri
from common import dump_json, load_json, load_jsonl, sha256_file
from morse_reference_validator import validate_pair as validate_reference

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

PAIRS_PATH = INPUT / "EXTENDED_POLICY_PAIRS_250.jsonl"
PROFILE_PATH = INPUT / "B0_PAIR_EXTENDED_PROFILE_0_2.json"
SHAPES_PATH = INPUT / "B0_PAIR_SHACL_SPARQL_CONSTRAINTS_0_1.ttl"
ONTOLOGY_PATH = INPUT / "B0_PAIR_ONTOLOGY_0_1.ttl"
EXPECTED_STAGE14_PAIRS_SHA256 = "5c8ad60bcfed43f447e4223c47405a6127ca4a33b31b95bcf7214f1b72ace18c"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def extract_violations(results_graph: Graph, pairs: list[dict[str, Any]]) -> dict[str, list[str]]:
    focus_to_pair = {str(safe_uri(p["pair_id"])): p["pair_id"] for p in pairs}
    out: dict[str, set[str]] = defaultdict(set)
    for result in results_graph.subjects(RDF.type, SH.ValidationResult):
        focus = results_graph.value(result, SH.focusNode)
        if focus is None:
            raise RuntimeError(f"Validation result {result} has no sh:focusNode")
        pair_id = focus_to_pair.get(str(focus))
        if pair_id is None:
            raise RuntimeError(f"Unknown focus node returned by pySHACL: {focus}")
        messages = list(results_graph.objects(result, SH.resultMessage))
        if not messages:
            raise RuntimeError(f"Validation result {result} has no sh:resultMessage")
        for message in messages:
            out[pair_id].add(str(message))
    return {pair_id: sorted(values) for pair_id, values in out.items()}


def main() -> int:
    pairs = load_jsonl(PAIRS_PATH)
    profile = load_json(PROFILE_PATH)
    if len(pairs) != 250:
        raise RuntimeError(f"Expected 250 pairs, got {len(pairs)}")
    pairs_sha256 = sha256_file(PAIRS_PATH)
    if pairs_sha256 != EXPECTED_STAGE14_PAIRS_SHA256:
        raise RuntimeError(f"Generated benchmark drift: {pairs_sha256}")

    data_graph = build_graph(pairs, profile)
    shapes_graph = Graph().parse(SHAPES_PATH, format="turtle")
    ontology_graph = Graph().parse(ONTOLOGY_PATH, format="turtle")

    started = time.perf_counter()
    conforms, results_graph, results_text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ontology_graph,
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=True,
        advanced=True,
        js=False,
        debug=False,
        serialize_report_graph=False,
    )
    elapsed = time.perf_counter() - started
    if not isinstance(results_graph, Graph):
        raise RuntimeError(f"Expected rdflib.Graph report, got {type(results_graph)!r}")

    py_violations = extract_violations(results_graph, pairs)
    rows: list[dict[str, Any]] = []
    decision_mismatches = 0
    violation_mismatches = 0
    expected_mismatches = 0

    for pair in pairs:
        pair_id = pair["pair_id"]
        violations = py_violations.get(pair_id, [])
        decision = "REJECT" if violations else "ACCEPT"
        reference = validate_reference(pair, profile)
        expected_decision = pair["expected_decision"]
        decision_match = decision == reference["decision"]
        violation_match = set(violations) == set(reference["violations"])
        expected_match = decision == expected_decision
        decision_mismatches += not decision_match
        violation_mismatches += not violation_match
        expected_mismatches += not expected_match
        rows.append({
            "pair_id": pair_id,
            "distinction_id": pair["source"]["distinction_id"],
            "scenario": pair["scenario"],
            "expected_decision": expected_decision,
            "pyshacl_decision": decision,
            "pyshacl_violations": "|".join(violations),
            "morse_reference_decision": reference["decision"],
            "morse_reference_violations": "|".join(reference["violations"]),
            "decision_matches_reference": decision_match,
            "violations_match_reference": violation_match,
            "matches_expected": expected_match,
        })

    total_mismatch_count = decision_mismatches + violation_mismatches + expected_mismatches
    status = "PASS" if total_mismatch_count == 0 else "FAIL"
    report_ttl = OUTPUT / "PYSHACL_VALIDATION_REPORT_250.ttl"
    results_graph.serialize(report_ttl, format="turtle")
    comparison_csv = OUTPUT / "PYSHACL_COMPARISON_250.csv"
    write_csv(comparison_csv, rows)
    (OUTPUT / "PYSHACL_REPORT_TEXT.txt").write_text(str(results_text).rstrip() + "\n", encoding="utf-8")

    receipt = {
        "work_id": "MORSE-STAGE15-FULL-PYSHACL-20260730-01",
        "status": status,
        "total_pair_count": len(pairs),
        "expected_accept_count": sum(p["expected_decision"] == "ACCEPT" for p in pairs),
        "expected_reject_count": sum(p["expected_decision"] == "REJECT" for p in pairs),
        "pyshacl_global_conforms": bool(conforms),
        "pyshacl_accepted_count": sum(r["pyshacl_decision"] == "ACCEPT" for r in rows),
        "pyshacl_rejected_count": sum(r["pyshacl_decision"] == "REJECT" for r in rows),
        "decision_mismatch_count_vs_reference": decision_mismatches,
        "violation_set_mismatch_count_vs_reference": violation_mismatches,
        "expected_decision_mismatch_count": expected_mismatches,
        "total_mismatch_count": total_mismatch_count,
        "elapsed_seconds": round(elapsed, 6),
        "runtime": {
            "python": platform.python_version(),
            "pyshacl": pyshacl.__version__,
            "rdflib": rdflib.__version__,
            "platform": platform.platform(),
        },
        "input_hashes": {
            "pairs_sha256": pairs_sha256,
            "profile_sha256": sha256_file(PROFILE_PATH),
            "shapes_sha256": sha256_file(SHAPES_PATH),
            "ontology_sha256": sha256_file(ONTOLOGY_PATH),
        },
        "output_hashes": {
            "comparison_sha256": sha256_file(comparison_csv),
            "report_graph_sha256": sha256_file(report_ttl),
        },
        "guards": {
            "human_gold": False,
            "natural_errors_measured": False,
            "morse_effectiveness_measured": False,
            "production_ready": False,
            "case_selection_changed": False,
            "semantic_rules_changed": False,
            "automatic_merge": False,
            "merge_performed": False,
        },
        "interpretation": (
            "A PASS verifies portability of the frozen Stage 14 SHACL-SPARQL forms to a full pySHACL processor "
            "on the 250-pair synthetic formal challenge. It does not measure Russian-language understanding, "
            "natural errors, human burden, or MORSE effectiveness."
        ),
    }
    dump_json(OUTPUT / "MORSE_STAGE15_PYSHACL_RECEIPT_0_1.json", receipt)
    summary = [
        f"STATUS={status}",
        f"PAIR_COUNT={len(pairs)}",
        f"PYSHACL_VERSION={pyshacl.__version__}",
        f"RDFLIB_VERSION={rdflib.__version__}",
        f"GLOBAL_CONFORMS={bool(conforms)}",
        f"ACCEPTED={receipt['pyshacl_accepted_count']}",
        f"REJECTED={receipt['pyshacl_rejected_count']}",
        f"DECISION_MISMATCH_VS_REFERENCE={decision_mismatches}",
        f"VIOLATION_SET_MISMATCH_VS_REFERENCE={violation_mismatches}",
        f"MISMATCH_VS_EXPECTED={expected_mismatches}",
        f"TOTAL_MISMATCH={total_mismatch_count}",
        f"ELAPSED_SECONDS={elapsed:.6f}",
    ]
    (OUTPUT / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
