# Contributing

Thanks for wanting to contribute to Bumpkin.

## What kind of repo this is

This repo is the public OSS home, source tree, and GitHub Action install target for Bumpkin.

Install target:

- `trybumpkin/bumpkin`

## Good first contribution areas

- release workflow docs
- versioning edge cases
- public API boundary config
- Python support
- fixture quality and eval coverage
- release note rendering

## Before opening a larger change

If the change is big, behavioral, or architectural, please open an issue first so we can align on:

- the user problem
- the expected SemVer behavior
- how the change should be tested

## Local setup

Use Python 3.11 if possible.

Install dev dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the main checks:

```bash
ruff check src tests
ruff format --check src tests
pyright
PYTHONPATH=src python -m pytest -q
```

## Workflow expectations

Please keep the public product story clear:

- Action-first
- release-scoped
- no required hosted server
- no required Bumpkin database

Do not re-center the repo around the old app shell or webhook path unless there is a very deliberate product decision to do that.

## Evals

Default CI is intentionally small.

Heavy eval workflows live separately in:

- `.github/workflows/evals.yml`

That means:

- normal code health checks belong in `ci.yml`
- eval/canary/research-style checks belong in `evals.yml`

## Running evals locally

Run a focused eval lane with:

```bash
PYTHONPATH=src python src/eval.py \
  --language-group python \
  --model "$BUMPKIN_MODEL" \
  --endpoint "$BUMPKIN_MODELS_ENDPOINT" \
  --output-json artifacts/eval-python.json
```

Useful flags:

- `--strict` to fail when the quality gate fails
- `--prompt-gate-baseline test-diffs/baselines/python-v1.json` to compare against a baseline
- `--preflight-only` to validate provider/model access before running fixtures
- `--continue-on-preflight-failure` for degraded deterministic smoke checks

If you want the GitHub workflow version, use:

- `.github/workflows/evals.yml`

That workflow already has lanes for:

- `python`
- `go`
- `rust`
- `java-kotlin`

## Fixture and baseline layout

Fixture cases live under:

- `test-diffs/<case-name>/`

Each case normally includes:

- `diff.txt`
- `expected.json`
- `context.json`

Baselines live under:

- `test-diffs/baselines/`

Those baselines are mapped in:

- `src/eval.py`

## Adding or improving language support

When adding support for a language or improving an existing lane:

1. add or update representative fixtures under `test-diffs/`
2. add or update the language baseline JSON under `test-diffs/baselines/`
3. register the baseline in `PROMPT_GATE_BASELINES` in `src/eval.py`
4. add or update heuristics, findings, or boundary rules in the relevant engine code
5. add or update unit/integration tests near the changed logic
6. only extend the eval workflow lane when the support is real enough to defend

Good language support here means more than "the eval runs":

- the fixtures look like real repo changes
- the expected SemVer outcomes are clear
- the public API boundary assumptions make sense for that ecosystem
- the lane is stable enough to be useful to other contributors

## Changing release behavior

If you change release logic, also check:

- `release_preview`
- `release_publish`
- release note output
- any affected docs in `README.md`, `ROADMAP.md`, or `bumpkin.yml.example`

## Docs surface

We keep the public markdown surface intentionally small.

Public root docs should stay focused and useful:

- `README.md`
- `CHANGELOG.md`
- `SECURITY.md`
- `ROADMAP.md`
- `CONTRIBUTING.md`

If a doc is mostly internal planning or experiment scaffolding, it should not live as a public-facing root markdown file.

## Testing expectations

If you change behavior, try to add or update tests close to the affected layer:

- unit tests for narrow logic changes
- integration tests for release flow changes
- eval fixtures only when they help lock real product behavior

## Pull requests

Good PRs here usually include:

- a clear reason for the change
- the user-facing behavior impact
- test coverage or an explanation for why tests were not changed

If the change affects versioning logic, API-boundary detection, or release notes, call that out explicitly in the PR description.
