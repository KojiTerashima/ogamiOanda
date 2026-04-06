from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeAccountConfig:
    practice_account_id: str
    practice_access_token: str
    practice_environment: str
    live_account_id: str
    live_sub_account_id: str
    live_access_token: str
    live_environment: str
    history_folder_path: str = ""

    @classmethod
    def from_legacy_values(
        cls,
        *,
        practice_account_id: str,
        practice_access_token: str,
        practice_environment: str,
        live_account_id: str,
        live_sub_account_id: str,
        live_access_token: str,
        live_environment: str,
        history_folder_path: str = "",
    ) -> "RuntimeAccountConfig":
        return cls(
            practice_account_id=practice_account_id,
            practice_access_token=practice_access_token,
            practice_environment=practice_environment,
            live_account_id=live_account_id,
            live_sub_account_id=live_sub_account_id,
            live_access_token=live_access_token,
            live_environment=live_environment,
            history_folder_path=history_folder_path,
        )
