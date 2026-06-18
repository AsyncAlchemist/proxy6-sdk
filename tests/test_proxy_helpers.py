"""Unit tests for Proxy / ProxyList convenience methods."""

from __future__ import annotations

import random
from datetime import datetime

import aiohttp
import httpx
import pytest
import requests

from proxy6 import (
    AccountInfo,
    Proxy,
    ProxyList,
    ProxyType,
    Version,
)


def _make_proxy(
    *,
    id: int = 1,
    host: str = "192.0.2.1",
    user: str = "u",
    password: str = "p",
    port: int = 8000,
    country: str | None = "us",
    descr: str | None = "scraper",
    active: bool = True,
    type: ProxyType | str = ProxyType.HTTP,
) -> Proxy:
    return Proxy(
        id=id,
        ip=host,
        host=host,
        port=port,
        user=user,
        password=password,
        type=type,
        date=datetime(2026, 1, 1),
        date_end=datetime(2026, 2, 1),
        unixtime=0,
        unixtime_end=0,
        active=active,
        country=country,
        descr=descr,
    )


def _account() -> AccountInfo:
    return AccountInfo(user_id="1", balance=10.0, currency="USD")


# ---------------------------------------------------------------------------
# Proxy: format converters
# ---------------------------------------------------------------------------


class TestVersionProperty:
    def test_ipv4_exit_reports_ipv4(self) -> None:
        assert _make_proxy(host="192.0.2.1").version == Version.IPV4

    def test_ipv6_exit_reports_ipv6(self) -> None:
        assert _make_proxy(host="2001:db8::1").version == Version.IPV6

    def test_v4_socks_with_v6_exit_reports_ipv6(self) -> None:
        # proxy6's IPv6 product: SOCKS endpoint on IPv4 (so any client can
        # reach it) but the destination sees the IPv6 exit. `version` should
        # follow the exit, not the SOCKS endpoint.
        p = Proxy(
            id=1, ip="2001:db8::1", host="192.0.2.1", port=8000,
            user="u", password="p", type=ProxyType.HTTP,
            date=None, date_end=None, unixtime=None, unixtime_end=None,
            active=True,
        )
        assert p.version == Version.IPV6

    def test_non_ip_exit_falls_back_to_ipv4(self) -> None:
        # Proxy6 always returns IP literals in `ip`, but the fallback path
        # matters for hand-constructed test data and mock objects.
        p = Proxy(
            id=1, ip="example.com", host="example.com", port=8000,
            user="u", password="p", type=ProxyType.HTTP,
            date=None, date_end=None, unixtime=None, unixtime_end=None,
            active=True,
        )
        assert p.version == Version.IPV4


class TestAsRequestsDict:
    def test_returns_both_schemes_with_same_url(self) -> None:
        p = _make_proxy()
        d = p.as_requests_dict()
        assert d == {
            "http": "http://u:p@192.0.2.1:8000",
            "https": "http://u:p@192.0.2.1:8000",
        }

    def test_scheme_override(self) -> None:
        d = _make_proxy().as_requests_dict(scheme="socks5")
        assert d["http"].startswith("socks5://")


class TestAsEnv:
    def test_contains_upper_and_lower_case_variants(self) -> None:
        d = _make_proxy().as_env()
        assert "HTTP_PROXY" in d and "http_proxy" in d
        assert "HTTPS_PROXY" in d and "https_proxy" in d
        assert "ALL_PROXY" in d and "all_proxy" in d
        # all six should point at the same URL
        urls = set(d.values())
        assert urls == {"http://u:p@192.0.2.1:8000"}


# ---------------------------------------------------------------------------
# Proxy: HTTP-client factories
# ---------------------------------------------------------------------------


class TestRequestsSession:
    def test_returns_new_session_with_proxies_set(self) -> None:
        sess = _make_proxy().requests_session()
        assert isinstance(sess, requests.Session)
        assert sess.proxies["http"] == "http://u:p@192.0.2.1:8000"
        assert sess.proxies["https"] == "http://u:p@192.0.2.1:8000"

    def test_mutates_provided_session(self) -> None:
        existing = requests.Session()
        existing.headers["X-Foo"] = "bar"
        returned = _make_proxy().requests_session(session=existing)
        assert returned is existing
        # Caller-set state is preserved.
        assert returned.headers["X-Foo"] == "bar"
        # Proxy was applied.
        assert returned.proxies["http"].startswith("http://u:p@")


