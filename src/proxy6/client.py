"""Synchronous client for the Proxy6.net HTTP API."""

from __future__ import annotations

import os
import random as _random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable

import requests

from .enums import ProxyType, State, Version
from .exceptions import Proxy6APIError, Proxy6Error
from .ratelimit import DEFAULT_RATE_LIMITER, RateLimiter
from .models import (
    AccountInfo,
    CheckResult,
    CountResult,
    CountryList,
    DeleteResult,
    Order,
    PriceQuote,
    PriceTable,
    ProlongResult,
    Proxy,
    ProxyList,
    Renewal,
    SetDescrResult,
)

if TYPE_CHECKING:
    import httpx

DEFAULT_BASE_URL = "https://px6.link/api"
DEFAULT_TIMEOUT = 30.0
DEFAULT_PROXY_CACHE_TTL = 86400.0  # 24 hours
API_KEY_ENV_VAR = "PROXY6_API_KEY"


def _ids_param(ids: Iterable[int | str] | str | int) -> str:
    if isinstance(ids, (str, int)):
        return str(ids)
    return ",".join(str(i) for i in ids)


def _coerce_version(version: Version | int | None) -> int | None:
    if version is None:
        return None
    return int(version)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _normalize_list(raw: Any) -> list[dict[str, Any]]:
    """The API returns either a dict keyed by proxy id or a list when ``nokey`` is set."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, list):
        return list(raw)
    raise Proxy6Error(f"Unexpected list payload: {raw!r}")


class Proxy6Client:
    """Client for the Proxy6.net API.

    The API key is read in this order: the explicit ``api_key`` argument, then
    the ``PROXY6_API_KEY`` environment variable. A ``ValueError`` is raised if
    neither is set.

    Example:
        client = Proxy6Client(api_key="...")          # explicit
        client = Proxy6Client()                       # reads PROXY6_API_KEY
        info = client.get_price(count=10, period=30, version=Version.IPV6)
        print(info.price, info.price_single)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
        rate_limiter: RateLimiter | None = DEFAULT_RATE_LIMITER,
        proxy_cache_ttl: float | None = DEFAULT_PROXY_CACHE_TTL,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(API_KEY_ENV_VAR)
        if not key:
            raise ValueError(
                f"api_key is required (pass it explicitly or set the "
                f"{API_KEY_ENV_VAR} environment variable)"
            )
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None
        # ``rate_limiter=None`` disables throttling entirely. By default all
        # clients share a single module-level limiter so multiple clients in
        # the same process stay under the documented 3 req/s cap together.
        self.rate_limiter = rate_limiter
        # In-process cache of the full proxy pool, refreshed at most once per
        # ``proxy_cache_ttl`` seconds and invalidated after any state-changing
        # call. ``None`` disables caching entirely.
        self.proxy_cache_ttl = proxy_cache_ttl
        self._proxy_cache: ProxyList | None = None
        self._proxy_cache_at: float = 0.0

    def __enter__(self) -> Proxy6Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def _do_get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "yes":
            raise Proxy6APIError(
                error_id=int(data.get("error_id", 0)),
                error=str(data.get("error", "unknown")),
            )
        return data

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{self.api_key}/{method}/"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        return self._do_get(url, clean)

    def invalidate_proxy_cache(self) -> None:
        """Drop the cached proxy list. Next ``proxies()`` call will re-fetch."""
        self._proxy_cache = None
        self._proxy_cache_at = 0.0

    def _proxy_cache_fresh(self) -> bool:
        if self._proxy_cache is None or self.proxy_cache_ttl is None:
            return False
        return (time.monotonic() - self._proxy_cache_at) <= self.proxy_cache_ttl

    def proxies(self, *, refresh: bool = False) -> ProxyList:
        """Cached view of your full proxy pool (state=ALL).

        Returns the same shape as :meth:`get_proxy`, but the underlying API
        call happens at most once per ``proxy_cache_ttl`` seconds (24h by
        default). The cache is automatically dropped after any state-changing
        call (``buy``, ``prolong``, ``delete``, ``set_descr``). Pass
        ``refresh=True`` to force a re-fetch now.

        Filter the result client-side with :meth:`ProxyList.filter` and pick
        one with :meth:`ProxyList.random` — both work on the cached list
        without hitting the API again. For server-side filters (``descr``,
        pagination, ``State.EXPIRING``) call :meth:`get_proxy` directly.
        """
        if refresh or not self._proxy_cache_fresh():
            self._proxy_cache = self.get_proxy(state=State.ALL)
            self._proxy_cache_at = time.monotonic()
        return self._proxy_cache

    def select_proxy(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = True,
        descr: str | None = None,
        type: ProxyType | str | None = None,
        rng: _random.Random | None = None,
    ) -> Proxy:
        """Pick one proxy from the cached pool that matches the given filters.

        ``active`` defaults to ``True`` — expired proxies usually aren't what
        you want for routing. Pass ``active=None`` to include them. The
        other filters default to ``None`` (no filtering on that attribute).
        Raises :class:`LookupError` when nothing matches.
        """
        pool = self.proxies().filter(
            country=country,
            version=version,
            active=active,
            descr=descr,
            type=type,
        )
        if not pool:
            criteria = {
                "country": country,
                "version": version,
                "active": active,
                "descr": descr,
                "type": type,
            }
            active_criteria = {k: v for k, v in criteria.items() if v is not None}
            raise LookupError(
                f"no proxy in pool matches filters: {active_criteria}"
            )
        return pool.random(rng=rng)

    def requests_session(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = True,
        descr: str | None = None,
        type: ProxyType | str | None = None,
        rng: _random.Random | None = None,
        session: requests.Session | None = None,
    ) -> requests.Session:
        """Pick a proxy and return a ``requests.Session`` preconfigured for it.

        One-liner for the common case::

            with client.requests_session(country="us") as s:
                s.get(url)
        """
        return self.select_proxy(
            country=country,
            version=version,
            active=active,
            descr=descr,
            type=type,
            rng=rng,
        ).requests_session(session=session)

    def httpx_client(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = True,
        descr: str | None = None,
        type: ProxyType | str | None = None,
        rng: _random.Random | None = None,
        **kwargs: Any,
    ) -> "httpx.Client":
        """Pick a proxy and return an ``httpx.Client`` routed through it.

        Extra ``**kwargs`` are forwarded to ``httpx.Client``.
        """
        return self.select_proxy(
            country=country,
            version=version,
            active=active,
            descr=descr,
            type=type,
            rng=rng,
        ).httpx_client(**kwargs)

    def httpx_async_client(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = True,
        descr: str | None = None,
        type: ProxyType | str | None = None,
        rng: _random.Random | None = None,
        **kwargs: Any,
    ) -> "httpx.AsyncClient":
        """Pick a proxy and return an ``httpx.AsyncClient`` routed through it."""
        return self.select_proxy(
            country=country,
            version=version,
            active=active,
            descr=descr,
            type=type,
            rng=rng,
        ).httpx_async_client(**kwargs)

    def aiohttp_kwargs(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = True,
        descr: str | None = None,
        type: ProxyType | str | None = None,
        rng: _random.Random | None = None,
    ) -> dict[str, str]:
        """Pick a proxy and return kwargs to spread into ``aiohttp`` requests."""
        return self.select_proxy(
            country=country,
            version=version,
            active=active,
            descr=descr,
            type=type,
            rng=rng,
        ).aiohttp_kwargs()

    def account(self) -> AccountInfo:
        """Call the API with no method to fetch account info (balance/currency)."""
        url = f"{self.base_url}/{self.api_key}/"
        return AccountInfo.from_api(self._do_get(url))

    def get_price(
        self,
        count: int | None = None,
        period: int | None = None,
        version: Version | int | None = None,
    ) -> PriceQuote | PriceTable:
        """Get the cost of an order.

        If ``count``, ``period`` and ``version`` are all supplied, the API
        returns a single price (``PriceQuote``). With any of them missing it
        returns the full price table (``PriceTable``).
        """
        params = {
            "count": count,
            "period": period,
            "version": _coerce_version(version),
        }
        data = self._request("getprice", params)
        account = AccountInfo.from_api(data)
        if "data" in data:
            table: dict[Version, dict[int, float]] = {}
            for v, periods in data["data"].items():
                table[Version(int(v))] = {int(p): float(c) for p, c in periods.items()}
            return PriceTable(account=account, data=table)
        return PriceQuote(
            account=account,
            price=float(data["price"]),
            price_single=float(data["price_single"]),
            period=int(data["period"]),
            count=int(data["count"]),
        )

    def get_count(
        self, country: str, version: Version | int | None = None
    ) -> CountResult:
        """How many proxies are available to buy for a given country/version."""
        data = self._request(
            "getcount",
            {"country": country, "version": _coerce_version(version)},
        )
        return CountResult(account=AccountInfo.from_api(data), count=int(data["count"]))

    def get_country(self, version: Version | int) -> CountryList:
        """List ISO2 country codes available for the given proxy version."""
        data = self._request("getcountry", {"version": _coerce_version(version)})
        return CountryList(
            account=AccountInfo.from_api(data),
            list=list(data.get("list", [])),
        )

    def get_proxy(
        self,
        state: State | str | None = None,
        descr: str | None = None,
        page: int | None = None,
        limit: int | None = None,
    ) -> ProxyList:
        """List your proxies.

        ``nokey`` is not exposed: this client always normalizes the response,
        returning a list of :class:`Proxy` regardless of API shape.
        """
        data = self._request(
            "getproxy",
            {
                "state": str(state) if state is not None else None,
                "descr": descr,
                "page": page,
                "limit": limit,
            },
        )
        proxies = [Proxy.from_api(p) for p in _normalize_list(data.get("list"))]
        return ProxyList(
            account=AccountInfo.from_api(data),
            list_count=int(data.get("list_count", len(proxies))),
            proxies=proxies,
        )

    def set_descr(
        self,
        new: str,
        old: str | None = None,
        ids: Iterable[int | str] | str | int | None = None,
    ) -> SetDescrResult:
        """Update the technical comment on proxies.

        Either ``old`` (match-by-old-comment) or ``ids`` (match-by-id) must be
        provided.
        """
        if old is None and ids is None:
            raise ValueError("set_descr requires either 'old' or 'ids'")
        data = self._request(
            "setdescr",
            {
                "new": new,
                "old": old,
                "ids": _ids_param(ids) if ids is not None else None,
            },
        )
        self.invalidate_proxy_cache()
        return SetDescrResult(account=AccountInfo.from_api(data), count=int(data["count"]))

    def buy(
        self,
        count: int,
        period: int,
        country: str,
        version: Version | int,
        descr: str | None = None,
        auto_prolong: bool = False,
    ) -> Order:
        """Purchase proxies."""
        params: dict[str, Any] = {
            "count": count,
            "period": period,
            "country": country,
            "version": _coerce_version(version),
            "descr": descr,
        }
        if auto_prolong:
            params["auto_prolong"] = ""
        data = self._request("buy", params)
        proxies_raw = _normalize_list(data.get("list"))
        # ``buy`` results omit country/descr from each proxy, set from order.
        for p in proxies_raw:
            p.setdefault("country", data.get("country", country))
        proxies = [Proxy.from_api(p) for p in proxies_raw]
        self.invalidate_proxy_cache()
        return Order(
            account=AccountInfo.from_api(data),
            order_id=int(data["order_id"]),
            count=int(data["count"]),
            price=float(data["price"]),
            period=int(data["period"]),
            country=str(data["country"]),
            proxies=proxies,
        )

    def prolong(
        self,
        period: int,
        ids: Iterable[int | str] | str | int,
    ) -> ProlongResult:
        """Extend existing proxies for the given number of days."""
        data = self._request(
            "prolong",
            {"period": period, "ids": _ids_param(ids)},
        )
        renewals_raw = _normalize_list(data.get("list"))
        renewals = [
            Renewal(
                id=int(r["id"]),
                date_end=_parse_dt(r.get("date_end")),
                unixtime_end=(
                    int(r["unixtime_end"]) if r.get("unixtime_end") is not None else None
                ),
            )
            for r in renewals_raw
        ]
        self.invalidate_proxy_cache()
        return ProlongResult(
            account=AccountInfo.from_api(data),
            order_id=int(data["order_id"]),
            price=float(data["price"]),
            period=int(data["period"]),
            count=int(data["count"]),
            renewals=renewals,
        )

    def delete(
        self,
        ids: Iterable[int | str] | str | int | None = None,
        descr: str | None = None,
    ) -> DeleteResult:
        """Delete proxies by id list or by technical comment.

        The API exposes this as method ``delete`` (the docs index calls it
        ``deleted``, but the URL uses ``delete``).
        """
        if ids is None and descr is None:
            raise ValueError("delete requires either 'ids' or 'descr'")
        data = self._request(
            "delete",
            {
                "ids": _ids_param(ids) if ids is not None else None,
                "descr": descr,
            },
        )
        self.invalidate_proxy_cache()
        return DeleteResult(account=AccountInfo.from_api(data), count=int(data["count"]))

    def check(
        self,
        ids: int | str | None = None,
        proxy: str | None = None,
    ) -> CheckResult:
        """Check whether a proxy is currently working.

        Pass either ``ids`` (an internal proxy id) or ``proxy`` (a string of
        the form ``ip:port:user:pass``).
        """
        if ids is None and proxy is None:
            raise ValueError("check requires either 'ids' or 'proxy'")
        data = self._request("check", {"ids": ids, "proxy": proxy})
        return CheckResult(
            account=AccountInfo.from_api(data),
            proxy_id=int(data["proxy_id"]),
            proxy_status=bool(data["proxy_status"]),
        )
