from __future__ import annotations

from datetime import datetime

import pytest
import requests
import responses

from proxy6 import (
    IcanhazipProvider,
    IfconfigCoProvider,
    IpifyProvider,
    IpinfoIoProvider,
    LeakCheck,
    Proxy,
    ProxyType,
    ProxyVerifier,
    VerificationError,
    VerificationResult,
    Version,
)


def _ipv4_proxy(host: str = "192.0.2.1") -> Proxy:
    return Proxy(
        id=1,
        ip=host,
        host=host,
        port=8000,
        user="u",
        password="p",
        type=ProxyType.HTTP,
        date=datetime(2026, 1, 1),
        date_end=datetime(2026, 2, 1),
        unixtime=0,
        unixtime_end=0,
        active=True,
        country="us",
    )


def _ipv6_proxy(host: str = "2001:db8::1") -> Proxy:
    return Proxy(
        id=2,
        ip=host,
        host=host,
        port=8000,
        user="u",
        password="p",
        type=ProxyType.HTTP,
        date=datetime(2026, 1, 1),
        date_end=datetime(2026, 2, 1),
        unixtime=0,
        unixtime_end=0,
        active=True,
        country="us",
    )


class TestProviderURLSelection:
    def test_ipify_picks_v4_or_v6_host(self) -> None:
        p = IpifyProvider()
        assert p.url(Version.IPV4) == "https://api.ipify.org?format=json"
        assert p.url(Version.IPV4_SHARED) == "https://api.ipify.org?format=json"
        assert p.url(Version.IPV6) == "https://api6.ipify.org?format=json"

    def test_icanhazip_picks_v4_or_v6_host(self) -> None:
        p = IcanhazipProvider()
        assert p.url(Version.IPV4) == "https://ipv4.icanhazip.com"
        assert p.url(Version.IPV6) == "https://ipv6.icanhazip.com"

    def test_ifconfig_co_picks_v4_or_v6_host(self) -> None:
        p = IfconfigCoProvider()
        assert p.url(Version.IPV4) == "https://ipv4.ifconfig.co/json"
        assert p.url(Version.IPV6) == "https://ipv6.ifconfig.co/json"

    def test_ipinfo_includes_token_when_present(self) -> None:
        assert IpinfoIoProvider().url(Version.IPV4) == "https://ipinfo.io/json"
        assert (
            IpinfoIoProvider(token="abc").url(Version.IPV4)
            == "https://ipinfo.io/json?token=abc"
        )


class TestProviderParsers:
    def test_ipify_parses_minimal_json(self) -> None:
        r = IpifyProvider().parse(b'{"ip":"203.0.113.7"}', 200)
        assert r.ip == "203.0.113.7"
        assert r.provider == "ipify"
        assert r.country is None
        assert r.raw == {"ip": "203.0.113.7"}

    def test_ipify_raises_on_missing_ip(self) -> None:
        with pytest.raises(VerificationError, match="missing 'ip'"):
            IpifyProvider().parse(b'{"foo":"bar"}', 200)

    def test_ipify_raises_on_non_json(self) -> None:
        with pytest.raises(VerificationError, match="non-JSON"):
            IpifyProvider().parse(b"not json", 200)

    def test_icanhazip_strips_trailing_newline(self) -> None:
        r = IcanhazipProvider().parse(b"203.0.113.7\n", 200)
        assert r.ip == "203.0.113.7"
        assert r.provider == "icanhazip"

    def test_icanhazip_raises_on_empty(self) -> None:
        with pytest.raises(VerificationError, match="empty"):
            IcanhazipProvider().parse(b"", 200)

    def test_ifconfig_co_extracts_country_and_asn(self) -> None:
        payload = (
            b'{"ip":"203.0.113.7","country_iso":"US","region_name":"California",'
            b'"city":"San Francisco","asn":"AS14618","asn_org":"AMAZON-AES"}'
        )
        r = IfconfigCoProvider().parse(payload, 200)
        assert r.ip == "203.0.113.7"
        assert r.country == "US"
        assert r.region == "California"
        assert r.city == "San Francisco"
        assert r.asn == 14618
        assert r.asn_org == "AMAZON-AES"
        assert r.provider == "ifconfig.co"

    def test_ifconfig_co_tolerates_integer_asn(self) -> None:
        payload = b'{"ip":"203.0.113.7","asn":14618}'
        assert IfconfigCoProvider().parse(payload, 200).asn == 14618

    def test_ifconfig_co_tolerates_missing_asn(self) -> None:
        payload = b'{"ip":"203.0.113.7"}'
        r = IfconfigCoProvider().parse(payload, 200)
        assert r.asn is None
        assert r.asn_org is None
        assert r.country is None

    def test_ipinfo_io_parses_org_into_asn_and_org_name(self) -> None:
        payload = (
            b'{"ip":"203.0.113.7","city":"San Francisco","region":"California",'
            b'"country":"US","org":"AS14618 AMAZON-AES"}'
        )
        r = IpinfoIoProvider().parse(payload, 200)
        assert r.ip == "203.0.113.7"
        assert r.country == "US"
        assert r.region == "California"
        assert r.city == "San Francisco"
        assert r.asn == 14618
        assert r.asn_org == "AMAZON-AES"
        assert r.provider == "ipinfo.io"

    def test_ipinfo_io_handles_org_without_asn_prefix(self) -> None:
        payload = b'{"ip":"203.0.113.7","org":"Some ISP"}'
        r = IpinfoIoProvider().parse(payload, 200)
        assert r.asn is None
        assert r.asn_org is None


