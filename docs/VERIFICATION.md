# Custom Verification Providers

This document explains how the `proxy6.verify` module works and how to write
your own verification provider — either by adapting an existing IP-check
service or by running your own endpoint.

If you just want to use the built-in providers, see the **Verifying a
proxy** section of the [README](../README.md). This document is for the
case where the built-ins don't fit and you need to plug something custom in.

---

## The contract

A verification provider does two things:

1. Decides **which URL** to hit for a given address family (`IPV4` vs
   `IPV6`), because some services expose family-specific hostnames.
2. **Parses** the response into a normalized `VerificationResult`.

That's it. Anything beyond those two operations belongs in your business
logic, not the provider.

The protocol — defined in `proxy6.verify` — is intentionally small:

```python
from typing import Protocol, runtime_checkable
from proxy6 import Version, VerificationResult

@runtime_checkable
class VerificationProvider(Protocol):
    name: str

    def url(self, version: Version) -> str: ...
    def parse(self, body: bytes, status_code: int) -> VerificationResult: ...
```

You can satisfy it with a plain class, a dataclass, a frozen dataclass, or
anything else that exposes those three names. Inheritance is **not**
required — the protocol is structural, so duck typing works fine.

### The `VerificationResult` shape

```python
@dataclass(slots=True)
class VerificationResult:
    ip: str                          # required
    provider: str                    # required — set to your `name`
    country: str | None = None       # ISO2 alpha-2 if you have it
    region: str | None = None        # state / province / region
    city: str | None = None
    asn: int | None = None           # integer ASN; strip the "AS" prefix
    asn_org: str | None = None       # human-readable ASN org
    raw: dict[str, Any] = ...        # untouched upstream payload (for debug)
```

Only `ip` and `provider` are required. The optional fields are populated
when the upstream provider returns them — leave them `None` if your source
doesn't surface them. The `raw` field is for downstream callers that want
fields you didn't bother normalizing.

---

## Authoring a provider

### 1. Adapting an existing public IP-check service

This is the most common case: you found a service that returns the public
IP and you want to use it as a fallback or replacement. A minimal example:

```python
from proxy6 import Version, VerificationProvider, VerificationResult


class MyIpServiceProvider:
    name = "my-ip-service"

    def url(self, version: Version) -> str:
        # Most public services don't expose family-specific hostnames;
        # the upstream proxy picks which family is used to reach them.
        return "https://my-ip-service.example/whatami"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        import json
        data = json.loads(body)
        # Map their field names onto ours.
        return VerificationResult(
            ip=data["client_ip"],
            country=data.get("geo", {}).get("country_code"),
            city=data.get("geo", {}).get("city"),
            raw=data,
            provider=self.name,
        )
```

The `ProxyVerifier` will:

1. Compute the URL via `url(version)`,
2. Route a GET through the proxy with a 10s default timeout,
3. Hand the response body + status code to `parse()`,
4. Wrap any transport failure / non-2xx in `VerificationError` for you.

You don't need to catch network errors or check the status code yourself —
`ProxyVerifier` handles that before calling `parse()`. Your `parse` should
only fail (by raising `VerificationError`) if the body itself is malformed.

### Declaring which families your provider supports

Real-world IP-check services often only have an A record or only an AAAA
record. Routing a v6-egress proxy at a v4-only endpoint will fail at the
TCP layer with a confusing transport error.

Set `supported_versions` on the provider (frozenset of `Version` values)
and the verifier will skip your provider for unsupported families instead
of trying and failing. Providers without this attribute are assumed to
support both families (backward-compatible).

```python
from proxy6 import Version, VerificationResult


class MyV4OnlyProvider:
    name = "my-v4-only"
    # Declares it cannot handle IPv6 proxies.
    supported_versions = frozenset({Version.IPV4})

    def url(self, version: Version) -> str:
        return "https://my-v4-only.example/ip"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        import json
        return VerificationResult(
            ip=json.loads(body)["ip"], provider=self.name
        )
```

In a fallback chain (`ProxyVerifier(providers=[...])`) the verifier walks
the list and silently passes over any provider whose set doesn't contain
the proxy's family. Only failures from providers that were *actually
tried* count toward the "all providers failed" error.

All four built-in providers also accept `supported_versions=` as a
constructor kwarg so you can restrict them without subclassing:

```python
from proxy6 import IpifyProvider, Version

v4_only = IpifyProvider(supported_versions={Version.IPV4})
```

For reference, the built-in defaults are: `IpifyProvider`,
`IcanhazipProvider`, `IfconfigCoProvider` → both families;
`IpinfoIoProvider` → IPv4 only (the `ipinfo.io` endpoint has no AAAA
record).

### 2. Supporting separate IPv4 / IPv6 endpoints

If you want a strict address-family test, the cleanest way is to publish
two hostnames — one with only an A record (IPv4-only) and one with only an
AAAA record (IPv6-only). Then key off `version`:

```python
def url(self, version: Version) -> str:
    if int(version) == int(Version.IPV6):
        return "https://ipv6.my-service.example/ip"
    return "https://ipv4.my-service.example/ip"
```

If both `A` and `AAAA` are published on the same name, the upstream proxy
gets to pick which family it uses — which usually defeats the purpose of
the test.

### 3. Sending custom headers, auth, or query params

The provider returns *just a URL*, not a `requests.PreparedRequest`. To
attach an API key or custom headers, you have two options:

