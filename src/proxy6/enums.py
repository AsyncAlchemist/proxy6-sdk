from __future__ import annotations

from enum import IntEnum, StrEnum


class Version(IntEnum):
    IPV4_SHARED = 3
    IPV4 = 4
    MTPROTO = 5
    IPV6 = 6


class ProxyType(StrEnum):
    HTTP = "http"
    SOCKS = "socks"


class State(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    EXPIRING = "expiring"
    ALL = "all"