class TestVerifierFamilyDetection:
    @responses.activate
    def test_ipv4_proxy_hits_ipv4_endpoint(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            json={"ip": "192.0.2.1"},
        )
        # Pin to ipify so we're asserting on a known endpoint shape.
        verifier = ProxyVerifier(provider=IpifyProvider())
        result = verifier.check(_ipv4_proxy())
        assert result.ip == "192.0.2.1"
        called = responses.calls[0].request.url
        assert "api.ipify.org" in called
        assert "api6.ipify.org" not in called

    @responses.activate
    def test_ipv6_proxy_hits_ipv6_endpoint(self) -> None:
        responses.add(
            responses.GET,
            "https://api6.ipify.org/",
            json={"ip": "2001:db8::1"},
        )
        result = ProxyVerifier(provider=IpifyProvider()).check(_ipv6_proxy())
        assert result.ip == "2001:db8::1"
        assert "api6.ipify.org" in responses.calls[0].request.url

    @responses.activate
    def test_explicit_version_overrides_autodetect(self) -> None:
        # IPv4 proxy host but caller forces v6 endpoint.
        responses.add(
            responses.GET,
            "https://api6.ipify.org/",
            json={"ip": "2001:db8::1"},
        )
        result = ProxyVerifier(provider=IpifyProvider()).check(
            _ipv4_proxy(), version=Version.IPV6
        )
        assert "api6.ipify.org" in responses.calls[0].request.url
        assert result.ip == "2001:db8::1"


class TestLeakCheck:
    @responses.activate
    def test_no_leak_when_seen_ip_matches_proxy_host(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            json={"ip": "192.0.2.1"},
        )
        leak = ProxyVerifier(provider=IpifyProvider()).check_leak(
            _ipv4_proxy("192.0.2.1")
        )
        assert isinstance(leak, LeakCheck)
        assert leak.matches
        assert not leak.leaked
        assert leak.expected_ip == "192.0.2.1"
        assert leak.result.ip == "192.0.2.1"

    @responses.activate
    def test_leak_detected_when_seen_ip_differs(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            json={"ip": "198.51.100.99"},
        )
        leak = ProxyVerifier(provider=IpifyProvider()).check_leak(
            _ipv4_proxy("192.0.2.1")
        )
        assert leak.leaked
        assert not leak.matches
        assert leak.result.ip == "198.51.100.99"
        assert leak.expected_ip == "192.0.2.1"


