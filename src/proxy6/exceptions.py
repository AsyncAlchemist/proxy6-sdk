"""Exceptions for the proxy6 SDK.

Every documented API error code has its own subclass of :class:`Proxy6APIError`,
so callers can catch specific failure modes instead of inspecting
``error_id`` by hand::

    try:
        client.buy(count=1, period=7, country="ru", version=Version.IPV6)
    except InsufficientBalanceError:
        topup()
    except NotEnoughProxiesError:
        wait_and_retry()

Instantiating ``Proxy6APIError(error_id, error)`` directly will return the
appropriate subclass via ``__new__`` dispatch, so the client only needs one
raise site.
"""

from __future__ import annotations

from typing import ClassVar


class Proxy6Error(Exception):
    """Base class for all proxy6 SDK errors."""


class Proxy6APIError(Proxy6Error):
    """Raised when the API returns ``status: "no"``.

    Subclasses are selected automatically based on ``error_id``. Catch this
    base class to handle any API error; catch a subclass for specific cases.
    """

    error_id: ClassVar[int] = 0
    _registry: ClassVar[dict[int, type[Proxy6APIError]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        code = cls.__dict__.get("error_id")
        if code:
            existing = Proxy6APIError._registry.get(code)
            if existing is not None and existing is not cls:
                raise RuntimeError(
                    f"Duplicate error_id {code} for {cls.__name__} and {existing.__name__}"
                )
            Proxy6APIError._registry[code] = cls

    def __new__(cls, error_id: int, error: str) -> Proxy6APIError:
        if cls is Proxy6APIError:
            cls = Proxy6APIError._registry.get(error_id, Proxy6APIError)
        return super().__new__(cls)

    def __init__(self, error_id: int, error: str) -> None:
        self.error_id = error_id
        self.error = error
        super().__init__(f"proxy6 API error {error_id}: {error}")


class UnknownError(Proxy6APIError):
    """30 - Unknown error."""

    error_id = 30


class AuthError(Proxy6APIError):
    """100 - Authorization error, wrong API key."""

    error_id = 100


class IPNotAllowedError(Proxy6APIError):
    """105 - API accessed from a disallowed IP, or malformed IP address."""

    error_id = 105


class MethodError(Proxy6APIError):
    """110 - Wrong method name."""

    error_id = 110


class InvalidCountError(Proxy6APIError):
    """200 - Wrong proxies quantity (zero, negative, or missing)."""

    error_id = 200


class InvalidPeriodError(Proxy6APIError):
    """210 - Wrong period (days) or missing."""

    error_id = 210


class InvalidCountryError(Proxy6APIError):
    """220 - Wrong country code (must be ISO2) or missing."""

    error_id = 220


class InvalidIdsError(Proxy6APIError):
    """230 - Wrong list of proxy ids."""

    error_id = 230


class InvalidVersionError(Proxy6APIError):
    """240 - Wrong proxy version."""

    error_id = 240


class InvalidDescriptionError(Proxy6APIError):
    """250 - Technical description error."""

    error_id = 250


class InvalidProxyTypeError(Proxy6APIError):
    """260 - Wrong proxy type (protocol) or missing."""

    error_id = 260


class InvalidPortError(Proxy6APIError):
    """270 - Wrong proxy port or missing."""

    error_id = 270


class InvalidProxyStringError(Proxy6APIError):
    """280 - Malformed ``ip:port:user:pass`` string for the check method."""

    error_id = 280


class NotEnoughProxiesError(Proxy6APIError):
    """300 - Requested more proxies than are available for sale."""

    error_id = 300


class InsufficientBalanceError(Proxy6APIError):
    """400 - Zero or low account balance."""

    error_id = 400


class NotFoundError(Proxy6APIError):
    """404 - Requested element was not found."""

    error_id = 404


class PriceCalculationError(Proxy6APIError):
    """410 - Total cost calculation error (zero or negative)."""

    error_id = 410


# Documented error codes (https://proxy6.net/en/developers#error). Kept as a
# plain mapping for callers who want the raw documentation text.
ERROR_CODES: dict[int, str] = {
    30: "Unknown error",
    100: "Authorization error, wrong key",
    105: "Incorrect IP or IP not allowed",
    110: "Wrong method",
    200: "Wrong proxies quantity",
    210: "Wrong period",
    220: "Wrong country (iso2)",
    230: "Wrong proxy id list",
    240: "Wrong version",
    250: "Wrong description",
    260: "Wrong proxy type/protocol",
    270: "Wrong port",
    280: "Wrong proxy string for check",
    300: "Not enough proxies available",
    400: "Zero or low balance",
    404: "Element not found",
    410: "Cost calculation error",
}
