from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.domain.market.currency_pair import CurrencyPair


@dataclass(frozen=True)
class PositionSizingPolicy:
    """Legacy-compatible risk sizing with no configuration or broker dependency."""

    risk_yen: float
    yen_per_pip_per_lot: float = 1000.0
    units_per_lot: int = 10000

    def units_for(
        self,
        pair: CurrencyPair,
        stop_loss_pips: float,
        multiplier: float = 1.0,
    ) -> int:
        if self.risk_yen <= 0:
            raise ValueError("risk_yen must be positive")
        if stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be positive")
        if multiplier <= 0:
            raise ValueError("units multiplier must be positive")

        lot = self.risk_yen / (stop_loss_pips * self.yen_per_pip_per_lot)
        raw_units = int(lot * self.units_per_lot)
        legacy_long_rounded = int(5 * round(raw_units / 5))
        units = int(legacy_long_rounded * multiplier)
        if units <= 0:
            raise ValueError(
                f"risk sizing produced no tradable units for {pair.name}: "
                f"risk_yen={self.risk_yen}, stop_loss_pips={stop_loss_pips}, multiplier={multiplier}"
            )
        return units
