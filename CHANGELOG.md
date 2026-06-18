# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
plus the [PEP 440](https://peps.python.org/pep-0440/) pre-release scheme.

## [Unreleased]

## [0.1.0a1] - 2026-06-18

First alpha release. The API surface is expected to change before `0.1.0`.

### Added
- `Proxy6Client` — synchronous client covering every documented endpoint:
  `get_price`, `get_count`, `get_country`, `get_proxy`, `set_descr`, `buy`,
  `prolong`, `delete`, `check`, plus the keyless `account()` call.
- Typed dataclass response models (`Proxy`, `Order`, `PriceQuote`,
  `PriceTable`, `ProlongResult`, `CheckResult`, etc.) with parsed
  `datetime` / `int` / `bool` values.
- Enums: `Version`, `ProxyType`, `State`.
- Per-code exception subclasses for all 17 documented API errors
  (`AuthError`, `InsufficientBalanceError`, `NotFoundError`, etc.),
  selected automatically via `Proxy6APIError.__new__`.
- `RateLimiter`: thread-safe sliding-window limiter shared across clients
  by default (3 req/s). Configurable per-client; pass `rate_limiter=None`
  to disable.
- `PROXY6_API_KEY` environment-variable fallback so `Proxy6Client()` works
  with no arguments.
- Integration test suite (`tests/test_integration.py`) that exercises every
  read-only endpoint against the live API; skipped when `PROXY6_API_KEY`
  is unset.
- GitHub Actions: CI runs the unit suite on Python 3.13 and 3.14 for every
  push / PR; the release workflow runs the full suite (including
  integration) when a GitHub Release is published.

[Unreleased]: https://github.com/AsyncAlchemist/proxy6-sdk/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/AsyncAlchemist/proxy6-sdk/releases/tag/v0.1.0a1
