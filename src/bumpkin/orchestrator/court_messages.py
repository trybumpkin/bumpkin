from __future__ import annotations

from bumpkin.orchestrator.court_payload import normalize_label


def build_court_messages(
    *,
    case_file_text: str,
    engine_label: str,
    language_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are Compatibility Court. Reason over the provided case file and return strict JSON only. "
        "Required keys: label, confidence, judge_summary, prosecutor_claims, defender_claims, "
        "accepted_arguments, rejected_arguments, unresolved_risks, accepted_evidence_ids, "
        "rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "Every accepted/rejected evidence id must exist in case_file.evidence_records[]. "
        "Each claim should cite those IDs or file paths present in the case file. "
        "Do not include markdown."
    )
    user = (
        "Court protocol:\n"
        "1) Prosecutor argues for higher-impact bump from evidence.\n"
        "2) Defender argues for lower-impact bump from evidence.\n"
        "3) Judge issues final verdict with accepted/rejected arguments and unresolved risks.\n\n"
        f"Deterministic engine label: {engine_label}\n\n"
        + (
            "Language-specific API hints:\n"
            + "".join(f"- {hint}\n" for hint in language_hints)
            + "\n"
            if language_hints
            else ""
        )
        + "Case file:\n"
        + f"{case_file_text}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_repair_messages(*, raw_output: str, fallback_label: str | None) -> list[dict[str, str]]:
    default_label = normalize_label(fallback_label or "") or "PATCH"
    system = (
        "You repair malformed Compatibility Court output into strict JSON only. "
        "Return one JSON object with keys: label, confidence, judge_summary, "
        "prosecutor_claims, defender_claims, accepted_arguments, rejected_arguments, unresolved_risks, "
        "accepted_evidence_ids, rejected_evidence_ids. "
        "label must be MAJOR|MINOR|PATCH|NO_BUMP. confidence must be high|medium|low. "
        "No markdown, no prose."
    )
    user = (
        "Repair the malformed payload below.\n"
        f"If label is missing or truncated, use default label {default_label}.\n"
        "If confidence is missing, use low.\n"
        "If judge_summary is missing, provide one concise sentence.\n\n"
        "Malformed output:\n"
        f"{raw_output[:1500]}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
