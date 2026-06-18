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
