package b0.governance

import rego.v1

allowed_transition(src, tgt) if { src == "MESSAGE"; tgt == "MESSAGE" }
allowed_transition(src, tgt) if { src == "MESSAGE"; tgt == "CLAIM" }
allowed_transition(src, tgt) if { src == "CLAIM"; tgt == "CLAIM" }
allowed_transition(src, tgt) if { src == "CLAIM"; tgt == "OBSERVATION" }
allowed_transition(src, tgt) if { src == "OBSERVATION"; tgt == "OBSERVATION" }
allowed_transition(src, tgt) if { src == "COMMAND"; tgt == "COMMAND" }
allowed_transition(src, tgt) if { src == "COMMAND"; tgt == "EXECUTION" }
allowed_transition(src, tgt) if { src == "EXECUTION"; tgt == "EXECUTION" }
allowed_transition(src, tgt) if { src == "EXECUTION"; tgt == "OUTCOME" }
allowed_transition(src, tgt) if { src == "OUTCOME"; tgt == "OUTCOME" }
allowed_transition(src, tgt) if { src == "OUTCOME"; tgt == "VERIFICATION" }
allowed_transition(src, tgt) if { src == "VERIFICATION"; tgt == "VERIFICATION" }

is_disabled(code) if {
    code in object.get(input, "disabled_rules", [])
}

block_codes := {
    "SOURCE_DAMAGED",
    "TRANSFER_FAILED",
    "PROVENANCE_INVALID",
    "PROFILE_VERSION_MISMATCH",
    "POLICY_VERSION_MISMATCH",
    "HUMAN_CONFIRMATION_REJECTED",
    "ILLEGAL_TYPE_PROMOTION",
    "NOT_AUTHORIZED",
    "CLAIM_EVIDENCE_MISSING",
    "EXECUTION_EVIDENCE_MISSING",
    "OUTCOME_EVIDENCE_MISSING",
    "VERIFICATION_EVIDENCE_MISSING",
    "AUDIT_CHAIN_INVALID",
}

hold_codes := {
    "INPUT_INTERPRETATION_UNRESOLVED",
    "TRANSFER_NOT_EVALUATED",
    "UNSUPPORTED_DISTINCTION",
    "AMBIGUITY_UNRESOLVED",
    "HUMAN_CONFIRMATION_MISSING",
    "AUTHORIZATION_UNKNOWN",
}

block_applies(c, code) if {
    code == "SOURCE_DAMAGED"
    not is_disabled(code)
    c.source_integrity != "INTACT"
}
block_applies(c, code) if {
    code == "TRANSFER_FAILED"
    not is_disabled(code)
    c.transfer_preservation == "FAIL"
}
block_applies(c, code) if {
    code == "PROVENANCE_INVALID"
    not is_disabled(code)
    c.provenance_status != "VALID"
}
block_applies(c, code) if {
    code == "PROFILE_VERSION_MISMATCH"
    not is_disabled(code)
    not c.profile_version_match
}
block_applies(c, code) if {
    code == "POLICY_VERSION_MISMATCH"
    not is_disabled(code)
    not c.policy_version_match
}
block_applies(c, code) if {
    code == "HUMAN_CONFIRMATION_REJECTED"
    not is_disabled(code)
    c.human_confirmation_required
    c.human_confirmation_status == "REJECTED"
}
block_applies(c, code) if {
    code == "ILLEGAL_TYPE_PROMOTION"
    not is_disabled(code)
    not allowed_transition(c.source_type, c.target_type)
}
block_applies(c, code) if {
    code == "NOT_AUTHORIZED"
    not is_disabled(code)
    c.requires_authorization
    c.authorization_status == "NOT_AUTHORIZED"
}
block_applies(c, code) if {
    code == "CLAIM_EVIDENCE_MISSING"
    not is_disabled(code)
    c.source_type == "CLAIM"
    c.target_type == "OBSERVATION"
    not c.evidence_admitted
}
block_applies(c, code) if {
    code == "EXECUTION_EVIDENCE_MISSING"
    not is_disabled(code)
    c.source_type == "COMMAND"
    c.target_type == "EXECUTION"
    not c.execution_evidence
}
block_applies(c, code) if {
    code == "OUTCOME_EVIDENCE_MISSING"
    not is_disabled(code)
    c.source_type == "EXECUTION"
    c.target_type == "OUTCOME"
    not c.outcome_evidence
}
block_applies(c, code) if {
    code == "VERIFICATION_EVIDENCE_MISSING"
    not is_disabled(code)
    c.source_type == "OUTCOME"
    c.target_type == "VERIFICATION"
    not c.verification_evidence
}
block_applies(c, code) if {
    code == "AUDIT_CHAIN_INVALID"
    not is_disabled(code)
    not c.audit_chain_valid
}

hold_applies(c, code) if {
    code == "INPUT_INTERPRETATION_UNRESOLVED"
    not is_disabled(code)
    c.input_interpretation != "VERIFIED"
}
hold_applies(c, code) if {
    code == "TRANSFER_NOT_EVALUATED"
    not is_disabled(code)
    c.transfer_preservation == "NOT_EVALUATED"
}
hold_applies(c, code) if {
    code == "UNSUPPORTED_DISTINCTION"
    not is_disabled(code)
    c.support_status != "SUPPORTED"
}
hold_applies(c, code) if {
    code == "AMBIGUITY_UNRESOLVED"
    not is_disabled(code)
    c.ambiguity_status != "RESOLVED"
}
hold_applies(c, code) if {
    code == "HUMAN_CONFIRMATION_MISSING"
    not is_disabled(code)
    c.human_confirmation_required
    c.human_confirmation_status != "CONFIRMED"
    c.human_confirmation_status != "REJECTED"
}
hold_applies(c, code) if {
    code == "AUTHORIZATION_UNKNOWN"
    not is_disabled(code)
    c.requires_authorization
    c.authorization_status != "AUTHORIZED"
    c.authorization_status != "NOT_AUTHORIZED"
}

block_reasons(c) := {code |
    some code in block_codes
    block_applies(c, code)
}

hold_reasons(c) := {code |
    some code in hold_codes
    hold_applies(c, code)
}

all_reasons(c) := block_reasons(c) | hold_reasons(c)

disposition(c) := "BLOCK" if {
    count(block_reasons(c)) > 0
} else := "HOLD" if {
    count(hold_reasons(c)) > 0
} else := "ALLOW"

decision(c) := {
    "case_id": c.case_id,
    "disposition": disposition(c),
    "reason_codes": sort([r | some r in all_reasons(c)]),
}

decisions := [decision(c) | some c in input.cases]
