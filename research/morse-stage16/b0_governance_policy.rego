package b0.governance

import rego.v1

allowed_transition(src, tgt) if {
    src == "MESSAGE"
    tgt == "MESSAGE"
}
allowed_transition(src, tgt) if {
    src == "MESSAGE"
    tgt == "CLAIM"
}
allowed_transition(src, tgt) if {
    src == "CLAIM"
    tgt == "CLAIM"
}
allowed_transition(src, tgt) if {
    src == "CLAIM"
    tgt == "OBSERVATION"
}
allowed_transition(src, tgt) if {
    src == "OBSERVATION"
    tgt == "OBSERVATION"
}
allowed_transition(src, tgt) if {
    src == "COMMAND"
    tgt == "COMMAND"
}
allowed_transition(src, tgt) if {
    src == "COMMAND"
    tgt == "EXECUTION"
}
allowed_transition(src, tgt) if {
    src == "EXECUTION"
    tgt == "EXECUTION"
}
allowed_transition(src, tgt) if {
    src == "EXECUTION"
    tgt == "OUTCOME"
}
allowed_transition(src, tgt) if {
    src == "OUTCOME"
    tgt == "OUTCOME"
}
allowed_transition(src, tgt) if {
    src == "OUTCOME"
    tgt == "VERIFICATION"
}
allowed_transition(src, tgt) if {
    src == "VERIFICATION"
    tgt == "VERIFICATION"
}

is_disabled(code) if {
    code in object.get(input, "disabled_rules", [])
}

block_reason(c, "SOURCE_DAMAGED") if {
    not is_disabled("SOURCE_DAMAGED")
    c.source_integrity != "INTACT"
}
hold_reason(c, "INPUT_INTERPRETATION_UNRESOLVED") if {
    not is_disabled("INPUT_INTERPRETATION_UNRESOLVED")
    c.input_interpretation != "VERIFIED"
}
block_reason(c, "TRANSFER_FAILED") if {
    not is_disabled("TRANSFER_FAILED")
    c.transfer_preservation == "FAIL"
}
hold_reason(c, "TRANSFER_NOT_EVALUATED") if {
    not is_disabled("TRANSFER_NOT_EVALUATED")
    c.transfer_preservation == "NOT_EVALUATED"
}
block_reason(c, "PROVENANCE_INVALID") if {
    not is_disabled("PROVENANCE_INVALID")
    c.provenance_status != "VALID"
}
block_reason(c, "PROFILE_VERSION_MISMATCH") if {
    not is_disabled("PROFILE_VERSION_MISMATCH")
    not c.profile_version_match
}
block_reason(c, "POLICY_VERSION_MISMATCH") if {
    not is_disabled("POLICY_VERSION_MISMATCH")
    not c.policy_version_match
}
hold_reason(c, "UNSUPPORTED_DISTINCTION") if {
    not is_disabled("UNSUPPORTED_DISTINCTION")
    c.support_status != "SUPPORTED"
}
hold_reason(c, "AMBIGUITY_UNRESOLVED") if {
    not is_disabled("AMBIGUITY_UNRESOLVED")
    c.ambiguity_status != "RESOLVED"
}
block_reason(c, "HUMAN_CONFIRMATION_REJECTED") if {
    not is_disabled("HUMAN_CONFIRMATION_REJECTED")
    c.human_confirmation_required
    c.human_confirmation_status == "REJECTED"
}
hold_reason(c, "HUMAN_CONFIRMATION_MISSING") if {
    not is_disabled("HUMAN_CONFIRMATION_MISSING")
    c.human_confirmation_required
    c.human_confirmation_status != "CONFIRMED"
    c.human_confirmation_status != "REJECTED"
}
block_reason(c, "ILLEGAL_TYPE_PROMOTION") if {
    not is_disabled("ILLEGAL_TYPE_PROMOTION")
    not allowed_transition(c.source_type, c.target_type)
}
block_reason(c, "NOT_AUTHORIZED") if {
    not is_disabled("NOT_AUTHORIZED")
    c.requires_authorization
    c.authorization_status == "NOT_AUTHORIZED"
}
hold_reason(c, "AUTHORIZATION_UNKNOWN") if {
    not is_disabled("AUTHORIZATION_UNKNOWN")
    c.requires_authorization
    c.authorization_status != "AUTHORIZED"
    c.authorization_status != "NOT_AUTHORIZED"
}
block_reason(c, "CLAIM_EVIDENCE_MISSING") if {
    not is_disabled("CLAIM_EVIDENCE_MISSING")
    c.source_type == "CLAIM"
    c.target_type == "OBSERVATION"
    not c.evidence_admitted
}
block_reason(c, "EXECUTION_EVIDENCE_MISSING") if {
    not is_disabled("EXECUTION_EVIDENCE_MISSING")
    c.source_type == "COMMAND"
    c.target_type == "EXECUTION"
    not c.execution_evidence
}
block_reason(c, "OUTCOME_EVIDENCE_MISSING") if {
    not is_disabled("OUTCOME_EVIDENCE_MISSING")
    c.source_type == "EXECUTION"
    c.target_type == "OUTCOME"
    not c.outcome_evidence
}
block_reason(c, "VERIFICATION_EVIDENCE_MISSING") if {
    not is_disabled("VERIFICATION_EVIDENCE_MISSING")
    c.source_type == "OUTCOME"
    c.target_type == "VERIFICATION"
    not c.verification_evidence
}
block_reason(c, "AUDIT_CHAIN_INVALID") if {
    not is_disabled("AUDIT_CHAIN_INVALID")
    not c.audit_chain_valid
}

block_reasons(c) := {r | block_reason(c, r)}
hold_reasons(c) := {r | hold_reason(c, r)}
all_reasons(c) := block_reasons(c) | hold_reasons(c)

disposition(c) := "BLOCK" if {
    count(block_reasons(c)) > 0
} else := "HOLD" if {
    count(hold_reasons(c)) > 0
} else := "ALLOW"

decision(c) := {
    "case_id": c.case_id,
    "disposition": disposition(c),
    "reason_codes": sort([r | r := all_reasons(c)[_]]),
}

decisions := [decision(c) | some c in input.cases]
