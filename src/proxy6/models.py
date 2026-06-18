from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enums import ProxyType, Version


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
    """Result of ``getproxy``."""

    account: AccountInfo
    list_count: int
    proxies: list[Proxy] = field(default_factory=list)


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
