#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import dump_json, dump_jsonl, load_json, sha256_file, sha256_text

DISTINCTIONS = [
    "E1_NEGATION_SCOPE",
    "E2_MODALITY_FORCE",
    "E3_CONDITION_OR_EXCEPTION",
    "E4_QUANTITY_UNIT_COMPARATOR",
    "E5_REFERENT_OR_ASSET",
    "E6_ATTRIBUTION",
    "E7_OBJECT_TYPE",
    "E8_PHASE_TO_OUTCOME",
    "E9_DISJUNCTION_SCOPE",
    "E10_EPISTEMIC_FORCE",
]

SCENARIOS = [
    ("IDENTITY_SINGLETON", "ACCEPT"),
    ("IDENTITY_UNRESOLVED", "ACCEPT"),
    ("ALLOWED_ABSTRACTION_ONE_STEP", "ACCEPT"),
    ("ALLOWED_ABSTRACTION_TO_MAX", "ACCEPT"),
    ("SPECIAL_ABSENT_IDENTITY", "ACCEPT"),
    ("SPECIAL_NOT_APPLICABLE_IDENTITY", "ACCEPT"),
    ("SPECIAL_UNSUPPORTED_IDENTITY", "ACCEPT"),
    ("SPECIAL_ALLOWED_TRANSITION", "ACCEPT"),
    ("ALLOWED_ABSTRACTION_NO_RECORD", "REJECT"),
    ("OVER_ABSTRACTION", "REJECT"),
    ("DOPSPECIFICATION", "REJECT"),
    ("CANDIDATE_REPLACEMENT", "REJECT"),
    ("EMPTY_SOURCE_SET", "REJECT"),
    ("EMPTY_TARGET_SET", "REJECT"),
    ("SPECIAL_FORBIDDEN_TRANSITION", "REJECT"),
    ("MIXED_CANDIDATE_TO_SPECIAL", "REJECT"),
    ("MIXED_SPECIAL_TO_CANDIDATE", "REJECT"),
    ("SOURCE_MAPPING_VERSION_MISMATCH", "REJECT"),
    ("TARGET_MAPPING_VERSION_MISMATCH", "REJECT"),
    ("PROFILE_VERSION_MISMATCH", "REJECT"),
    ("CHANGE_RECORD_PROFILE_VERSION_MISMATCH", "REJECT"),
    ("UNSUPPORTED_DISTINCTION", "REJECT"),
    ("ANCHOR_MISMATCH", "REJECT"),
    ("CASE_ID_MISMATCH", "REJECT"),
    ("DISTINCTION_MISMATCH", "REJECT"),
]


def base_side(case_id: str, anchor: str, distinction: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "anchor_sha256": anchor,
        "distinction_id": distinction,
        "mapping_version": "0.2",
        "projection_kind": "CANDIDATE_SET",
        "candidates": [],
        "special_state": None,
    }


def candidate_side(case_id: str, anchor: str, distinction: str, values: list[str]) -> dict[str, Any]:
    side = base_side(case_id, anchor, distinction)
    side["candidates"] = list(values)
    return side


def special_side(case_id: str, anchor: str, distinction: str, state: str) -> dict[str, Any]:
    side = base_side(case_id, anchor, distinction)
    side["projection_kind"] = "SPECIAL_STATE"
    side["special_state"] = state
    return side


