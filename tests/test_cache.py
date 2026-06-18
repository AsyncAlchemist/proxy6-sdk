"""Unit tests for the in-process proxy-pool cache on Proxy6Client."""

from __future__ import annotations

import re
import time

import pytest
import responses

from proxy6 import Proxy6Client, State, Version
from proxy6.client import DEFAULT_BASE_URL


API_KEY = "test_key"
ACCOUNT_FIELDS = {
    "status": "yes",
    "user_id": "1",
    "balance": "10.00",
    "currency": "USD",
}
PROXY_PAYLOAD = {
    "1": {
        "id": "1",
        "ip": "192.0.2.1",
        "host": "192.0.2.1",
        "port": "8000",
        "user": "u",
        "pass": "p",
        "type": "http",
        "country": "us",
        "date": "2026-01-01 00:00:00",
        "date_end": "2026-02-01 00:00:00",
        "unixtime": 1764547200,
        "unixtime_end": 1767225600,
        "active": "1",
        "descr": "a",
    },
    "2": {
        "id": "2",
        "ip": "192.0.2.2",
        "host": "192.0.2.2",
        "port": "8000",
        "user": "u",
        "pass": "p",
        "type": "http",
        "country": "us",
        "date": "2026-01-01 00:00:00",
        "date_end": "2026-02-01 00:00:00",
        "unixtime": 1764547200,
        "unixtime_end": 1767225600,
        "active": "1",
        "descr": "b",
    },
}


def _url(method: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(DEFAULT_BASE_URL)}/{API_KEY}/{method}/.*")


@pytest.fixture
def client() -> Proxy6Client:
    return Proxy6Client(api_key=API_KEY, rate_limiter=None)


def _add_getproxy_response(extra: dict | None = None) -> None:
    responses.add(
        responses.GET,
        _url("getproxy"),
        json={**ACCOUNT_FIELDS, "list_count": 2, "list": PROXY_PAYLOAD, **(extra or {})},
    )


