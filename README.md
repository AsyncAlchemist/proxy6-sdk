# proxy6-sdk

[![CI](https://github.com/AsyncAlchemist/proxy6-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/AsyncAlchemist/proxy6-sdk/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AsyncAlchemist/proxy6-sdk/graph/badge.svg)](https://codecov.io/gh/AsyncAlchemist/proxy6-sdk)
[![PyPI version](https://badge.fury.io/py/proxy6-sdk.svg)](https://pypi.org/project/proxy6-sdk/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Unofficial** — this project is a community-built client for
> [Proxy6.net](https://proxy6.net/) and is **not affiliated with, endorsed by,
> or supported by Proxy6.net**. All trademarks belong to their respective
> owners.

A typed Python SDK for the [Proxy6.net API](https://proxy6.net/en/developers).

Covers all nine documented endpoints — `getprice`, `getcount`, `getcountry`,
`getproxy`, `setdescr`, `buy`, `prolong`, `delete`, `check` — plus the
keyless `account` call. Responses are parsed into dataclasses with proper
types (`datetime`, `int`, `bool`, enums) instead of the raw strings the API
returns.

> **Status:** alpha (`0.1.0a1`). The public API may change before `0.1.0`.
> See [CHANGELOG.md](CHANGELOG.md) for what shipped.

## Install

```sh
uv add proxy6-sdk
# or
pip install proxy6-sdk
```

The distribution name is `proxy6-sdk`; the import name is `proxy6`:

```python
from proxy6 import Proxy6Client
```

Requires Python 3.13+.

## Quick start

```python
from proxy6 import Proxy6Client, Version

# Pass the key explicitly...
with Proxy6Client(api_key="YOUR_KEY") as client:
    ...

# ...or set PROXY6_API_KEY in the environment and omit it.
with Proxy6Client() as client:
    info = client.account()
    print(f"Balance: {info.balance} {info.currency}")

    # How much for 10 Russian IPv6 proxies for 30 days?
    quote = client.get_price(count=10, period=30, version=Version.IPV6)
    print(quote.price, quote.price_single)

    # Buy them
    order = client.buy(
        count=10,
        period=30,
        country="ru",
        version=Version.IPV6,
        descr="scraper-pool",
    )
    for proxy in order.proxies:
        print(proxy.auth_url())  # http://user:pass@host:port
```

## API surface

| Method                                              | Purpose                                        |
| --------------------------------------------------- | ---------------------------------------------- |
| `account()`                                         | Balance / currency (calls API with no method)  |
| `get_price(count?, period?, version?)`              | Single-quote or full price table               |
| `get_count(country, version?)`                      | Available stock for a country                  |
| `get_country(version)`                              | List of ISO2 codes for a version               |
| `get_proxy(state?, descr?, page?, limit?)`          | List your proxies                              |
| `set_descr(new, old?, ids?)`                        | Rename the technical comment                   |
| `buy(count, period, country, version, descr?, ...)` | Purchase proxies                               |
| `prolong(period, ids)`                              | Extend existing proxies                        |
| `delete(ids?, descr?)`                              | Delete by id or by comment                     |
| `check(ids?, proxy?)`                               | Liveness check via id or `ip:port:user:pass`   |
| `proxies(refresh?)`                                 | Cached view of the full pool (filter locally)  |
| `invalidate_proxy_cache()`                          | Drop the pool cache                            |
| `select_proxy(country?, version?, active?, ...)`    | Pick one proxy from the pool, raises if nothing matches |
| `requests_session(country?, version?, ...)`         | One-shot: pick a proxy → ready `requests.Session` |
| `httpx_client(country?, ..., **kwargs)`             | One-shot: pick a proxy → ready `httpx.Client`  |
| `httpx_async_client(country?, ..., **kwargs)`       | One-shot: pick a proxy → ready `httpx.AsyncClient` |
| `aiohttp_kwargs(country?, ...)`                     | One-shot: pick a proxy → kwargs for `aiohttp` requests |

### Using your proxies in an HTTP client

The SDK ships convenience helpers at two levels so you don't have to stitch
together proxy URLs by hand.

**One-liner on the client** — picks a proxy from the cached pool (auto-filtered
to `active=True` by default) and hands back a ready-to-use HTTP client:

```python
with Proxy6Client() as c:
    with c.requests_session(country="us") as s:
        r = s.get("https://api.ipify.org?format=json", timeout=10)
```

**Per-proxy** — when you want to pick the proxy yourself first (e.g. inspect
it, reuse it across calls) and produce the client from there:

```python
with Proxy6Client() as c:
    proxy = c.select_proxy(country="us", version=Version.IPV4)
    # equivalently: c.proxies().filter(country="us", version=Version.IPV4).random()
    with proxy.requests_session() as s:
        r = s.get("https://api.ipify.org?format=json", timeout=10)
```

Both forms share the cache — back-to-back calls don't re-hit `/getproxy`.
Filter args (`country`, `version`, `active`, `descr`, `type`) are the same
as :meth:`ProxyList.filter`. If nothing matches, a `LookupError` is raised
with the criteria that failed.

#### Examples per library

**requests**

```python
from proxy6 import Proxy6Client

with Proxy6Client() as c:
    # One-shot.
    with c.requests_session(country="us") as s:
        r = s.get("https://api.ipify.org?format=json", timeout=10)
        print(r.json()["ip"])

    # Per-proxy (lets you inspect/reuse `proxy`).
    proxy = c.select_proxy(country="us")
    with proxy.requests_session() as s:
        r = s.get("https://api.ipify.org?format=json", timeout=10)
```

**httpx (sync)**

```python
from proxy6 import Proxy6Client

with Proxy6Client() as c:
    with c.httpx_client(country="us", timeout=10) as client:
        r = client.get("https://api.ipify.org?format=json")
        print(r.json()["ip"])

    # Per-proxy.
    proxy = c.select_proxy(country="us")
    with proxy.httpx_client(timeout=10) as client:
        r = client.get("https://api.ipify.org?format=json")
```

**httpx (async)**

```python
import asyncio
from proxy6 import Proxy6Client

async def main() -> None:
    with Proxy6Client() as c:
        async with c.httpx_async_client(country="us", timeout=10) as client:
            r = await client.get("https://api.ipify.org?format=json")
            print(r.json()["ip"])

asyncio.run(main())
```

**aiohttp** — `aiohttp` has no session-level proxy setting, so the proxy
goes on each request. The helper returns a kwargs dict you spread in:

```python
import asyncio
import aiohttp
from proxy6 import Proxy6Client

async def main() -> None:
    with Proxy6Client() as c:
        kw = c.aiohttp_kwargs(country="us")  # {"proxy": "http://u:p@host:port"}
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.ipify.org?format=json", **kw) as r:
                print((await r.json())["ip"])

asyncio.run(main())
```

**subprocess / curl / wget** — env-var format for shelling out:

```python
import os
import subprocess
from proxy6 import Proxy6Client

with Proxy6Client() as c:
    proxy = c.select_proxy(country="us")
    subprocess.run(
        ["curl", "https://api.ipify.org"],
        env={**os.environ, **proxy.as_env()},
    )
```

**Just give me the URL / dict** — if you're plugging into another HTTP lib
not covered above:

```python
proxy.auth_url()              # "http://user:pass@host:port"
proxy.as_requests_dict()      # {"http": auth_url, "https": auth_url}
proxy.aiohttp_kwargs()        # {"proxy": auth_url}
```

`httpx` and `aiohttp` are imported lazily — they only need to be installed
if you actually call the corresponding helper.

### Caching the proxy pool

`get_proxy()` is the raw API call and always hits the wire. For the
"give me my pool, I'll filter locally" workflow there's `proxies()`, which
fetches the full pool once and reuses it for repeated calls:

```python
pool = client.proxies()                       # one API call
us_v4 = pool.filter(country="us", version=Version.IPV4, active=True)
proxy = us_v4.random()
client.proxies()                              # served from cache, no HTTP
```

- Default TTL is 24 hours. Override with
  `Proxy6Client(proxy_cache_ttl=3600)` (seconds) or pass `None` to disable
  caching entirely.
- The cache is **automatically invalidated** after any state-changing call
  (`buy`, `prolong`, `delete`, `set_descr`), so newly-bought proxies show up
  on the next `proxies()` call.
- Force a refresh with `client.proxies(refresh=True)` or drop the cache
  explicitly with `client.invalidate_proxy_cache()`.
- `ProxyList` is iterable / sized / indexable and supports `filter(...)`
  (`country`, `version`, `active`, `descr`, `type`) and `random(*, rng=None)`
  so most pool workflows don't need to touch `client.proxies` directly.

### Authentication

The client resolves the API key in this order:

1. The `api_key=` constructor argument
2. The `PROXY6_API_KEY` environment variable

If neither is set, `Proxy6Client()` raises `ValueError`. The SDK does **not**
load `.env` files itself — if you keep your key in `.env`, use
[python-dotenv](https://github.com/theskumar/python-dotenv) in your
application:

```python
from dotenv import load_dotenv
from proxy6 import Proxy6Client

load_dotenv()
client = Proxy6Client()
```

### Enums

```python
from proxy6 import Version, State, ProxyType

Version.IPV4_SHARED  # 3
Version.IPV4         # 4
Version.MTPROTO      # 5
Version.IPV6         # 6

State.ACTIVE | State.EXPIRED | State.EXPIRING | State.ALL
ProxyType.HTTP | ProxyType.SOCKS
```

### Errors

The API uses an envelope of `{"status":"no","error_id":N,"error":"..."}`. Each
documented error code has its own exception subclass, so you can catch
specific failures directly:

```python
from proxy6 import (
    InsufficientBalanceError,
    NotEnoughProxiesError,
    Proxy6APIError,
)

try:
    client.buy(count=100, period=30, country="ru", version=Version.IPV6)
except InsufficientBalanceError:
    topup()
except NotEnoughProxiesError:
    wait_and_retry()
except Proxy6APIError as e:
    # Catch-all for anything else
    log.error("proxy6 %s: %s", e.error_id, e.error)
```

| Code | Exception                  | Meaning                                  |
| ---: | -------------------------- | ---------------------------------------- |
|   30 | `UnknownError`             | Unknown error                            |
|  100 | `AuthError`                | Wrong API key                            |
|  105 | `IPNotAllowedError`        | IP restriction blocked the call          |
|  110 | `MethodError`              | Wrong method name                        |
|  200 | `InvalidCountError`        | Bad proxies quantity                     |
|  210 | `InvalidPeriodError`       | Bad period (days)                        |
|  220 | `InvalidCountryError`      | Bad country code                         |
|  230 | `InvalidIdsError`          | Bad proxy id list                        |
|  240 | `InvalidVersionError`      | Bad proxy version                        |
|  250 | `InvalidDescriptionError`  | Bad technical description                |
|  260 | `InvalidProxyTypeError`    | Bad proxy type/protocol                  |
|  270 | `InvalidPortError`         | Bad port                                 |
|  280 | `InvalidProxyStringError`  | Bad `ip:port:user:pass` for `check`      |
|  300 | `NotEnoughProxiesError`    | Stock too low                            |
|  400 | `InsufficientBalanceError` | Zero / low balance                       |
|  404 | `NotFoundError`            | Element not found                        |
|  410 | `PriceCalculationError`    | Cost ≤ 0                                 |

The raw documented messages are also exposed as the `proxy6.ERROR_CODES`
dict.

### Rate limiting

The API allows **3 requests per second**; over that limit it returns HTTP 429.
The SDK ships with a thread-safe sliding-window limiter that all
`Proxy6Client` instances share by default, so you don't have to think about
it — concurrent calls just block long enough to stay under the cap.

```python
from proxy6 import Proxy6Client, RateLimiter

# Default — uses the process-wide DEFAULT_RATE_LIMITER (3/s).
client = Proxy6Client()

# Custom limit (e.g. you have a higher-tier agreement).
client = Proxy6Client(rate_limiter=RateLimiter(max_requests=10, period=1.0))

# Disable entirely (you're handling throttling yourself).
client = Proxy6Client(rate_limiter=None)
```

### Verifying a proxy against a live IP-check service

`ProxyVerifier` routes a request through a proxy and asks a public
"what's my IP" service what it sees, so you can confirm the proxy is
egressing as expected and your real IP isn't leaking. By default it walks
through four built-in providers in order and returns the first success,
so a single provider being down or blocking your IP doesn't break the
check.

```python
from proxy6 import Proxy6Client, ProxyVerifier

with Proxy6Client() as c:
    proxy = c.proxies().filter(country="us", active=True).random()

with ProxyVerifier() as v:                              # fallback enabled by default
    leak = v.check_leak(proxy)
    print(leak.result.ip, leak.result.country, leak.leaked, leak.result.provider)
```

`check_leak()` returns a `LeakCheck` whose `leaked` property is `True`
whenever the IP the service saw differs from `proxy.host` — i.e. either
the proxy isn't doing its job, or traffic bypassed it entirely.

Built-in providers (the default chain, in order):

| Provider                    | Endpoint                                          | Data returned                                                                   |
| --------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| `IpifyProvider`             | `api.ipify.org` / `api6.ipify.org`                | IP only — smallest moving part                                                  |
| `IcanhazipProvider`         | `ipv4.icanhazip.com` / `ipv6.icanhazip.com`       | IP only, plain text                                                             |
| `IfconfigCoProvider`        | `ipv4.ifconfig.co/json` / `ipv6.ifconfig.co/json` | IP + country + region + city + ASN                                              |
| `IpinfoIoProvider`          | `ipinfo.io/json`                                  | IP + country + region + city + ASN (token optional for higher free-tier limits) |

Pin a single provider (no fallback) or control the chain explicitly:

```python
# Single provider — failures raise instead of falling back.
ProxyVerifier(provider=IpifyProvider()).check(proxy)

# Custom fallback chain, tried in order.
ProxyVerifier(providers=[MyChecker(), IpifyProvider(), IcanhazipProvider()]).check(proxy)
```

If every provider in the chain fails, `check()` raises a single
`VerificationError` whose message lists each failure in order — no silent
fallbacks, no truncated history. To use a custom provider or run your own
endpoint, see [docs/VERIFICATION.md](docs/VERIFICATION.md).

### Using a custom session

Inject any `requests.Session` (e.g. with retry policies or a proxy of your
own):

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504)
)))
client = Proxy6Client(api_key="...", session=session)
```

## Development

```sh
uv sync
uv run pytest                    # unit tests only (integration is gated)
uv run pytest -m integration     # hit the real API; needs PROXY6_API_KEY
```

Put your key in a local `.env`; `tests/conftest.py` loads it automatically.

User-visible changes are tracked in [CHANGELOG.md](CHANGELOG.md) — add an
entry under `[Unreleased]` whenever you ship something that affects the
public API.

## License

MIT — see [LICENSE](LICENSE). This is an unofficial project and ships with
no warranty of fitness for any particular purpose.
