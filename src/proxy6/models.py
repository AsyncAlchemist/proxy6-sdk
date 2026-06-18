from __future__ import annotations

import ipaddress
import random as _random
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterator

from .enums import ProxyType, Version

if TYPE_CHECKING:
    import aiohttp
    import httpx
    import requests


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(slots=True)
class Proxy:
    """A proxy record returned by ``getproxy`` or ``buy``."""

    id: int
    ip: str
    host: str
    port: int
    user: str
    password: str
    type: ProxyType | str
    date: datetime | None
    date_end: datetime | None
    unixtime: int | None
    unixtime_end: int | None
    active: bool
    country: str | None = None
    descr: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Proxy:
        return cls(
            id=int(raw["id"]),
            ip=raw["ip"],
            host=raw["host"],
            port=int(raw["port"]),
            user=raw["user"],
            password=raw["pass"],
            type=raw.get("type", ""),
            country=raw.get("country"),
            date=_parse_dt(raw.get("date")),
            date_end=_parse_dt(raw.get("date_end")),
            unixtime=int(raw["unixtime"]) if raw.get("unixtime") is not None else None,
            unixtime_end=(
                int(raw["unixtime_end"]) if raw.get("unixtime_end") is not None else None
            ),
            descr=raw.get("descr"),
            active=str(raw.get("active", "0")) == "1",
        )

    def auth_url(self, scheme: str = "http") -> str:
        """Return a ``scheme://user:pass@host:port`` URL for use with HTTP libs."""
        return f"{scheme}://{self.user}:{self.password}@{self.host}:{self.port}"

    @property
    def version(self) -> Version:
        """Address family inferred from the exit IP (``ip``), not ``host``.

        Returns :class:`Version.IPV6` for IPv6 literals, :class:`Version.IPV4`
        otherwise. For proxy6's IPv6 product the SOCKS endpoint (``host``) is
        an IPv4 address so any client can reach it, but the exit (``ip``) is
        IPv6 — and the exit is what destinations (and verifiers) actually see,
        so it's what callers usually mean by "what version is this proxy?".
        Can't distinguish ``IPV4`` from ``IPV4_SHARED`` (both are IPv4
        literals); use the SKU you bought if you need that.
        """
        try:
            addr = ipaddress.ip_address(self.ip)
        except ValueError:
            return Version.IPV4
        return Version.IPV6 if isinstance(addr, ipaddress.IPv6Address) else Version.IPV4

    def as_requests_dict(self, scheme: str = "http") -> dict[str, str]:
        """Return the proxies dict shape ``requests`` expects.

        Drop-in for ``requests.get(..., proxies=proxy.as_requests_dict())``
        or ``session.proxies.update(...)``. Same URL is used for both
        ``http`` and ``https`` destinations — Proxy6 HTTP proxies tunnel
        HTTPS via CONNECT.
        """
        url = self.auth_url(scheme)
        return {"http": url, "https": url}

    def as_env(self, scheme: str = "http") -> dict[str, str]:
        """Return env-var mapping for subprocess / shell tools (curl, wget, ...).

        Includes both upper- and lower-case keys because tools disagree on
        which they read. Drop-in for
        ``subprocess.run(..., env={**os.environ, **proxy.as_env()})``.
        """
        url = self.auth_url(scheme)
        return {
            "HTTP_PROXY": url,
            "HTTPS_PROXY": url,
            "ALL_PROXY": url,
            "http_proxy": url,
            "https_proxy": url,
            "all_proxy": url,
        }

    def requests_session(
        self,
        *,
        session: "requests.Session | None" = None,
    ) -> "requests.Session":
        """Return a ``requests.Session`` preconfigured to route through this proxy.

        Pass ``session=`` to mutate an existing one (e.g. one with retry
        adapters); otherwise a fresh ``Session`` is created.
        """
        import requests

        sess = session if session is not None else requests.Session()
        sess.proxies.update(self.as_requests_dict())
        return sess

    def httpx_client(self, **kwargs: Any) -> "httpx.Client":
        """Return an ``httpx.Client`` routed through this proxy.

        Requires ``httpx`` to be installed (not a hard dependency of this
        SDK). Extra kwargs are forwarded to ``httpx.Client``.
        """
        import httpx

        return httpx.Client(proxy=self.auth_url(), **kwargs)

    def httpx_async_client(self, **kwargs: Any) -> "httpx.AsyncClient":
        """Return an ``httpx.AsyncClient`` routed through this proxy.

        Requires ``httpx`` to be installed. Extra kwargs are forwarded.
        """
        import httpx

        return httpx.AsyncClient(proxy=self.auth_url(), **kwargs)

    def aiohttp_kwargs(self) -> dict[str, str]:
        """Return kwargs to spread into ``aiohttp`` request calls.

        ``aiohttp`` has no session-level proxy setting, so the proxy must be
        passed on each request::

            async with aiohttp.ClientSession() as s:
                async with s.get(url, **proxy.aiohttp_kwargs()) as r:
                    ...
        """
        return {"proxy": self.auth_url()}


