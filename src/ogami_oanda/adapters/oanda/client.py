from __future__ import annotations

from typing import Any, Protocol

from oandapyV20 import API



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
        return self.api.request(endpoint)