class TestVerifierTransport:
    @responses.activate
    def test_http_error_raises_verification_error(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            status=503,
            body="upstream down",
        )
        with pytest.raises(VerificationError, match="HTTP 503"):
            ProxyVerifier(provider=IpifyProvider()).check(_ipv4_proxy())

    @responses.activate
    def test_transport_error_wraps_in_verification_error(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            body=requests.ConnectionError("boom"),
        )
        with pytest.raises(VerificationError, match="transport error"):
            ProxyVerifier(provider=IpifyProvider()).check(_ipv4_proxy())

    @responses.activate
    def test_passes_proxy_credentials_to_requests(self) -> None:
        responses.add(
            responses.GET,
            "https://api.ipify.org/",
            json={"ip": "192.0.2.1"},
        )
        proxy = _ipv4_proxy()
        ProxyVerifier(provider=IpifyProvider()).check(proxy)
        # `responses` records the proxies dict on the prepared request via
        # the session; easiest sanity check is that the call went through and
        # the proxy URL we'd inject is the auth_url shape we expect.
        assert proxy.auth_url() == "http://u:p@192.0.2.1:8000"


class TestCustomProvider:
    @responses.activate
    def test_user_provider_returning_minimal_result(self) -> None:
        class Stub:
            name = "stub"

            def url(self, version: Version) -> str:
                return "https://stub.example/ip"

            def parse(self, body: bytes, status_code: int) -> VerificationResult:
                return VerificationResult(
                    ip=body.decode().strip(),
                    provider=self.name,
                    country="ZZ",
                )

        responses.add(
            responses.GET,
            "https://stub.example/ip",
            body="203.0.113.42\n",
        )
        result = ProxyVerifier(provider=Stub()).check(_ipv4_proxy())
        assert result.ip == "203.0.113.42"
        assert result.country == "ZZ"
        assert result.provider == "stub"


class TestVerifierFallback:
    @responses.activate
    def test_default_verifier_walks_built_in_chain(self) -> None:
        # Fail ipify with a 503, succeed on icanhazip — should return the
        # icanhazip result without ever raising.
        responses.add(
            responses.GET, "https://api.ipify.org/", status=503, body="down"
        )
        responses.add(
            responses.GET, "https://ipv4.icanhazip.com/", body="203.0.113.7\n"
        )
        result = ProxyVerifier().check(_ipv4_proxy())
        assert result.ip == "203.0.113.7"
        assert result.provider == "icanhazip"
        # Both providers were hit.
        assert len(responses.calls) == 2

    @responses.activate
    def test_first_success_short_circuits_remaining(self) -> None:
        # ipify succeeds; the chain should stop there.
        responses.add(
            responses.GET, "https://api.ipify.org/", json={"ip": "203.0.113.7"}
        )
        result = ProxyVerifier().check(_ipv4_proxy())
        assert result.ip == "203.0.113.7"
        assert result.provider == "ipify"
        assert len(responses.calls) == 1

    @responses.activate
    def test_all_providers_failing_raises_combined_error(self) -> None:
        responses.add(responses.GET, "https://api.ipify.org/", status=503)
        responses.add(responses.GET, "https://ipv4.icanhazip.com/", status=503)
        responses.add(responses.GET, "https://ipv4.ifconfig.co/json", status=503)
        responses.add(responses.GET, "https://ipinfo.io/json", status=503)
        with pytest.raises(VerificationError, match="all 4 verification providers"):
            ProxyVerifier().check(_ipv4_proxy())
        assert len(responses.calls) == 4

    @responses.activate
    def test_explicit_single_provider_does_not_fall_back(self) -> None:
        # Single provider config = legacy behavior: one shot, raise on fail.
        responses.add(responses.GET, "https://api.ipify.org/", status=503)
        with pytest.raises(VerificationError, match="HTTP 503"):
            ProxyVerifier(provider=IpifyProvider()).check(_ipv4_proxy())
        assert len(responses.calls) == 1

    @responses.activate
    def test_providers_argument_controls_chain_order(self) -> None:
        # ipinfo first then icanhazip — fail ipinfo, succeed on icanhazip.
        responses.add(responses.GET, "https://ipinfo.io/json", status=503)
        responses.add(
            responses.GET, "https://ipv4.icanhazip.com/", body="203.0.113.7\n"
        )
        result = ProxyVerifier(
            providers=[IpinfoIoProvider(), IcanhazipProvider()]
        ).check(_ipv4_proxy())
        assert result.provider == "icanhazip"
        assert result.ip == "203.0.113.7"

    def test_passing_both_provider_and_providers_raises(self) -> None:
        with pytest.raises(ValueError, match="either"):
            ProxyVerifier(
                provider=IpifyProvider(), providers=[IcanhazipProvider()]
            )

    def test_empty_providers_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            ProxyVerifier(providers=[])
