from __future__ import annotations


def _non_empty_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        return [f"{field} must be a list of non-empty strings."]
    return []


def _rows(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{field} must be a list."]
    errors: list[str] = []
    required = ("path", "rule", "action", "target", "impact_scope", "suggested_bump", "severity")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(f"{field}[{index}] must be an object.")
            continue
        errors.extend(
            f"{field}[{index}].{key} must be non-empty."
            for key in required
            if not str(row.get(key, "")).strip()
        )
    return errors


def validate_v5_fields(payload: dict[str, object], errors: list[str]) -> None:
    errors.extend(_rows(payload.get("semantic_facts"), "semantic_facts"))
    proof_obligations = payload.get("proof_obligations")
    if not isinstance(proof_obligations, dict):
        errors.append("v5 payload must include proof_obligations object.")
    else:
        version = str(proof_obligations.get("version", "")).strip()
        if version != "proof_obligations_v1":
            errors.append(
                f"Invalid proof_obligations.version: {version!r} (expected 'proof_obligations_v1')"
            )
        for key in ("required", "satisfied", "missing", "critical_missing"):
            errors.extend(
                _non_empty_string_list(proof_obligations.get(key), f"proof_obligations.{key}")
            )

    reasoning_trace = payload.get("reasoning_trace")
    if not isinstance(reasoning_trace, list):
        errors.append("v5 payload must include reasoning_trace list.")
    else:
        for index, claim in enumerate(reasoning_trace):
            if not isinstance(claim, dict):
                errors.append(f"reasoning_trace[{index}] must be an object.")
                continue
            _validate_trace_claim(claim, index, errors)

    contradictions = payload.get("contradictions")
    if not isinstance(contradictions, list):
        errors.append("v5 payload must include contradictions list.")
    else:
        for index, contradiction in enumerate(contradictions):
            if not isinstance(contradiction, dict):
                errors.append(f"contradictions[{index}] must be an object.")
                continue
            if not str(contradiction.get("code", "")).strip():
                errors.append(f"contradictions[{index}].code must be non-empty.")
            if not str(contradiction.get("message", "")).strip():
                errors.append(f"contradictions[{index}].message must be non-empty.")
            errors.extend(
                _non_empty_string_list(
                    contradiction.get("evidence_paths", []),
                    f"contradictions[{index}].evidence_paths",
                )
            )


def _validate_trace_claim(claim: dict[object, object], index: int, errors: list[str]) -> None:
    evidence = claim.get("evidence")
    policy = claim.get("policy")
    impact = claim.get("impact")
    if not isinstance(evidence, dict):
        errors.append(f"reasoning_trace[{index}].evidence must be an object.")
    elif (
        not str(evidence.get("path", "")).strip()
        and not str(evidence.get("evidence_id", "")).strip()
    ):
        errors.append(f"reasoning_trace[{index}].evidence requires non-empty path or evidence_id.")
    if not isinstance(policy, dict):
        errors.append(f"reasoning_trace[{index}].policy must be an object.")
    elif not str(policy.get("id", "")).strip():
        errors.append(f"reasoning_trace[{index}].policy.id must be non-empty.")
    if not isinstance(impact, dict):
        errors.append(f"reasoning_trace[{index}].impact must be an object.")
    else:
        if not str(impact.get("statement", "")).strip():
            errors.append(f"reasoning_trace[{index}].impact.statement must be non-empty.")
        if not str(impact.get("implied_bump", "")).strip():
            errors.append(f"reasoning_trace[{index}].impact.implied_bump must be non-empty.")