class TestProxiesCacheBasics:
    @responses.activate
    def test_first_call_fetches_and_subsequent_calls_use_cache(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        a = client.proxies()
        b = client.proxies()
        c = client.proxies()
        # Cached object is returned by identity.
        assert a is b is c
        # Only one network call was made.
        assert len(responses.calls) == 1

    @responses.activate
    def test_refresh_true_forces_refetch(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        _add_getproxy_response()
        client.proxies()
        client.proxies(refresh=True)
        assert len(responses.calls) == 2

    @responses.activate
    def test_proxies_call_uses_state_all(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        client.proxies()
        called = responses.calls[0].request.url
        assert "state=all" in called

    @responses.activate
    def test_cache_returns_full_pool_for_local_filtering(
        self, client: Proxy6Client
    ) -> None:
        _add_getproxy_response()
        pool = client.proxies()
        # ProxyList container + filter work on cached data without another call.
        only_a = pool.filter(descr="a")
        assert len(only_a) == 1
        assert only_a[0].id == 1
        assert len(responses.calls) == 1


class TestProxiesCacheTTL:
    @responses.activate
    def test_ttl_zero_means_every_call_refetches(self) -> None:
        _add_getproxy_response()
        _add_getproxy_response()
        _add_getproxy_response()
        client = Proxy6Client(api_key=API_KEY, rate_limiter=None, proxy_cache_ttl=0)
        client.proxies()
        client.proxies()
        client.proxies()
        assert len(responses.calls) == 3

    @responses.activate
    def test_ttl_none_disables_cache(self) -> None:
        _add_getproxy_response()
        _add_getproxy_response()
        client = Proxy6Client(api_key=API_KEY, rate_limiter=None, proxy_cache_ttl=None)
        client.proxies()
        client.proxies()
        assert len(responses.calls) == 2

    @responses.activate
    def test_ttl_expiry_triggers_refetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _add_getproxy_response()
        _add_getproxy_response()

        # Freeze "now" then advance past TTL.
        fake_now = [1000.0]

        def fake_monotonic() -> float:
            return fake_now[0]

        monkeypatch.setattr("proxy6.client.time.monotonic", fake_monotonic)
        client = Proxy6Client(api_key=API_KEY, rate_limiter=None, proxy_cache_ttl=60.0)

        client.proxies()  # fetch #1 at t=1000
        fake_now[0] = 1059.0  # still inside TTL
        client.proxies()
        assert len(responses.calls) == 1

        fake_now[0] = 1061.0  # past TTL
        client.proxies()
        assert len(responses.calls) == 2


class TestCacheInvalidation:
    def _ok_setdescr(self) -> None:
        responses.add(
            responses.GET,
            _url("setdescr"),
            json={**ACCOUNT_FIELDS, "count": 1},
        )

    def _ok_delete(self) -> None:
        responses.add(
            responses.GET,
            _url("delete"),
            json={**ACCOUNT_FIELDS, "count": 1},
        )

    def _ok_buy(self) -> None:
        responses.add(
            responses.GET,
            _url("buy"),
            json={
                **ACCOUNT_FIELDS,
                "order_id": 1,
                "count": 1,
                "price": 0.35,
                "period": 7,
                "country": "us",
                "list": PROXY_PAYLOAD,
            },
        )

    def _ok_prolong(self) -> None:
        responses.add(
            responses.GET,
            _url("prolong"),
            json={
                **ACCOUNT_FIELDS,
                "order_id": 1,
                "price": 0.35,
                "period": 7,
                "count": 1,
                "list": {
                    "1": {
                        "id": 1,
                        "date_end": "2026-03-01 00:00:00",
                        "unixtime_end": 1769904000,
                    }
                },
            },
        )

    @responses.activate
    def test_buy_invalidates(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        self._ok_buy()
        _add_getproxy_response()

        client.proxies()
        client.buy(count=1, period=7, country="us", version=Version.IPV4)
        client.proxies()
        # Two getproxy + one buy = 3 calls.
        assert len(responses.calls) == 3

    @responses.activate
    def test_prolong_invalidates(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        self._ok_prolong()
        _add_getproxy_response()

        client.proxies()
        client.prolong(period=7, ids=1)
        client.proxies()
        assert len(responses.calls) == 3

    @responses.activate
    def test_delete_invalidates(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        self._ok_delete()
        _add_getproxy_response()

        client.proxies()
        client.delete(ids=1)
        client.proxies()
        assert len(responses.calls) == 3

    @responses.activate
    def test_set_descr_invalidates(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        self._ok_setdescr()
        _add_getproxy_response()

        client.proxies()
        client.set_descr(new="foo", ids=1)
        client.proxies()
        assert len(responses.calls) == 3

    @responses.activate
    def test_explicit_invalidate_works(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        _add_getproxy_response()

        client.proxies()
        client.invalidate_proxy_cache()
        client.proxies()
        assert len(responses.calls) == 2

    @responses.activate
    def test_get_proxy_does_not_invalidate_cache(self, client: Proxy6Client) -> None:
        # get_proxy is a read; calling it shouldn't drop the cache.
        _add_getproxy_response()  # proxies() initial fetch
        _add_getproxy_response()  # explicit get_proxy direct call
        # (Note: we do NOT add a third response — that proves the second
        # proxies() call below comes from cache, not a network round-trip.)

        client.proxies()
        client.get_proxy(state=State.ACTIVE)
        cached = client.proxies()
        assert cached is not None
        assert len(responses.calls) == 2  # just the two we set up


class TestClientLevelOneShotFactories:
    """Client.requests_session / httpx_client / select_proxy etc."""

    @responses.activate
    def test_select_proxy_returns_a_match_from_cached_pool(
        self, client: Proxy6Client
    ) -> None:
        _add_getproxy_response()
        proxy = client.select_proxy(country="us")
        assert proxy.country == "us"
        # Only one API call — used the cache.
        assert len(responses.calls) == 1

    @responses.activate
    def test_select_proxy_active_default_excludes_expired(
        self, client: Proxy6Client
    ) -> None:
        # Override the canned payload to include an inactive proxy.
        responses.add(
            responses.GET,
            _url("getproxy"),
            json={
                **ACCOUNT_FIELDS,
                "list_count": 2,
                "list": {
                    "1": {**PROXY_PAYLOAD["1"], "active": "0"},
                    "2": PROXY_PAYLOAD["2"],
                },
            },
        )
        proxy = client.select_proxy()
        assert proxy.id == 2  # only the active one
        assert proxy.active is True

    @responses.activate
    def test_select_proxy_active_none_includes_expired(
        self, client: Proxy6Client
    ) -> None:
        responses.add(
            responses.GET,
            _url("getproxy"),
            json={
                **ACCOUNT_FIELDS,
                "list_count": 1,
                "list": {"1": {**PROXY_PAYLOAD["1"], "active": "0"}},
            },
        )
        proxy = client.select_proxy(active=None)
        assert proxy.id == 1
        assert proxy.active is False

    @responses.activate
    def test_select_proxy_raises_when_nothing_matches(
        self, client: Proxy6Client
    ) -> None:
        _add_getproxy_response()
        with pytest.raises(LookupError, match="country"):
            client.select_proxy(country="zz")

    @responses.activate
    def test_requests_session_one_liner(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        sess = client.requests_session(country="us")
        # The session should route through one of our cached proxies.
        assert sess.proxies["http"].endswith(":8000")
        assert sess.proxies["http"].startswith("http://u:p@192.0.2.")
        assert len(responses.calls) == 1  # single API call

    @responses.activate
    def test_httpx_client_one_liner(self, client: Proxy6Client) -> None:
        import httpx
        _add_getproxy_response()
        client_obj = client.httpx_client(country="us", timeout=5.0)
        assert isinstance(client_obj, httpx.Client)
        client_obj.close()

    @responses.activate
    def test_httpx_async_client_one_liner(self, client: Proxy6Client) -> None:
        import httpx
        _add_getproxy_response()
        client_obj = client.httpx_async_client(country="us")
        assert isinstance(client_obj, httpx.AsyncClient)
        # Don't await aclose() — we never opened the loop. Discarding is fine
        # since no connection has been opened.

    @responses.activate
    def test_aiohttp_kwargs_one_liner(self, client: Proxy6Client) -> None:
        _add_getproxy_response()
        kw = client.aiohttp_kwargs(country="us")
        assert set(kw) == {"proxy"}
        assert kw["proxy"].startswith("http://u:p@192.0.2.")

    @responses.activate
    def test_factories_share_pool_cache(self, client: Proxy6Client) -> None:
        # Three different one-liners back-to-back should still trigger only
        # one /getproxy round-trip.
        _add_getproxy_response()
        client.requests_session(country="us")
        client.aiohttp_kwargs(country="us")
        client.select_proxy(country="us")
        assert len(responses.calls) == 1
