from __future__ import annotations

import re

import pytest
import responses

from proxy6 import (
    Proxy6APIError,
    Proxy6Client,
    State,
    Version,
)
from proxy6.client import DEFAULT_BASE_URL
from proxy6.models import PriceQuote, PriceTable

API_KEY = "test_key"
ACCOUNT_FIELDS = {
    "status": "yes",
    "user_id": "1",
    "balance": "48.80",
    "currency": "RUB",
}


def _url(method: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(DEFAULT_BASE_URL)}/{API_KEY}/{method}/.*")


@pytest.fixture
def client() -> Proxy6Client:
    return Proxy6Client(api_key=API_KEY)


@responses.activate
def test_account(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        f"{DEFAULT_BASE_URL}/{API_KEY}/",
        json=ACCOUNT_FIELDS,
    )
    info = client.account()
    assert info.user_id == "1"
    assert info.balance == 48.80
    assert info.currency == "RUB"


@responses.activate
def test_get_price_quote(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getprice"),
        json={
            **ACCOUNT_FIELDS,
            "price": 1800,
            "price_single": 0.6,
            "period": 30,
            "count": 100,
        },
    )
    quote = client.get_price(count=100, period=30, version=Version.IPV6)
    assert isinstance(quote, PriceQuote)
    assert quote.price == 1800
    assert quote.price_single == 0.6
    assert quote.count == 100
    assert quote.account.currency == "RUB"

    sent = responses.calls[0].request.url
    assert "count=100" in sent
    assert "period=30" in sent
    assert "version=6" in sent


@responses.activate
def test_get_price_table(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getprice"),
        json={
            **ACCOUNT_FIELDS,
            "data": {
                "6": {"3": 2.95, "7": 5.51},
                "4": {"7": 28, "30": 120},
            },
        },
    )
    table = client.get_price()
    assert isinstance(table, PriceTable)
    assert table.data[Version.IPV6][7] == 5.51
    assert table.data[Version.IPV4][30] == 120.0


@responses.activate
def test_get_count(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getcount"),
        json={**ACCOUNT_FIELDS, "count": 971},
    )
    result = client.get_count("ru", Version.IPV6)
    assert result.count == 971
    sent = responses.calls[0].request.url
    assert "country=ru" in sent
    assert "version=6" in sent


@responses.activate
def test_get_country(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getcountry"),
        json={**ACCOUNT_FIELDS, "list": ["ru", "ua", "us"]},
    )
    result = client.get_country(Version.IPV4)
    assert result.list == ["ru", "ua", "us"]


@responses.activate
def test_get_proxy_dict_shape(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getproxy"),
        json={
            **ACCOUNT_FIELDS,
            "list_count": 2,
            "list": {
                "11": {
                    "id": "11",
                    "ip": "2a00:1838:32:19f:45fb:2640::330",
                    "host": "185.22.134.250",
                    "port": "7330",
                    "user": "5svBNZ",
                    "pass": "iagn2d",
                    "type": "auto",
                    "country": "ru",
                    "date": "2016-06-19 16:32:39",
                    "date_end": "2016-07-12 11:50:41",
                    "unixtime": 1466379159,
                    "unixtime_end": 1468349441,
                    "descr": "",
                    "active": "1",
                },
                "14": {
                    "id": "14",
                    "ip": "2a00:1838:32:198:56ec:2696::386",
                    "host": "185.22.134.242",
                    "port": "7386",
                    "user": "nV5TFK",
                    "pass": "3Itr1t",
                    "type": "auto",
                    "country": "ru",
                    "date": "2016-06-27 16:06:22",
                    "date_end": "2016-07-11 16:06:22",
                    "unixtime": 1466379151,
                    "unixtime_end": 1468349441,
                    "descr": "",
                    "active": "0",
                },
            },
        },
    )
    result = client.get_proxy(state=State.ACTIVE)
    assert result.list_count == 2
    assert len(result.proxies) == 2
    p1 = next(p for p in result.proxies if p.id == 11)
    assert p1.host == "185.22.134.250"
    assert p1.port == 7330
    assert p1.user == "5svBNZ"
    assert p1.password == "iagn2d"
    assert p1.country == "ru"
    assert p1.active is True
    p2 = next(p for p in result.proxies if p.id == 14)
    assert p2.active is False
    assert p1.auth_url() == "http://5svBNZ:iagn2d@185.22.134.250:7330"