**(a) Bake it into the URL.** Cleanest for query-string tokens:

```python
class IpinfoIoProvider:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def url(self, version: Version) -> str:
        if self.token:
            return f"https://ipinfo.io/json?token={self.token}"
        return "https://ipinfo.io/json"
```

**(b) Inject the headers into the `requests.Session`.** Pass a configured
session to `ProxyVerifier(session=...)`:

```python
import requests
from proxy6 import ProxyVerifier

session = requests.Session()
session.headers["Authorization"] = "Bearer ..."
verifier = ProxyVerifier(provider=MyAuthedProvider(), session=session)
```

The session is reused for every check, so this also gives you connection
pooling and any retry policy you've mounted on it.

### 4. Surfacing errors

Raise `VerificationError` from `parse()` if the upstream payload is in a
shape you can't normalize. **Do not** silently return an empty / partial
result with a placeholder IP — the verifier treats every returned
`VerificationResult` as a confident answer, and a placeholder would defeat
leak detection.

```python
def parse(self, body: bytes, status_code: int) -> VerificationResult:
    data = json.loads(body)
    if "ip" not in data:
        raise VerificationError(f"my-provider: missing 'ip' in {data!r}")
    return VerificationResult(ip=data["ip"], provider=self.name, raw=data)
```

Transport / HTTP errors are surfaced for you — the verifier already wraps
`requests.RequestException` and any `status_code >= 400` into
`VerificationError` before invoking `parse()`.

---

## Running your own verification server

If you don't want to depend on a third-party IP-check service, host one
yourself. The server only needs to do one thing: return the IP it sees the
TCP peer connecting from.

### Bare-minimum endpoint (FastAPI)

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/ip")
def ip(request: Request) -> dict[str, str]:
    return {"ip": request.client.host}
```

### Or in Flask:

```python
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.get("/ip")
def ip():
    return jsonify(ip=request.remote_addr)
```

### Or nginx + a static reflect:

```nginx
location /ip {
    default_type application/json;
    return 200 '{"ip":"$remote_addr"}';
}
```

### Client-side glue

```python
from proxy6 import (
    ProxyVerifier, VerificationProvider, VerificationResult, Version,
)

class MyServerProvider:
    name = "my-server"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def url(self, version: Version) -> str:
        host_prefix = "v6." if int(version) == int(Version.IPV6) else "v4."
        return f"https://{host_prefix}{self.base_url}/ip"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        import json
        data = json.loads(body)
        return VerificationResult(
            ip=data["ip"],
            raw=data,
            provider=self.name,
        )

verifier = ProxyVerifier(provider=MyServerProvider("ip.mycompany.com"))
result = verifier.check(proxy)
```

### Things to keep in mind when running your own

- **Trust the right header.** If you sit behind Cloudflare or a load
  balancer, `request.client.host` / `$remote_addr` will be the LB's IP, not
  the proxy's. Read `CF-Connecting-IP` (Cloudflare), the leftmost trusted
  hop of `X-Forwarded-For`, or whatever your edge sets — scoped to clients
  you trust to send those headers.
- **Force address family per host.** AAAA-only and A-only hostnames are
  what make an "is the IPv6 proxy actually egressing IPv6?" test meaningful.
  Sharing one name with both records lets the proxy pick.
- **Never trust client-supplied IPs.** Always derive the answer from the
  TCP peer. Reading the IP from a query param or request body would mean
  a leak test passes for the wrong reasons.
- **Keep it cheap.** This endpoint is hit every time a caller verifies.
  Bare TCP-peer reflection is fast enough that no caching is needed.

---

## Fallback chains

Once you have a custom provider, you can mix it into a fallback chain. By
default `ProxyVerifier()` walks the four built-ins in order; to put yours
first (or replace the list entirely) pass `providers=`:

```python
from proxy6 import (
    ProxyVerifier, IpifyProvider, IcanhazipProvider,
)

verifier = ProxyVerifier(providers=[
    MyServerProvider("ip.mycompany.com"),  # try ours first
    IpifyProvider(),                       # public fallback #1
    IcanhazipProvider(),                   # public fallback #2
])

result = verifier.check(proxy)
# result.provider tells you which one actually returned data
```

If every provider in the chain raises, `ProxyVerifier.check()` raises a
single `VerificationError` whose message lists each failure in order — no
silent fallbacks, no truncated history.

---

## Testing your provider

The provider protocol is trivially mockable. Drive `url()` and `parse()`
directly without a network — they're pure functions:

```python
def test_my_provider_extracts_country():
    p = MyServerProvider("ip.example")
    body = b'{"ip":"203.0.113.7","country":"US"}'
    result = p.parse(body, 200)
    assert result.ip == "203.0.113.7"
    assert result.country == "US"
```

For end-to-end coverage, use the
[`responses`](https://github.com/getsentry/responses) library to mock the
upstream HTTP call. The `ProxyVerifier` uses a standard `requests.Session`,
so `responses.activate` intercepts the GET regardless of the proxy config:

```python
import responses
from proxy6 import ProxyVerifier

@responses.activate
def test_my_provider_end_to_end(proxy):
    responses.add(
        responses.GET,
        "https://ip.example/ip",
        json={"ip": "203.0.113.7"},
    )
    result = ProxyVerifier(provider=MyServerProvider("ip.example")).check(proxy)
    assert result.ip == "203.0.113.7"
```

See `tests/test_verify.py` in the SDK for the exact patterns used by the
built-in providers.
