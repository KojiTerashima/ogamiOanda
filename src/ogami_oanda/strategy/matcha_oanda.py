"""Pure, broker-neutral port of the Matcha USD/JPY strategy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Mapping

from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType
from ogami_oanda.domain.positions.models import TradeState
from ogami_oanda.strategy.contracts import (
    JSONState,
    JSONValue,
    StrategyCommand,
    StrategyCommandAction,
    StrategyDecision,
    StrategyInput,
)

STRATEGY_API_VERSION = 1
MATCHA_SOURCE = "matcha_oanda"


@dataclass(frozen=True)
class MatchaConfig:
    pair: str
    lot_size: int
    max_lot_size: int
    max_pos: int
    sfd_check: bool
    auto_lot: bool
    leverage: float
    cancel: bool
    cancel_len: int
    siguma_1: float
    siguma_2: float
    siguma_3: float
    siguma_4: float
    past_price_len: int
    std_len: int
    dp: float
    ctp: int
    breakout: bool
    stop_latency_ms: float
    max_latency_ms: float
    tp_sl_amount_mode: bool
    tp_sl_close_intent_suppress: bool
    take_profit_amount: float
    stop_loss_amount: float
    take_profit_distance: float
    stop_loss_distance: float
    timescale: int
    minutes_to_expire: int
    close_position: bool

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "MatchaConfig":
        supported_route = {
            "pair": "USD_JPY",
            "AutoLot": False,
            "Cancel": False,
            "MaxPos": 1,
            "tp_sl_amount_mode": True,
            "tp_sl_close_intent_suppress": True,
            "close_position": False,
            "timescale": 60,
        }
        for key, supported in supported_route.items():
            value = _required(raw, key)
            if type(value) is not type(supported) or value != supported:
                raise ValueError(f"{key}={value!r} is unsupported; only {key}={supported!r} is supported")

        return cls(
            pair="USD_JPY",
            lot_size=_positive_int(raw, "LotSize"),
            max_lot_size=_positive_int(raw, "MaxLotSize"),
            max_pos=1,
            sfd_check=_boolean(raw, "sfdCheck"),
            auto_lot=False,
            leverage=_finite_float(raw, "Leverage"),
            cancel=False,
            cancel_len=_positive_int(raw, "Cancel_len"),
            siguma_1=_nonnegative_float(raw, "siguma_1"),
            siguma_2=_nonnegative_float(raw, "siguma_2"),
            siguma_3=_nonnegative_float(raw, "siguma_3"),
            siguma_4=_nonnegative_float(raw, "siguma_4"),
            past_price_len=_nonnegative_int(raw, "pastPrice_len"),
            std_len=_positive_int(raw, "std_len"),
            dp=_nonnegative_float(raw, "dp"),
            ctp=_integer(raw, "CTP"),
            breakout=_boolean(raw, "BreakOut"),
            stop_latency_ms=_nonnegative_float(raw, "stop_latency"),
            max_latency_ms=_nonnegative_float(raw, "max_latency"),
            tp_sl_amount_mode=True,
            tp_sl_close_intent_suppress=True,
            take_profit_amount=_positive_float(raw, "take_profit_amount"),
            stop_loss_amount=_positive_float(raw, "stop_loss_amount"),
            take_profit_distance=_nonnegative_float(raw, "take_profit_distance"),
            stop_loss_distance=_nonnegative_float(raw, "stop_loss_distance"),
            timescale=60,
            minutes_to_expire=_positive_int(raw, "minutes_to_expire"),
            close_position=False,
        )


class MatchaStrategy:
    def __init__(self, config: MatchaConfig):
        self.config = config
        self.pair = config.pair
        self._last_candle: str | None = None
        self._previous_net_units = 0
        self._cooldown_minute: str | None = None
        self._latency_samples_ms: list[float] = []

    def decide(self, input: StrategyInput) -> StrategyDecision:
        prices = _price_levels(input.candles, input.quote.mid, self.config)
        candle_id = _newest_candle_id(input.candles)
        is_new_candle = candle_id is not None and candle_id != self._last_candle
        if candle_id is not None:
            self._last_candle = candle_id
        diagnostics: dict[str, JSONValue] = {
            "price_levels": prices,
            "candle_order": "input_newest_first_math_oldest_first",
            "sfd_check": self.config.sfd_check,
            "candle_id": candle_id,
        }
        net_units = self._net_units(input)
        diagnostics["net_units"] = net_units
        latency_ms = _quote_age_ms(input.evaluation_time, input.quote.source_time)
        diagnostics["quote_latency_ms"] = latency_ms
        if latency_ms is not None:
            self._latency_samples_ms.append(round(latency_ms, 6))
            del self._latency_samples_ms[:-100]

        if self.config.max_latency_ms > 0 and latency_ms is not None and latency_ms > self.config.max_latency_ms:
            return self._finish(
                net_units,
                commands=(
                    StrategyCommand(
                        StrategyCommandAction.CANCEL_PENDING,
                        MATCHA_SOURCE,
                        "maximum_quote_latency",
                    ),
                    StrategyCommand(
                        StrategyCommandAction.CLOSE_ALL,
                        MATCHA_SOURCE,
                        "maximum_quote_latency",
                    ),
                ),
                diagnostics=diagnostics,
            )

        if self._previous_net_units != 0 and net_units == 0:
            return self._finish(
                net_units,
                commands=(
                    StrategyCommand(
                        StrategyCommandAction.CANCEL_PENDING,
                        MATCHA_SOURCE,
                        "flatten_cleanup",
                    ),
                ),
                diagnostics=diagnostics,
            )

        self._touch_cooldown(input.evaluation_time)
        entry_lot = self.entry_lot()
        position_size = abs(net_units)
        maximum = self.max_pos_size(entry_lot)
        if position_size > maximum:
            correction = self.correction_units(position_size, maximum)
            commands = ()
            if correction > 0:
                commands = (
                    StrategyCommand(
                        StrategyCommandAction.REDUCE_EXPOSURE,
                        MATCHA_SOURCE,
                        "maximum_exposure",
                        correction,
                    ),
                )
            return self._finish(net_units, commands=commands, diagnostics=diagnostics)

        quote_is_usable = (
            input.quote.pair == self.pair
            and input.quote.tradeable is True
            and latency_ms is not None
            and not (
                self.config.stop_latency_ms > 0
                and latency_ms > self.config.stop_latency_ms
            )
        )
        if not quote_is_usable:
            diagnostics["entry_suppressed"] = "quote_freshness_or_tradeability"
            return self._finish(net_units, diagnostics=diagnostics)
        if not all(isinstance(price, (int, float)) and price > 0 for price in prices[:6]):
            diagnostics["entry_suppressed"] = "price_calculation_unready"
            return self._finish(net_units, diagnostics=diagnostics)

        signal = int(prices[6])
        if signal in (1, 2):
            decision = self._breakout_decision(net_units, signal, entry_lot, diagnostics)
            self._previous_net_units = net_units
            return decision

        if not is_new_candle:
            diagnostics["entry_suppressed"] = "duplicate_completed_candle"
            return self._finish(net_units, diagnostics=diagnostics)

        intents: tuple[OrderIntent, ...]
        if net_units == 0:
            intents = (
                self._intent(Direction.BUY, OrderType.LIMIT, float(prices[0]), entry_lot, "normal_buy", signal),
                self._intent(Direction.SELL, OrderType.LIMIT, float(prices[1]), entry_lot, "normal_sell", signal),
            )
        elif net_units > 0:
            units = self.entry_lot_2(position_size, entry_lot)
            intents = (
                self._intent(Direction.BUY, OrderType.LIMIT, float(prices[0]), units, "normal_long_add", signal),
            ) if units > 0 else ()
        else:
            units = self.entry_lot_2(position_size, entry_lot)
            intents = (
                self._intent(Direction.SELL, OrderType.LIMIT, float(prices[1]), units, "normal_short_add", signal),
            ) if units > 0 else ()
        return self._finish(net_units, intents=intents, diagnostics=diagnostics)

    def _breakout_decision(
        self,
        net_units: int,
        signal: int,
        entry_lot: int,
        diagnostics: Mapping[str, JSONValue],
    ) -> StrategyDecision:
        entry_direction = Direction.BUY if signal == 1 else Direction.SELL
        if net_units == 0:
            return StrategyDecision(
                intents=(self._intent(entry_direction, OrderType.MARKET, 0, entry_lot, "breakout_entry", signal),),
                diagnostics=diagnostics,
            )

        position_direction = Direction.BUY if net_units > 0 else Direction.SELL
        position_size = abs(net_units)
        if position_direction is entry_direction:
            units = self.entry_lot_2(position_size, entry_lot)
            intents = (
                self._intent(entry_direction, OrderType.MARKET, 0, units, "breakout_add", signal),
            ) if units > 0 else ()
            return StrategyDecision(intents=intents, diagnostics=diagnostics)

        desired = self.close_lot(position_size) + entry_lot
        reduction = min(desired, position_size)
        reverse_units = max(0, desired - position_size)
        commands = (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                MATCHA_SOURCE,
                "breakout_reverse",
                reduction,
            ),
        ) if reduction > 0 else ()
        intents = (
            self._intent(entry_direction, OrderType.MARKET, 0, reverse_units, "breakout_reverse", signal),
        ) if reverse_units > 0 else ()
        return StrategyDecision(commands=commands, intents=intents, diagnostics=diagnostics)

    def _intent(
        self,
        direction: Direction,
        order_type: OrderType,
        target: float,
        units: int,
        branch: str,
        signal: int,
    ) -> OrderIntent:
        return OrderIntent(
            pair=self.pair,
            direction=direction,
            order_type=order_type,
            target=target,
            target_is_price=order_type is not OrderType.MARKET,
            take_profit=self.config.take_profit_amount / units,
            take_profit_is_price=False,
            stop_loss=self.config.stop_loss_amount / units,
            stop_loss_is_price=False,
            units=units,
            name=f"{MATCHA_SOURCE}_{branch}",
            priority=100,
            order_timeout_min=self.config.minutes_to_expire,
            metadata={"source": MATCHA_SOURCE, "matcha_branch": branch, "matcha_signal": signal},
        )

    def _finish(
        self,
        net_units: int,
        *,
        commands: tuple[StrategyCommand, ...] = (),
        intents: tuple[OrderIntent, ...] = (),
        diagnostics: Mapping[str, JSONValue],
    ) -> StrategyDecision:
        self._previous_net_units = net_units
        return StrategyDecision(commands=commands, intents=intents, diagnostics=diagnostics)

    def _net_units(self, input: StrategyInput) -> int:
        total = 0
        for position in input.positions:
            if position.pair != self.pair or position.source != MATCHA_SOURCE:
                continue
            if position.trade_state is not TradeState.OPEN or position.direction not in (-1, 1):
                continue
            total += int(position.direction) * abs(int(position.units))
        return total

    def _touch_cooldown(self, evaluation_time: datetime | None) -> None:
        if evaluation_time is None or evaluation_time.tzinfo is None:
            return
        minute = evaluation_time.replace(second=0, microsecond=0).isoformat()
        if minute != self._cooldown_minute:
            self._cooldown_minute = minute

    def entry_lot(self) -> int:
        return min(self.config.lot_size, self.config.max_lot_size)

    def entry_lot_2(self, position_units: int, entry_lot: int | None = None) -> int:
        entry = self.entry_lot() if entry_lot is None else entry_lot
        position = abs(position_units)
        if entry * self.config.cancel_len - 1 < position:
            return 0
        return max(0, math.floor(entry - position / self.config.cancel_len))

    def close_lot(self, position_units: int) -> int:
        return max(0, math.floor(abs(position_units) / self.config.cancel_len))

    def max_pos_size(self, entry_lot: int | None = None) -> int:
        entry = self.entry_lot() if entry_lot is None else entry_lot
        return entry * self.config.cancel_len * self.config.max_pos

    @staticmethod
    def correction_units(position_units: int, maximum_units: int) -> int:
        return max(0, math.floor((abs(position_units) - maximum_units) / 2))

    def dump_state(self) -> JSONState:
        return {
            "version": 1,
            "source": MATCHA_SOURCE,
            "last_candle": self._last_candle,
            "previous_net_units": self._previous_net_units,
            "cooldown_minute": self._cooldown_minute,
            "latency_samples_ms": list(self._latency_samples_ms),
        }

    def load_state(self, state: Mapping[str, JSONValue]) -> None:
        if not isinstance(state, Mapping):
            raise ValueError("matcha state must be a mapping")
        if not state:
            self._last_candle = None
            self._previous_net_units = 0
            self._cooldown_minute = None
            self._latency_samples_ms = []
            return

        required = {
            "version",
            "source",
            "last_candle",
            "previous_net_units",
            "cooldown_minute",
            "latency_samples_ms",
        }
        missing = required.difference(state)
        if missing:
            raise ValueError(f"matcha state is missing fields: {', '.join(sorted(missing))}")
        if type(state["version"]) is not int or state["version"] != 1:
            raise ValueError("matcha state version must be 1")
        if state["source"] != MATCHA_SOURCE:
            raise ValueError(f"matcha state source must be {MATCHA_SOURCE!r}")

        last_candle = state["last_candle"]
        if last_candle is not None and (not isinstance(last_candle, str) or not last_candle):
            raise ValueError("matcha state last_candle must be a non-empty string or null")
        previous_net_units = state["previous_net_units"]
        if type(previous_net_units) is not int:
            raise ValueError("matcha state previous_net_units must be an integer")
        cooldown_minute = state["cooldown_minute"]
        if cooldown_minute is not None:
            if not isinstance(cooldown_minute, str):
                raise ValueError("matcha state cooldown_minute must be an aware ISO datetime or null")
            try:
                parsed_cooldown = datetime.fromisoformat(cooldown_minute)
            except ValueError as exc:
                raise ValueError("matcha state cooldown_minute must be an aware ISO datetime or null") from exc
            if parsed_cooldown.tzinfo is None:
                raise ValueError("matcha state cooldown_minute must be an aware ISO datetime or null")

        samples = state["latency_samples_ms"]
        if not isinstance(samples, list) or len(samples) > 100:
            raise ValueError("matcha state latency_samples_ms must be a list with at most 100 values")
        validated_samples: list[float] = []
        for sample in samples:
            if isinstance(sample, bool) or not isinstance(sample, (int, float)):
                raise ValueError("matcha state latency samples must be finite non-negative numbers")
            converted = float(sample)
            if not math.isfinite(converted) or converted < 0:
                raise ValueError("matcha state latency samples must be finite non-negative numbers")
            validated_samples.append(converted)

        self._last_candle = last_candle
        self._previous_net_units = previous_net_units
        self._cooldown_minute = cooldown_minute
        self._latency_samples_ms = validated_samples


def create_strategy(config: Mapping[str, object]) -> MatchaStrategy:
    """Validate the supported route before constructing Matcha."""

    return MatchaStrategy(MatchaConfig.from_mapping(config))


def _required(raw: Mapping[str, object], key: str) -> object:
    if key not in raw:
        raise ValueError(f"missing required Matcha setting: {key}")
    return raw[key]


def _boolean(raw: Mapping[str, object], key: str) -> bool:
    value = _required(raw, key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return value


def _integer(raw: Mapping[str, object], key: str) -> int:
    value = _required(raw, key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    return value


def _positive_int(raw: Mapping[str, object], key: str) -> int:
    value = _integer(raw, key)
    if value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _nonnegative_int(raw: Mapping[str, object], key: str) -> int:
    value = _integer(raw, key)
    if value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _finite_float(raw: Mapping[str, object], key: str) -> float:
    value = _required(raw, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a finite number")
    converted = float(value)
    if converted != converted or converted in (float("inf"), float("-inf")):
        raise ValueError(f"{key} must be a finite number")
    return converted


def _nonnegative_float(raw: Mapping[str, object], key: str) -> float:
    value = _finite_float(raw, key)
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _positive_float(raw: Mapping[str, object], key: str) -> float:
    value = _finite_float(raw, key)
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _price_levels(candles: object | None, ltp: float, config: MatchaConfig) -> list[JSONValue]:
    records = _candle_records(candles)
    newest_first: list[tuple[float, float, float, float]] = []
    for record in records:
        try:
            values = tuple(float(record[key]) for key in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) and value > 0 for value in values):
            newest_first.append(values)

    oldest_first = list(reversed(newest_first))
    if len(oldest_first) < config.std_len + 3 or not math.isfinite(ltp) or ltp <= 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0]

    opens = [row[0] for row in oldest_first]
    highs = [row[1] for row in oldest_first]
    lows = [row[2] for row in oldest_first]
    closes = [row[3] for row in oldest_first]
    o1 = opens[-1]
    h1 = max(highs[-1], ltp)
    l1 = min(lows[-1], ltp)
    c1 = ltp

    if config.ctp == 1:
        center = (max(h1, ltp) + min(l1, ltp) + ltp + ltp) / 4
    elif config.ctp == 2:
        center = (max(h1, ltp) + min(l1, ltp) + ltp) / 3
    elif config.ctp == 3:
        center = (highs[-1] + lows[-1] + o1 + o1) / 4
    else:
        center = ltp

    std = _population_std(closes[-config.std_len :]) + c1 * config.dp
    depth1 = std * config.siguma_1
    depth2 = std * config.siguma_1 * config.siguma_2
    depth3 = std * config.siguma_1 * config.siguma_3
    prices: list[JSONValue] = [
        _normalize_price(center - depth1),
        _normalize_price(center + depth1),
        _normalize_price(center - depth2),
        _normalize_price(center + depth2),
        _normalize_price(center - depth3),
        _normalize_price(center + depth3),
    ]

    signal = 0
    past = config.past_price_len
    if config.breakout and past > 0 and len(closes) > config.std_len + past + 1:
        scope = min(len(closes), config.std_len + past)
        prior = closes[-scope:-past]
        std2 = _population_std(prior) + closes[-past] * config.dp
        base = (closes[-past] + closes[-(past + 1)]) / 2
        high = _normalize_price(base + std2 * config.siguma_4)
        low = _normalize_price(base - std2 * config.siguma_4)
        if c1 > high:
            signal = 1
        elif c1 < low:
            signal = 2
    prices.append(signal)
    return prices


def _candle_records(candles: object | None) -> list[Mapping[str, object]]:
    if candles is None:
        return []
    to_dict = getattr(candles, "to_dict", None)
    if callable(to_dict):
        records = to_dict(orient="records")
    elif isinstance(candles, Iterable) and not isinstance(candles, (str, bytes, Mapping)):
        records = list(candles)
    else:
        return []
    return [record for record in records if isinstance(record, Mapping)]


def _newest_candle_id(candles: object | None) -> str | None:
    records = _candle_records(candles)
    if not records:
        return None
    raw = records[0].get("time", records[0].get("time_jp"))
    if raw is None:
        return None
    isoformat = getattr(raw, "isoformat", None)
    value = isoformat() if callable(isoformat) else str(raw)
    return value if value else None


def _population_std(values: list[float]) -> float:
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))


def _normalize_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _quote_age_ms(evaluation_time: datetime | None, source_time: datetime | None) -> float | None:
    if evaluation_time is None or source_time is None:
        return None
    if evaluation_time.tzinfo is None or source_time.tzinfo is None:
        return None
    return max(0.0, (evaluation_time - source_time).total_seconds() * 1000)
