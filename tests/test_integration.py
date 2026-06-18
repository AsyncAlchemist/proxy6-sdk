"""Integration tests against the real proxy6.net API.

Skipped at module load if ``PROXY6_API_KEY`` is not set. All tests here are
**read-only** — they never call ``buy``, ``prolong``, ``delete`` or
``set_descr`` — so they cost nothing and never modify account state.

Run only the integration suite with::

    uv run pytest -m integration

Skip integration during a normal run with::

    uv run pytest -m "not integration"
"""

from __future__ import annotations

import os

import pytest

from proxy6 import (
    PriceQuote,
    PriceTable,
    Proxy6Client,
    ProxyList,
    ProxyVerifier,
    State,
    Version,
)
from proxy6.client import API_KEY_ENV_VAR

if not os.environ.get(API_KEY_ENV_VAR):
    pytest.skip(
        f"{API_KEY_ENV_VAR} not set; skipping live API integration tests",
        allow_module_level=True,
    )

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> Proxy6Client:
    # The client uses ``DEFAULT_RATE_LIMITER`` (3 req/s) automatically — no
    # need to throttle from the test side.
    with Proxy6Client() as c:
        yield c


def test_account(client: Proxy6Client) -> None:
    info = client.account()
    assert info.user_id
    assert info.balance >= 0
    assert info.currency in {"RUB", "USD"}


def test_get_price_table(client: Proxy6Client) -> None:
    table = client.get_price()
    assert isinstance(table, PriceTable)
    assert table.data, "price table should not be empty"
    for version, periods in table.data.items():
        assert isinstance(version, Version)
        assert periods, f"no periods quoted for {version}"
        for days, price in periods.items():
            assert days > 0
            assert price > 0


def test_get_price_quote(client: Proxy6Client) -> None:
    quote = client.get_price(count=1, period=7, version=Version.IPV6)
    assert isinstance(quote, PriceQuote)
    assert quote.count == 1
    assert quote.period == 7
    assert quote.price > 0
    assert quote.price_single > 0


def test_get_country_ipv6(client: Proxy6Client) -> None:
    result = client.get_country(Version.IPV6)
    assert result.list, "IPv6 should be available in at least one country"
    assert all(isinstance(c, str) and len(c) == 2 for c in result.list)


def test_get_count_for_first_country(client: Proxy6Client) -> None:
    countries = client.get_country(Version.IPV6).list
    result = client.get_count(country=countries[0], version=Version.IPV6)
    assert result.count >= 0


def test_list_proxies(client: Proxy6Client) -> None:
    result = client.get_proxy()
    assert result.list_count >= 0
    assert len(result.proxies) == result.list_count


def test_check_existing_proxy(client: Proxy6Client) -> None:
    """Liveness-check an existing proxy. Read-only on the account."""
    listing = client.get_proxy(state=State.ACTIVE)
    if not listing.proxies:
        pytest.skip("no active proxies on account; nothing to check")
    target = listing.proxies[0]
    result = client.check(ids=target.id)
    assert result.proxy_id == target.id
    assert isinstance(result.proxy_status, bool)


# ---------------------------------------------------------------------------
# Pool / cache integration — read-only.
# ---------------------------------------------------------------------------


def test_proxies_returns_proxylist_and_caches(client: Proxy6Client) -> None:
    """First call hits the API; subsequent calls return the same object."""
    a = client.proxies()
    assert isinstance(a, ProxyList)
    # The module-scoped client may have been used by earlier tests; the
    # important assertion is that two back-to-back calls are cache hits.
    b = client.proxies()
    assert a is b, "cached call should return the same ProxyList instance"


def test_proxies_refresh_true_returns_fresh_object(client: Proxy6Client) -> None:
    cached = client.proxies()
    refreshed = client.proxies(refresh=True)
    assert refreshed is not cached, "refresh=True should bypass the cache"
    assert len(refreshed) == len(cached), "pool size should be stable"


def test_proxy_list_container_protocol_on_live_data(client: Proxy6Client) -> None:
    pool = client.proxies()
    assert isinstance(pool, ProxyList)
    # Iteration + indexing + length agree with each other.
    via_iter = [p.id for p in pool]
    via_index = [pool[i].id for i in range(len(pool))]
    assert via_iter == via_index
    assert bool(pool) == (len(pool) > 0)


def test_filter_by_version_pulls_ipv4_and_ipv6_separately(
    client: Proxy6Client,
) -> None:
    """Confirm ProxyList.filter splits the pool by address family on real data."""
    pool = client.proxies()
    if not pool:
        pytest.skip("account has no proxies; can't exercise filter")

    v4 = pool.filter(version=Version.IPV4)
    v6 = pool.filter(version=Version.IPV6)

    # Every classified proxy should match its bucket.
    for p in v4:
        assert p.version == Version.IPV4, f"proxy {p.id} {p.host} not IPv4"
    for p in v6:
        assert p.version == Version.IPV6, f"proxy {p.id} {p.host} not IPv6"

    # The two buckets are disjoint and cover the full pool.
    v4_ids = {p.id for p in v4}
    v6_ids = {p.id for p in v6}
    assert not (v4_ids & v6_ids), "v4 and v6 buckets must be disjoint"
    assert v4_ids | v6_ids == {p.id for p in pool}


def test_random_pick_returns_a_pool_member(client: Proxy6Client) -> None:
    pool = client.proxies()
    if not pool:
        pytest.skip("account has no proxies; can't sample")
    chosen = pool.random()
    assert chosen.id in {p.id for p in pool}


# ---------------------------------------------------------------------------
# Verification fallback — hits real third-party IP-check services.
# ---------------------------------------------------------------------------


def test_verifier_with_default_fallback_succeeds_against_an_active_proxy(
    client: Proxy6Client,
) -> None:
    """The default chain (ipify → icanhazip → ifconfig.co → ipinfo.io) should
    survive any single provider being down by falling through to the next.
    """
    pool = client.proxies().filter(active=True, version=Version.IPV4)
    if not pool:
        pytest.skip("no active IPv4 proxies; can't run verification")
    proxy = pool[0]

    with ProxyVerifier() as v:  # default fallback chain
        leak = v.check_leak(proxy)

    # We can't predict *which* provider survived (datacenter blocks are
    # common on ifconfig.co etc.), but the seen IP should match the proxy.
    assert leak.result.ip == proxy.host, (
        f"leak detected: saw {leak.result.ip}, expected {proxy.host} "
        f"(via {leak.result.provider})"
    )
    assert not leak.leaked
    assert leak.result.provider in {
        "ipify", "icanhazip", "ifconfig.co", "ipinfo.io",
    }