class TestHttpxClients:
    def test_httpx_client_constructs_without_error(self) -> None:
        client = _make_proxy().httpx_client()
        assert isinstance(client, httpx.Client)
        client.close()

    def test_httpx_client_forwards_kwargs(self) -> None:
        client = _make_proxy().httpx_client(timeout=5.0)
        assert isinstance(client, httpx.Client)
        assert client.timeout.connect == 5.0
        client.close()

    @pytest.mark.asyncio
    async def test_httpx_async_client_constructs_without_error(self) -> None:
        client = _make_proxy().httpx_async_client()
        assert isinstance(client, httpx.AsyncClient)
        await client.aclose()


class TestAiohttpKwargs:
    def test_returns_proxy_key_with_auth_url(self) -> None:
        kw = _make_proxy().aiohttp_kwargs()
        assert kw == {"proxy": "http://u:p@192.0.2.1:8000"}

    @pytest.mark.asyncio
    async def test_kwargs_are_accepted_by_aiohttp_request_signature(self) -> None:
        # Don't hit the network — just construct the request coroutine and
        # discard it. If aiohttp didn't accept the kwargs shape, this would
        # raise TypeError before any IO.
        kw = _make_proxy().aiohttp_kwargs()
        async with aiohttp.ClientSession() as s:
            cm = s.get("http://example.invalid/", **kw)
            cm.close()


# ---------------------------------------------------------------------------
# ProxyList: container protocol + random/filter
# ---------------------------------------------------------------------------


def _pool() -> ProxyList:
    return ProxyList(
        account=_account(),
        list_count=4,
        proxies=[
            _make_proxy(id=1, host="192.0.2.1", country="us", active=True, descr="a"),
            _make_proxy(id=2, host="192.0.2.2", country="us", active=False, descr="a"),
            _make_proxy(id=3, host="198.51.100.1", country="gb", active=True, descr="b"),
            _make_proxy(id=4, host="2001:db8::1", country="us", active=True, descr="b"),
        ],
    )


class TestProxyListContainerProtocol:
    def test_iteration(self) -> None:
        ids = [p.id for p in _pool()]
        assert ids == [1, 2, 3, 4]

    def test_length(self) -> None:
        assert len(_pool()) == 4

    def test_indexing(self) -> None:
        assert _pool()[0].id == 1
        assert _pool()[-1].id == 4

    def test_bool(self) -> None:
        assert bool(_pool()) is True
        empty = ProxyList(account=_account(), list_count=0, proxies=[])
        assert bool(empty) is False


class TestProxyListRandom:
    def test_returns_one_of_the_proxies(self) -> None:
        rng = random.Random(0)
        chosen = _pool().random(rng=rng)
        assert chosen.id in {1, 2, 3, 4}

    def test_deterministic_with_seeded_rng(self) -> None:
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        assert _pool().random(rng=rng1).id == _pool().random(rng=rng2).id

    def test_empty_raises_index_error(self) -> None:
        empty = ProxyList(account=_account(), list_count=0, proxies=[])
        with pytest.raises(IndexError, match="empty"):
            empty.random()


class TestProxyListFilter:
    def test_filter_by_country(self) -> None:
        us = _pool().filter(country="us")
        assert [p.id for p in us] == [1, 2, 4]

    def test_filter_by_active(self) -> None:
        actives = _pool().filter(active=True)
        assert [p.id for p in actives] == [1, 3, 4]

    def test_filter_by_descr(self) -> None:
        b = _pool().filter(descr="b")
        assert [p.id for p in b] == [3, 4]

    def test_filter_by_version_ipv4(self) -> None:
        v4 = _pool().filter(version=Version.IPV4)
        assert [p.id for p in v4] == [1, 2, 3]

    def test_filter_by_version_ipv6(self) -> None:
        v6 = _pool().filter(version=Version.IPV6)
        assert [p.id for p in v6] == [4]

    def test_filter_chains_combine_with_and(self) -> None:
        narrow = _pool().filter(country="us", active=True, version=Version.IPV4)
        assert [p.id for p in narrow] == [1]

    def test_filter_returns_proxy_list_preserving_account(self) -> None:
        narrow = _pool().filter(country="us")
        assert isinstance(narrow, ProxyList)
        assert narrow.account.user_id == "1"
        assert narrow.list_count == len(narrow.proxies)

    def test_filter_by_type_string(self) -> None:
        socks = _make_proxy(id=99, type=ProxyType.SOCKS)
        plist = ProxyList(account=_account(), list_count=2, proxies=[_make_proxy(id=1), socks])
        only_socks = plist.filter(type=ProxyType.SOCKS)
        assert [p.id for p in only_socks] == [99]
