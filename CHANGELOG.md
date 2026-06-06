# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Made the release-scoped preview path artifact-first and non-noisy by avoiding PR comment posting during release previews.
- Added clean `needs_review` handling for unresolved release batches instead of failing the workflow.
- Clarified OSS docs around release-scoped usage, provider setup, and recommended public API config.
- Split Action runtime dependencies from dev/test dependencies while keeping a standalone Action package for distribution.
- Moved GitHub App shell notes out of the root product path to keep the repo Action-first.
- Kept the install path on `trybumpkin/bumpkin-action`.
