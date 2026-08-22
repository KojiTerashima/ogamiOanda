from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ogami_oanda.domain.market.currency_pair import currency_pair


@dataclass
class PortfolioAnalytics:
    """Legacy-compatible, process-lifetime close-result aggregation.

    The initial values and the asymmetric minimum updates intentionally mirror
    ``classPosition.order_information``.  In particular, the cumulative-yen
    and cumulative-price minima remain infinity after an initial winning
    trade; that is observable legacy behaviour, not a normalization target.
    """

    total_yen: float = 0.0
    total_yen_max: float = 0.0
    total_yen_min: float = float("inf")
    total_price_diff: float = 0.0
    total_price_diff_max: float = 0.0
    total_price_diff_min: float = float("inf")
    total_pips: float = 0.0
    total_pips_max: float = 0.0
    total_pips_min: float = float("inf")
    plus_yen_position_num: int = 0
    minus_yen_position_num: int = 0
    lc_change_num: int = 0
    before_latest_price_diff: float = 0.0
    before_latest_pl_pips: float = 0.0
    before_latest_plu: float = 0.0
    before_latest_name: str = ""
    history_plus_minus: list[float] = field(default_factory=lambda: [0.0])
    history_names: list[str] = field(default_factory=lambda: ["0"])
    history_name_plus_minus: list[dict[str, object]] = field(default_factory=list)
    result_dic_arr: list[dict[str, object]] = field(default_factory=list)
    result_row: int = 7

    def apply(
        self,
        record: Mapping[str, object],
        price_diff: float,
        *,
        lc_change_count: int = 0,
    ) -> None:
        realized = float(record["res"])
        pips = float(record["pl_per_units"])
        pair = currency_pair(str(record["pair"]))

        self.total_yen = round(self.total_yen + realized, 2)
        if self.total_yen > self.total_yen_max:
            self.total_yen_max = self.total_yen
        elif self.total_yen < self.total_yen_min:
            self.total_yen_min = self.total_yen

        self.total_price_diff = pair.round_price(
            self.total_price_diff + price_diff,
        )
        if self.total_price_diff > self.total_price_diff_max:
            self.total_price_diff_max = self.total_price_diff
        elif self.total_price_diff < self.total_price_diff_min:
            self.total_price_diff_min = self.total_price_diff

        self.total_pips = round(self.total_pips + pips, 2)
        if self.total_pips > self.total_pips_max:
            self.total_pips_max = self.total_pips
        if self.total_pips < self.total_pips_min:
            self.total_pips_min = self.total_pips

        if realized < 0:
            self.minus_yen_position_num += 1
        else:
            self.plus_yen_position_num += 1
        self.lc_change_num += int(lc_change_count)

        name = str(record["name"])
        self.before_latest_price_diff = price_diff
        self.before_latest_pl_pips = pips
        self.before_latest_plu = pips
        self.before_latest_name = name
        self.history_plus_minus.append(pips)
        self.history_names.append(name)
        self.history_name_plus_minus.append(
            {
                "name": record["name_only"],
                "price_diff": price_diff,
                "pl_pips": pips,
            }
        )
        self.result_dic_arr.append(dict(record))

    @property
    def result_summary(self) -> dict[str, object]:
        """Return the cumulative values shown by the legacy close report."""

        return {
            "total_yen": self.total_yen,
            "total_yen_max": self.total_yen_max,
            "total_yen_min": self.total_yen_min,
            "total_price_diff": self.total_price_diff,
            "total_price_diff_max": self.total_price_diff_max,
            "total_price_diff_min": self.total_price_diff_min,
            "total_pips": self.total_pips,
            "total_pips_max": self.total_pips_max,
            "total_pips_min": self.total_pips_min,
            "plus_yen_position_num": self.plus_yen_position_num,
            "minus_yen_position_num": self.minus_yen_position_num,
            "lc_change_num": self.lc_change_num,
        }

    def latest_summary(self, limit: int | None = None) -> dict[str, object]:
        """Return the last legacy result rows and their integer-yen sum."""

        row_count = self.result_row if limit is None else limit
        rows = tuple(self.result_dic_arr[-row_count:])
        return {
            "rows": rows,
            "res_sum": sum(int(float(row["res"])) for row in rows),
        }

    def pivot_summary(
        self,
        limit: int | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Reproduce the legacy seven-row ``name_only`` group summary."""

        rows = self.latest_summary(limit)["rows"]
        grouped: dict[str, dict[str, object]] = {}
        for row in rows:
            name = str(row["name_only"])
            result = float(row["res"])
            item = grouped.setdefault(
                name,
                {
                    "name_only": name,
                    "res_sum": 0.0,
                    "positive_count": 0,
                    "negative_count": 0,
                },
            )
            item["res_sum"] = float(item["res_sum"]) + result
            if result > 0:
                item["positive_count"] = int(item["positive_count"]) + 1
            elif result < 0:
                item["negative_count"] = int(item["negative_count"]) + 1
        return tuple(
            {
                **grouped[name],
                "res_sum": int(float(grouped[name]["res_sum"])),
            }
            for name in sorted(grouped)
        )


_LATEST_BY_PAIR: dict[str, PortfolioAnalytics] = {}


def publish_portfolio_analytics(pair: str, analytics: PortfolioAnalytics) -> None:
    """Expose the src-owned aggregate to the root compatibility projection."""

    _LATEST_BY_PAIR[pair] = analytics


def latest_portfolio_analytics(pair: str) -> PortfolioAnalytics | None:
    return _LATEST_BY_PAIR.get(pair)
