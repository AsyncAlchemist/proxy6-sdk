"""Modular proxy IP verification.

Built-in providers hit small public "what's my IP" services and convert their
responses to a common :class:`VerificationResult`. Users can plug in their own
by implementing the :class:`VerificationProvider` protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

import requests

from .enums import Version
from .models import Proxy


class VerificationError(Exception):
    """Raised when a verification call fails to produce a usable result."""


@dataclass(slots=True)
class VerificationResult:
    """Normalized output from any verification provider.

    Only ``ip`` and ``provider`` are guaranteed to be set. Richer providers
    populate location/ASN fields; minimal ones leave them ``None``. The
    untouched payload is kept on ``raw`` for debugging or custom checks.
    """

    ip: str
    provider: str
    country: str | None = None
    region: str | None = None
    city: str | None = None
    asn: int | None = None
    asn_org: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LeakCheck:
    """Comparison of the IP a verifier saw against ``proxy.host``."""

    result: VerificationResult
    expected_ip: str

    @property
    def matches(self) -> bool:
        return self.result.ip == self.expected_ip

    @property
    def leaked(self) -> bool:
        return not self.matches


@runtime_checkable
class VerificationProvider(Protocol):
    """A pluggable IP-check endpoint.

    Implement ``url(version)`` to return the URL to hit (the provider may pick
    a different host per address family) and ``parse(body, status_code)`` to
    convert the response to a :class:`VerificationResult`.
    """

    name: str

    def url(self, version: Version) -> str: ...
    def parse(self, body: bytes, status_code: int) -> VerificationResult: ...


def _safe_json(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise VerificationError(f"non-JSON body: {body[:200]!r}") from e
    if not isinstance(data, dict):
        raise VerificationError(f"expected JSON object, got {type(data).__name__}")
    return data


def _is_ipv6(version: Version | int) -> bool:
    return int(version) == int(Version.IPV6)


class IpifyProvider:
    """``api.ipify.org`` / ``api6.ipify.org`` — minimal, returns just the IP."""

    name = "ipify"

    def url(self, version: Version) -> str:
        host = "api6.ipify.org" if _is_ipv6(version) else "api.ipify.org"
        return f"https://{host}?format=json"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        data = _safe_json(body)
        if "ip" not in data:
            raise VerificationError(f"ipify response missing 'ip': {data!r}")
        return VerificationResult(ip=str(data["ip"]), provider=self.name, raw=data)


class IcanhazipProvider:
    """``ipv4.icanhazip.com`` / ``ipv6.icanhazip.com`` — plain-text IP only."""

    name = "icanhazip"

    def url(self, version: Version) -> str:
        host = "ipv6.icanhazip.com" if _is_ipv6(version) else "ipv4.icanhazip.com"
        return f"https://{host}"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        ip = body.decode("ascii", errors="replace").strip()
        if not ip:
            raise VerificationError("icanhazip returned an empty body")
        return VerificationResult(ip=ip, provider=self.name, raw={"ip": ip})


class IfconfigCoProvider:
    """``ifconfig.co/json`` — JSON with country/ASN, family forced by hostname."""

    name = "ifconfig.co"

    def url(self, version: Version) -> str:
        host = "ipv6.ifconfig.co" if _is_ipv6(version) else "ipv4.ifconfig.co"
        return f"https://{host}/json"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        data = _safe_json(body)
        if "ip" not in data:
            raise VerificationError(f"ifconfig.co response missing 'ip': {data!r}")
        asn_raw = data.get("asn")
        asn: int | None = None
        if isinstance(asn_raw, str) and asn_raw.startswith("AS"):
            try:
                asn = int(asn_raw[2:])
            except ValueError:
                asn = None
        elif isinstance(asn_raw, int):
            asn = asn_raw
        return VerificationResult(
            ip=str(data["ip"]),
            country=data.get("country_iso") or None,
            region=data.get("region_name") or None,
            city=data.get("city") or None,
            asn=asn,
            asn_org=data.get("asn_org") or None,
            raw=data,
            provider=self.name,
        )


class IpinfoIoProvider:
    """``ipinfo.io/json`` — city/region/country plus ASN in the ``org`` field.

    Pass ``token`` for the free-tier 50k/mo allowance; without one the
    endpoint still works but is rate-limited more aggressively.
    """

    name = "ipinfo.io"

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def url(self, version: Version) -> str:
        # ipinfo.io doesn't expose family-forced hostnames; the proxy decides
        # which family is used to reach the resolver / endpoint.
        if self.token:
            return f"https://ipinfo.io/json?token={self.token}"
        return "https://ipinfo.io/json"

    def parse(self, body: bytes, status_code: int) -> VerificationResult:
        data = _safe_json(body)
        if "ip" not in data:
            raise VerificationError(f"ipinfo.io response missing 'ip': {data!r}")
        org = data.get("org", "")
        asn: int | None = None
        asn_org: str | None = None
        if isinstance(org, str) and org.startswith("AS"):
            head, _, tail = org.partition(" ")
            try:
                asn = int(head[2:])
            except ValueError:
                pass
            asn_org = tail or None
        return VerificationResult(
            ip=str(data["ip"]),
            country=data.get("country") or None,
            region=data.get("region") or None,
            city=data.get("city") or None,
            asn=asn,
            asn_org=asn_org,
            raw=data,
            provider=self.name,
        )


DEFAULT_VERIFICATION_PROVIDER: VerificationProvider = IpifyProvider()
DEFAULT_VERIFICATION_PROVIDERS: tuple[VerificationProvider, ...] = (
    IpifyProvider(),
    IcanhazipProvider(),
    IfconfigCoProvider(),
    IpinfoIoProvider(),
)
DEFAULT_VERIFICATION_TIMEOUT = 10.0


class ProxyVerifier:
    """Route a verification request through a proxy and parse the result.

    With no arguments, tries the four built-in providers (ipify, icanhazip,
    ifconfig.co, ipinfo.io) in order and returns the first success. Pass
    ``provider=`` to pin one (failures will raise instead of falling back),
    or ``providers=`` to control the fallback order and contents explicitly.

    Example::

        # Default — fall through the built-ins.
        with ProxyVerifier() as v:
            leak = v.check_leak(proxy)
            assert not leak.leaked, f"saw {leak.result.ip}, expected {leak.expected_ip}"

        # Single provider, no fallback.
        ProxyVerifier(provider=IpifyProvider()).check(proxy)

        # Custom fallback order.
        ProxyVerifier(providers=[my_provider, IpifyProvider()]).check(proxy)
    """

    def __init__(
        self,
        provider: VerificationProvider | None = None,
        *,
        providers: Sequence[VerificationProvider] | None = None,
        timeout: float = DEFAULT_VERIFICATION_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        if provider is not None and providers is not None:
            raise ValueError("pass either `provider` or `providers`, not both")
        if provider is not None:
            chain: tuple[VerificationProvider, ...] = (provider,)
        elif providers is not None:
            chain = tuple(providers)
            if not chain:
                raise ValueError("`providers` cannot be empty")
        else:
            chain = DEFAULT_VERIFICATION_PROVIDERS
        self.providers: tuple[VerificationProvider, ...] = chain
        self.timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None

    @property
    def provider(self) -> VerificationProvider:
        """Convenience: the first (and possibly only) provider in the chain."""
        return self.providers[0]

    def __enter__(self) -> ProxyVerifier:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _try_one(
        self,
        provider: VerificationProvider,
        proxy: Proxy,
        version: Version,
    ) -> VerificationResult:
        url = provider.url(version)
        auth = proxy.auth_url()
        try:
            resp = self._session.get(
                url,
                proxies={"http": auth, "https": auth},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise VerificationError(
                f"transport error via {provider.name}: {e}"
            ) from e
        if resp.status_code >= 400:
            raise VerificationError(
                f"{provider.name} returned HTTP {resp.status_code}: "
                f"{resp.text[:200]!r}"
            )
        return provider.parse(resp.content, resp.status_code)

    def check(
        self,
        proxy: Proxy,
        *,
        version: Version | None = None,
    ) -> VerificationResult:
        """Issue a request through ``proxy`` and return the normalized result.

        Tries each configured provider in order and returns the first one
        that produces a usable result. If every provider fails, raises a
        single :class:`VerificationError` summarizing each failure. If only
        one provider is configured the behavior matches a non-fallback call.

        ``version`` overrides the family autodetected from ``proxy.host``;
        use it when the proxy host isn't an IP literal or you want to force
        the provider's IPv4/IPv6 endpoint regardless.
        """
        v = version if version is not None else proxy.version
        errors: list[tuple[str, str]] = []
        for provider in self.providers:
            try:
                return self._try_one(provider, proxy, v)
            except VerificationError as e:
                errors.append((provider.name, str(e)))
        names = ", ".join(name for name, _ in errors)
        details = "; ".join(f"{name}: {err}" for name, err in errors)
        raise VerificationError(
            f"all {len(errors)} verification providers failed ({names}): {details}"
        )

    def check_leak(
        self,
        proxy: Proxy,
        *,
        version: Version | None = None,
    ) -> LeakCheck:
        """As :meth:`check`, but also compare the seen IP to the exit IP
        (``proxy.ip``).

        For proxy6's IPv6 product the SOCKS endpoint (``proxy.host``) is on
        IPv4 while the destination sees the IPv6 exit (``proxy.ip``), so the
        expected match is against ``proxy.ip``. For the IPv4 product the two
        are equal in practice.
        """
        result = self.check(proxy, version=version)
        return LeakCheck(result=result, expected_ip=proxy.ip)
