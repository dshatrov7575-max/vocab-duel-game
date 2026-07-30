#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def validate_pair(pair: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Independent Python reference for formal specification 0.2.

    It intentionally does not import the RDF or SPARQL implementation.
    """
    errors: set[str] = set()
    source = pair["source"]
    target = pair["target"]

    if source["case_id"] != target["case_id"]:
        errors.add("CASE_ID_MISMATCH")
    if source["anchor_sha256"] != target["anchor_sha256"]:
        errors.add("ANCHOR_MISMATCH")
    if source["distinction_id"] != target["distinction_id"]:
        errors.add("DISTINCTION_MISMATCH")
    if source["distinction_id"] not in set(profile["supported_distinctions"]):
        errors.add("UNSUPPORTED_DISTINCTION")
    required_mapping = profile["required_mapping_version"]
    if source["mapping_version"] != required_mapping or target["mapping_version"] != required_mapping:
        errors.add("MAPPING_VERSION_MISMATCH")
    if pair["profile_version"] != profile["profile_version"]:
        errors.add("PROFILE_VERSION_MISMATCH")
    if source["projection_kind"] != target["projection_kind"]:
        errors.add("PROJECTION_KIND_MISMATCH")

    if source["projection_kind"] == "CANDIDATE_SET" and target["projection_kind"] == "CANDIDATE_SET":
        source_set = set(source.get("candidates", []))
        target_set = set(target.get("candidates", []))
        allowed_set = set(pair.get("allowed_candidates", []))
        if not source_set:
            errors.add("EMPTY_SOURCE_CANDIDATE_SET")
        if not target_set:
            errors.add("EMPTY_TARGET_CANDIDATE_SET")
        if not source_set.issubset(target_set):
            errors.add("SOURCE_CANDIDATE_DROPPED")
        if not target_set.issubset(allowed_set):
            errors.add("TARGET_CANDIDATE_OUTSIDE_ALLOWED_BOUND")
        if target_set - source_set and not pair["change_record"]["present"] and source_set:
            errors.add("ABSTRACTION_WITHOUT_CHANGE_RECORD")
    elif source["projection_kind"] == "SPECIAL_STATE" and target["projection_kind"] == "SPECIAL_STATE":
        transition = [source.get("special_state"), target.get("special_state")]
        if transition not in profile.get("allowed_special_transitions", []):
            errors.add("SPECIAL_TRANSITION_NOT_ALLOWED")

    if pair["change_record"]["present"]:
        if pair["change_record"].get("profile_version") != pair["profile_version"]:
            errors.add("CHANGE_RECORD_PROFILE_VERSION_MISMATCH")

    return {
        "decision": "REJECT" if errors else "ACCEPT",
        "violations": sorted(errors),
    }