def make_pair(d: str, scenario: str, expected: str, idx: int) -> dict[str, Any]:
    token = d.split("_", 1)[0]
    case_id = f"S14CASE-{idx:02d}-{token}"
    anchor = sha256_text(f"MORSE-STAGE14|{d}|{scenario}|anchor")
    a, b, c = f"{d}:A", f"{d}:B", f"{d}:C"
    source = candidate_side(case_id, anchor, d, [a])
    target = candidate_side(case_id, anchor, d, [a])
    allowed = [a]
    change_record = {"present": False, "profile_version": None}
    profile_version = "0.2"

    if scenario == "IDENTITY_SINGLETON":
        pass
    elif scenario == "IDENTITY_UNRESOLVED":
        source["candidates"] = [a, b]; target["candidates"] = [a, b]; allowed = [a, b]
    elif scenario == "ALLOWED_ABSTRACTION_ONE_STEP":
        target["candidates"] = [a, b]; allowed = [a, b]; change_record = {"present": True, "profile_version": "0.2"}
    elif scenario == "ALLOWED_ABSTRACTION_TO_MAX":
        target["candidates"] = [a, b, c]; allowed = [a, b, c]; change_record = {"present": True, "profile_version": "0.2"}
    elif scenario == "SPECIAL_ABSENT_IDENTITY":
        source = special_side(case_id, anchor, d, "ABSENT"); target = special_side(case_id, anchor, d, "ABSENT"); allowed = []
    elif scenario == "SPECIAL_NOT_APPLICABLE_IDENTITY":
        source = special_side(case_id, anchor, d, "NOT_APPLICABLE"); target = special_side(case_id, anchor, d, "NOT_APPLICABLE"); allowed = []
    elif scenario == "SPECIAL_UNSUPPORTED_IDENTITY":
        source = special_side(case_id, anchor, d, "UNSUPPORTED"); target = special_side(case_id, anchor, d, "UNSUPPORTED"); allowed = []
    elif scenario == "SPECIAL_ALLOWED_TRANSITION":
        source = special_side(case_id, anchor, d, "ABSENT"); target = special_side(case_id, anchor, d, "NOT_APPLICABLE"); allowed = []
    elif scenario == "ALLOWED_ABSTRACTION_NO_RECORD":
        target["candidates"] = [a, b]; allowed = [a, b]
    elif scenario == "OVER_ABSTRACTION":
        target["candidates"] = [a, b, c]; allowed = [a, b]; change_record = {"present": True, "profile_version": "0.2"}
    elif scenario == "DOPSPECIFICATION":
        source["candidates"] = [a, b]; target["candidates"] = [a]; allowed = [a, b]
    elif scenario == "CANDIDATE_REPLACEMENT":
        target["candidates"] = [b]; allowed = [a, b]
    elif scenario == "EMPTY_SOURCE_SET":
        source["candidates"] = []; target["candidates"] = [a]; allowed = [a]
    elif scenario == "EMPTY_TARGET_SET":
        target["candidates"] = []; allowed = [a]
    elif scenario == "SPECIAL_FORBIDDEN_TRANSITION":
        source = special_side(case_id, anchor, d, "ABSENT"); target = special_side(case_id, anchor, d, "UNSUPPORTED"); allowed = []
    elif scenario == "MIXED_CANDIDATE_TO_SPECIAL":
        target = special_side(case_id, anchor, d, "ABSENT"); allowed = [a]
    elif scenario == "MIXED_SPECIAL_TO_CANDIDATE":
        source = special_side(case_id, anchor, d, "ABSENT"); target = candidate_side(case_id, anchor, d, [a]); allowed = [a]
    elif scenario == "SOURCE_MAPPING_VERSION_MISMATCH":
        source["mapping_version"] = "0.1"
    elif scenario == "TARGET_MAPPING_VERSION_MISMATCH":
        target["mapping_version"] = "0.1"
    elif scenario == "PROFILE_VERSION_MISMATCH":
        profile_version = "0.1"
    elif scenario == "CHANGE_RECORD_PROFILE_VERSION_MISMATCH":
        target["candidates"] = [a, b]; allowed = [a, b]; change_record = {"present": True, "profile_version": "0.1"}
    elif scenario == "UNSUPPORTED_DISTINCTION":
        source["distinction_id"] = "E99_UNKNOWN_DISTINCTION"; target["distinction_id"] = "E99_UNKNOWN_DISTINCTION"
    elif scenario == "ANCHOR_MISMATCH":
        target["anchor_sha256"] = sha256_text(f"MORSE-STAGE14|{d}|{scenario}|different-anchor")
    elif scenario == "CASE_ID_MISMATCH":
        target["case_id"] = case_id + "-OTHER"
    elif scenario == "DISTINCTION_MISMATCH":
        target["distinction_id"] = DISTINCTIONS[(DISTINCTIONS.index(d) + 1) % len(DISTINCTIONS)]
    else:
        raise AssertionError(scenario)

    return {
        "schema_version": "B0_PAIR_POLICY_CHALLENGE_0_1",
        "pair_id": f"S14-{token}-{scenario}",
        "scenario": scenario,
        "expected_decision": expected,
        "profile_id": "B0_PAIR_EXTENDED_PROFILE_0_2",
        "profile_version": profile_version,
        "source": source,
        "target": target,
        "allowed_candidates": allowed,
        "change_record": change_record,
        "notes": [
            "Synthetic mechanism challenge; no claim of natural-language frequency.",
            "Pair-specific allowed_candidates instantiates the permitted abstraction bound.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    profile = load_json(args.profile)
    assert profile["profile_id"] == "B0_PAIR_EXTENDED_PROFILE_0_2"
    rows = [make_pair(d, scenario, expected, idx) for idx, d in enumerate(DISTINCTIONS, 1) for scenario, expected in SCENARIOS]
    assert len(rows) == 250
    dump_jsonl(args.out, rows)
    receipt = {
        "work_id": "MORSE-STAGE14-B0-PAIR-CHALLENGE-20260730-01",
        "pair_count": len(rows),
        "distinction_count": len(DISTINCTIONS),
        "scenario_count_per_distinction": len(SCENARIOS),
        "expected_decision_counts": {"ACCEPT": sum(r["expected_decision"] == "ACCEPT" for r in rows), "REJECT": sum(r["expected_decision"] == "REJECT" for r in rows)},
        "profile_sha256": sha256_file(args.profile),
        "pairs_sha256": sha256_file(args.out),
        "human_gold": False,
        "natural_error_measurement": False,
        "purpose": "mechanism expressiveness and cross-implementation equivalence challenge",
    }
    dump_json(args.out.with_suffix(".receipt.json"), receipt)
    print(receipt)


if __name__ == "__main__":
    main()
