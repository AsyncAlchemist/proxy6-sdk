from __future__ import annotations


class Proxy6Error(Exception):
    """Base class for all proxy6 SDK errors."""


class Proxy6APIError(Proxy6Error):
    """Raised when the API returns ``status: "no"``.

    Attributes mirror the documented error envelope:
    ``{"status":"no","error_id":<int>,"error":"<key>"}``.
    """

    def __init__(self, error_id: int, error: str) -> None:
        self.error_id = error_id
        self.error = error
        super().__init__(f"proxy6 API error {error_id}: {error}")


# Documented error codes (https://proxy6.net/en/developers#error)
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