@responses.activate
def test_get_proxy_handles_nokey_list_shape(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("getproxy"),
        json={
            **ACCOUNT_FIELDS,
            "list_count": 1,
            "list": [
                {
                    "id": "11",
                    "ip": "::1",
                    "host": "1.2.3.4",
                    "port": "7000",
                    "user": "u",
                    "pass": "p",
                    "type": "auto",
                    "country": "ru",
                    "date": "2016-06-19 16:32:39",
                    "date_end": "2016-07-12 11:50:41",
                    "unixtime": 1,
                    "unixtime_end": 2,
                    "descr": "",
                    "active": "1",
                }
            ],
        },
    )
    result = client.get_proxy()
    assert len(result.proxies) == 1
    assert result.proxies[0].id == 11


@responses.activate
def test_set_descr_requires_old_or_ids(client: Proxy6Client) -> None:
    with pytest.raises(ValueError):
        client.set_descr(new="x")


@responses.activate
def test_set_descr_by_old(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("setdescr"),
        json={**ACCOUNT_FIELDS, "count": 4},
    )
    result = client.set_descr(new="newtest", old="test")
    assert result.count == 4
    sent = responses.calls[0].request.url
    assert "new=newtest" in sent
    assert "old=test" in sent


@responses.activate
def test_set_descr_by_ids(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("setdescr"),
        json={**ACCOUNT_FIELDS, "count": 2},
    )
    client.set_descr(new="x", ids=[15, 16])
    assert "ids=15%2C16" in responses.calls[0].request.url


@responses.activate
def test_buy(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("buy"),
        json={
            **ACCOUNT_FIELDS,
            "balance": 42.5,
            "order_id": 12345,
            "count": 1,
            "price": 6.3,
            "period": 7,
            "country": "ru",
            "list": {
                "15": {
                    "id": "15",
                    "ip": "2a00:1838:32:19f:45fb:2640::330",
                    "host": "185.22.134.250",
                    "port": "7330",
                    "user": "5svBNZ",
                    "pass": "iagn2d",
                    "type": "auto",
                    "date": "2016-06-19 16:32:39",
                    "date_end": "2016-07-12 11:50:41",
                    "unixtime": 1466379159,
                    "unixtime_end": 1468349441,
                    "active": "1",
                }
            },
        },
    )
    order = client.buy(count=1, period=7, country="ru", version=Version.IPV6, auto_prolong=True)
    assert order.order_id == 12345
    assert order.price == 6.3
    assert order.proxies[0].id == 15
    assert order.proxies[0].country == "ru"
    sent = responses.calls[0].request.url
    assert "auto_prolong=" in sent
    assert "version=6" in sent


@responses.activate
def test_prolong(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("prolong"),
        json={
            **ACCOUNT_FIELDS,
            "balance": 29,
            "order_id": 12345,
            "price": 12.6,
            "period": 7,
            "count": 2,
            "list": {
                "15": {
                    "id": 15,
                    "date_end": "2016-07-15 06:30:27",
                    "unixtime_end": 1468349441,
                },
                "16": {
                    "id": 16,
                    "date_end": "2016-07-16 09:31:21",
                    "unixtime_end": 1468349529,
                },
            },
        },
    )
    result = client.prolong(period=7, ids=[15, 16])
    assert result.order_id == 12345
    assert result.price == 12.6
    assert result.count == 2
    assert {r.id for r in result.renewals} == {15, 16}
    sent = responses.calls[0].request.url
    assert "ids=15%2C16" in sent


@responses.activate
def test_delete_by_ids(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("delete"),
        json={**ACCOUNT_FIELDS, "count": 2},
    )
    result = client.delete(ids=[15, 16])
    assert result.count == 2


def test_delete_requires_arg(client: Proxy6Client) -> None:
    with pytest.raises(ValueError):
        client.delete()


@responses.activate
def test_check(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("check"),
        json={**ACCOUNT_FIELDS, "proxy_id": 15, "proxy_status": True},
    )
    result = client.check(ids=15)
    assert result.proxy_id == 15
    assert result.proxy_status is True


def test_check_requires_arg(client: Proxy6Client) -> None:
    with pytest.raises(ValueError):
        client.check()


@responses.activate
def test_api_error_raises(client: Proxy6Client) -> None:
    responses.add(
        responses.GET,
        _url("buy"),
        json={"status": "no", "error_id": 400, "error": "Error no money"},
    )
    with pytest.raises(Proxy6APIError) as exc:
        client.buy(count=1, period=7, country="ru", version=Version.IPV6)
    assert exc.value.error_id == 400
    assert "Error no money" in exc.value.error


def test_requires_api_key() -> None:
    with pytest.raises(ValueError):
        Proxy6Client(api_key="")


@responses.activate
def test_context_manager_closes_session() -> None:
    responses.add(
        responses.GET,
        re.compile(r".*/test_key/$"),
        json=ACCOUNT_FIELDS,
    )
    with Proxy6Client(api_key=API_KEY) as c:
        c.account()