@dataclass(slots=True)
class AccountInfo:
    """Account fields present on every successful response."""

    user_id: str
    balance: float
    currency: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> AccountInfo:
        return cls(
            user_id=str(raw["user_id"]),
            balance=float(raw["balance"]),
            currency=str(raw["currency"]),
        )


@dataclass(slots=True)
class PriceQuote:
    """Result of ``getprice`` when ``count``, ``period`` and ``version`` are given."""

    account: AccountInfo
    price: float
    price_single: float
    period: int
    count: int


@dataclass(slots=True)
class PriceTable:
    """Result of ``getprice`` when called without parameters.

    ``data[version][period_days] -> price`` for a single proxy.
    """

    account: AccountInfo
    data: dict[Version, dict[int, float]]


@dataclass(slots=True)
class CountResult:
    account: AccountInfo
    count: int


@dataclass(slots=True)
class CountryList:
    account: AccountInfo
    list: list[str]


@dataclass(slots=True)
class ProxyList:
    """Result of ``getproxy``.

    Iterable / indexable / sized — ``for p in plist``, ``len(plist)`` and
    ``plist[0]`` all do what you'd expect. ``random()`` and ``filter()``
    are provided for the common "pool" workflow.
    """

    account: AccountInfo
    list_count: int
    proxies: list[Proxy] = field(default_factory=list)

    def __iter__(self) -> Iterator[Proxy]:
        return iter(self.proxies)

    def __len__(self) -> int:
        return len(self.proxies)

    def __getitem__(self, index: int) -> Proxy:
        return self.proxies[index]

    def __bool__(self) -> bool:
        return bool(self.proxies)

    def random(self, *, rng: _random.Random | None = None) -> Proxy:
        """Return one proxy chosen uniformly at random.

        Raises ``IndexError`` if the list is empty. Pass ``rng`` for
        deterministic selection in tests.
        """
        if not self.proxies:
            raise IndexError("ProxyList is empty")
        chooser = rng.choice if rng is not None else _random.choice
        return chooser(self.proxies)

    def filter(
        self,
        *,
        country: str | None = None,
        version: Version | int | None = None,
        active: bool | None = None,
        descr: str | None = None,
        type: ProxyType | str | None = None,
    ) -> ProxyList:
        """Return a new ``ProxyList`` narrowed to proxies matching every given
        attribute. ``None`` means "don't filter on this attribute".
        """
        version_int = int(version) if version is not None else None
        type_str: str | None
        if type is None:
            type_str = None
        else:
            type_str = type.value if isinstance(type, ProxyType) else str(type)

        matched: list[Proxy] = []
        for p in self.proxies:
            if country is not None and p.country != country:
                continue
            if active is not None and p.active != active:
                continue
            if descr is not None and p.descr != descr:
                continue
            if type_str is not None:
                p_type = p.type.value if isinstance(p.type, ProxyType) else str(p.type)
                if p_type != type_str:
                    continue
            if version_int is not None and int(p.version) != version_int:
                continue
            matched.append(p)
        return ProxyList(account=self.account, list_count=len(matched), proxies=matched)


@dataclass(slots=True)
class Order:
    """Result of ``buy``."""

    account: AccountInfo
    order_id: int
    count: int
    price: float
    period: int
    country: str
    proxies: list[Proxy] = field(default_factory=list)


@dataclass(slots=True)
class Renewal:
    """Per-proxy expiry update returned by ``prolong``."""

    id: int
    date_end: datetime | None
    unixtime_end: int | None


@dataclass(slots=True)
class ProlongResult:
    account: AccountInfo
    order_id: int
    price: float
    period: int
    count: int
    renewals: list[Renewal] = field(default_factory=list)


@dataclass(slots=True)
class DeleteResult:
    account: AccountInfo
    count: int


@dataclass(slots=True)
class SetDescrResult:
    account: AccountInfo
    count: int


@dataclass(slots=True)
class CheckResult:
    account: AccountInfo
    proxy_id: int
    proxy_status: bool
