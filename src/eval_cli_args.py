from __future__ import annotations

import argparse
import os

from prompt_pack import DEFAULT_LANGUAGE_GROUP
from token_env import resolve_models_endpoint


def parse_args() -> argparse.Namespace:
    try:
        default_case_delay_ms = int(os.getenv("BUMPKIN_EVAL_CASE_DELAY_MS", "0"))
    except ValueError:
        default_case_delay_ms = 0
    parser = argparse.ArgumentParser(description="Run Bumpkin fixture evals.")
    parser.add_argument("--fixtures-dir", default="test-diffs", help="Fixtures root directory")
    parser.add_argument(
        "--aggregate-json-dir",
        default="",
        help="Aggregate eval JSON outputs from this directory instead of running model calls.",
    )
    parser.add_argument(
        "--language-group",
        default=DEFAULT_LANGUAGE_GROUP,
        help="Only evaluate fixtures matching this language group.",
    )
    parser.add_argument("--prompt-version", default="", help="Override prompt version selection.")
    parser.add_argument(
        "--prompt-gate-baseline",
        default="",
        help="JSON file describing required prompt gate metrics.",
    )
    parser.add_argument(
        "--mode",
        default=os.getenv("BUMPKIN_PROVIDER", "auto"),
        help="Provider mode: auto | stub | github-models | openrouter",
    )
    parser.add_argument(
        "--include-tuning-targets",
        action="store_true",
        help="Include fixtures marked with context tuning_target=true.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BUMPKIN_MODEL", ""),
        help="Model identifier for the configured provider.",
    )
    parser.add_argument(
        "--endpoint",
        default=resolve_models_endpoint(),
        help="Chat completions endpoint for the configured model provider.",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Model API max retries")
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=int(os.getenv("BUMPKIN_REQUEST_TIMEOUT", "45")),
        help="Per-request model API timeout in seconds",
    )
    parser.add_argument(
        "--case-delay-ms",
        type=int,
        default=default_case_delay_ms,
        help="Pause between fixture evals in milliseconds.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Optional number of fixtures to evaluate per batch.",
    )
    parser.add_argument(
        "--batch-index",
        type=int,
        default=0,
        help="Zero-based batch index when --batch-size is provided.",
    )
    parser.add_argument(
        "--output-json", default="", help="Optional path to write machine-readable eval output."
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run only the model preflight check and skip fixture execution.",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero when the selected quality gate fails."
    )
    parser.add_argument(
        "--continue-on-preflight-failure",
        action="store_true",
        help="Continue fixture evaluation even when model preflight fails. Useful for deterministic/degraded smoke validation.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.8,
        help="Minimum passing ratio when --strict is used without a prompt gate baseline.",
    )
    return parser.parse_args()
