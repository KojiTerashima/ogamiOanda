from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from config.app_config import AppConfig, load_app_config
from config.notifier import Notifier


@dataclass(frozen=True)
class DependencyContainer:
    app_config: AppConfig
    notifier_factory: Callable[[], Notifier]
    oanda_factory: Callable[..., Any]
    position_control_factory: Callable[..., Any]
    candle_analysis_factory: Callable[..., Any]

    @classmethod
    def default(cls, app_config: AppConfig | None = None) -> "DependencyContainer":
        import classCandleAnalysis as ca
        import classOanda
        import classPositionControl
        from config.notifier import get_notifier

        active_app_config = app_config if app_config is not None else load_app_config()
        return cls(
            app_config=active_app_config,
            notifier_factory=get_notifier,
            oanda_factory=classOanda.Oanda,
            position_control_factory=classPositionControl.position_control,
            candle_analysis_factory=ca.candleAnalysis,
        )

    def create_notifier(self) -> Notifier:
        return self.notifier_factory()

    def create_base_oanda(self, use_sub_account: bool = True):
        accounts = self.app_config.runtime_accounts
        account_id = (
            accounts.live_sub_account_id if use_sub_account else accounts.live_account_id
        )
        return self.oanda_factory(
            account_id,
            accounts.live_access_token,
            accounts.live_environment,
        )

    def create_position_control(self, *, is_live: bool, notifier: Notifier | None = None):
        return self.position_control_factory(
            is_live,
            account_config=self.app_config.runtime_accounts,
            notifier=notifier,
        )

    def create_candle_analysis(self, oanda_client, target_time):
        return self.candle_analysis_factory(oanda_client, target_time)
