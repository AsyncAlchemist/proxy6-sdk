# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
plus the [PEP 440](https://peps.python.org/pep-0440/) pre-release scheme.

## [Unreleased]

### Changed
- **Breaking.** `Proxy.version` now infers from the exit IP (`Proxy.ip`)
  rather than the SOCKS endpoint (`Proxy.host`). proxy6's IPv6 product
  exposes a v4 SOCKS endpoint with a v6 exit, so the previous
  host-based inference labelled v6 proxies as IPv4. Callers asking "what
  version is this proxy?" almost always mean "what does the destination
  see," which is the exit. IPv4 proxies (where `host == ip`) are
  unaffected.
- **Breaking.** `ProxyVerifier.check_leak()` now compares the verifier's
  seen IP against `proxy.ip` (the exit) instead of `proxy.host` (the
  SOCKS endpoint). For the IPv6 product this fixes false-positive leak
  reports; for IPv4 proxies the two were already equal.

## [0.1.0a2] - 2026-06-18

### Added
- `ProxyVerifier` — pluggable wrapper that routes a request through a proxy
  and asks an IP-check service what it sees, returning a normalized
  `VerificationResult` (IP plus optional country / region / city / ASN).
  `check_leak()` compares the seen IP to `proxy.host` and returns a
  `LeakCheck`.
- Built-in `VerificationProvider` implementations: `IpifyProvider`,
  `IcanhazipProvider`, `IfconfigCoProvider`, `IpinfoIoProvider`. Each
  selects an IPv4/IPv6 endpoint based on the proxy's address family. Users
  can add their own by implementing the `VerificationProvider` protocol.
- **Provider fallback**: `ProxyVerifier()` now walks
  `DEFAULT_VERIFICATION_PROVIDERS` (all four built-ins) in order by default
  and returns the first success — a single provider blocking datacenter IPs
  no longer breaks the check. Pass `provider=` to pin one (no fallback) or
  `providers=` to control the chain explicitly.
- `VerificationError` — raised on transport failures, non-2xx responses,
  malformed provider payloads, and (when every provider in a fallback
  chain fails) with a combined message listing each failure.
- `Proxy.version` — address family inferred from `host`.
- `Proxy.as_requests_dict()` and `Proxy.as_env()` — format converters for
  `requests.get(proxies=...)` and subprocess / `curl` env vars.
- `Proxy.requests_session()`, `Proxy.httpx_client()`,
  `Proxy.httpx_async_client()`, `Proxy.aiohttp_kwargs()` — one-call
  factories that return HTTP clients preconfigured to route through the
  proxy. `httpx` and `aiohttp` are imported lazily so they remain optional
  dependencies.
- `ProxyList` is now iterable, sized, indexable and truthy. New methods
  `random(rng=None)` and `filter(country=?, version=?, active=?, descr=?,
  type=?)` cover the common pool workflows.
- `Proxy6Client.proxies(refresh=False)` — cached view of the full pool
  with a 24h default TTL (`proxy_cache_ttl` is configurable; pass `None`
  to disable caching). The cache is automatically invalidated after
  `buy`, `prolong`, `delete`, and `set_descr`.
- `Proxy6Client.invalidate_proxy_cache()` — explicit cache drop.
- `Proxy6Client.select_proxy(country=?, version=?, active=?, descr=?, type=?,
  rng=?)` — pick one proxy from the cached pool that matches the given
  filters. Defaults to `active=True`. Raises `LookupError` with the
  criteria summary when no proxy matches.
- `Proxy6Client.requests_session(...)`, `httpx_client(...)`,
  `httpx_async_client(...)`, `aiohttp_kwargs(...)` — one-call factories
  that combine `select_proxy(...)` with the corresponding `Proxy.<lib>`
  helper. Share the pool cache, so `client.requests_session(country="us")`
  doesn't re-hit `/getproxy` on every call.
- [docs/VERIFICATION.md](docs/VERIFICATION.md) — dedicated guide for
  authoring custom verification providers and running your own
  verification server.

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

[Unreleased]: https://github.com/AsyncAlchemist/proxy6-sdk/compare/v0.1.0a2...HEAD
[0.1.0a2]: https://github.com/AsyncAlchemist/proxy6-sdk/compare/v0.1.0a1...v0.1.0a2
[0.1.0a1]: https://github.com/AsyncAlchemist/proxy6-sdk/releases/tag/v0.1.0a1
