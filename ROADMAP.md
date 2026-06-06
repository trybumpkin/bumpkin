# Roadmap

## Where Bumpkin Is Today

Bumpkin is in a pretty good place for:

- release-scoped GitHub Action flow
- merged PR aggregation since the previous tag
- release preview and release publish modes
- deterministic release notes plus model-assisted SemVer classification

Right now the product mostly centers on:

- `release_preview`
- `release_publish`
- a clean install path through `trybumpkin/bumpkin-action`

## Current Support Reality

The core works best when a repo has:

- clear public API boundaries
- disciplined SemVer expectations
- readable diffs
- stable release practices

JS/TS is where the first eval work started, but the goal is not to stay JS/TS-only.

## What Needs Work Next

### 1. Public API boundary clarity

We need stronger and more obvious configuration for:

- public API entrypoints
- public API paths
- internal paths
- low-signal paths

This is one of the biggest things that affects whether the SemVer call is trustworthy.

### 2. Better support for Python

Python support still needs work around:

- stronger public export detection
- better handling of module-level API changes
- clearer package boundary reasoning
- more Python-specific eval fixtures

### 3. Better support for other languages

We should grow this carefully instead of acting like broad support is already done.

Near-term candidates:

- Go
- Rust
- Java/Kotlin

Each language needs:

- representative fixtures
- explicit support expectations
- public API heuristics that fit the ecosystem

### 4. Better ambiguity handling

We should keep improving cases where the deterministic engine is unsure:

- low-confidence diffs
- mixed-signal release batches
- manual-review outcomes

The goal is not fake certainty.
The goal is better `needs_review` behavior and better model help when things are unclear.

### 5. Cleaner release UX

The Action-first flow is the right default right now, but the release UX still needs cleanup:

- clearer workflow summaries
- cleaner release artifacts
- easier tagging guidance
- tighter docs around provider setup

## Practical Near-Term Plan

1. Keep the default CI small and reliable.
2. Keep evals available as a separate manual workflow.
3. Improve Python support.
4. Expand language coverage only when fixtures and heuristics are good enough.
5. Keep the public product story centered on the Action.
