from __future__ import annotations

from typing import Any, Protocol

from oandapyV20 import API

from ogami_oanda.application.errors import TransientExternalServiceError



class AccountConfiguration(Protocol):
    account_id: str
    access_token: str
    environment: str


class OandaClient:
    def __init__(self, account: AccountConfiguration, api: Any | None = None) -> None:
        self.account = account
        self.api = api or API(access_token=account.access_token, environment=account.environment)

    @property
    def account_id(self) -> str:
        return self.account.account_id

    def request(self, endpoint: Any) -> dict[str, object]:
        try:
            return self.api.request(endpoint)
        except Exception as error:
            if _is_transient(error):
                raise TransientExternalServiceError(
                    "oanda",
                    str(getattr(error, "msg", None) or error),
                    retry_after_seconds=_retry_after(error),
                ) from error
            raise


def _status_code(error: Exception) -> int | None:
    raw_code = getattr(error, "code", None)
    try:
        return int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        return None


def _is_transient(error: Exception) -> bool:
    code = _status_code(error)
    if code in {408, 425, 429} or (code is not None and code >= 500):
        return True
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_name = error.__class__.__name__.lower()
    return "timeout" in error_name or "connection" in error_name or "proxy" in error_name


def _retry_after(error: Exception) -> float | None:
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is None:
        return None
    value = headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
