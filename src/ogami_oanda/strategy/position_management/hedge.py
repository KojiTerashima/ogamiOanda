from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HedgePosition:
    position_id: str
    direction: int
    unrealized_pl: float


@dataclass(frozen=True)
class HedgeCommand:
    action: str
    position_id: str


@dataclass(frozen=True)
class HedgePolicy:
    minimum_previous_best_score: float = 0.4

    def close_commands(self, positions: list[HedgePosition]) -> tuple[HedgeCommand, ...]:
        best_pair: tuple[HedgePosition, HedgePosition] | None = None
        best_score = -float("inf")
        for long_position in positions:
            if long_position.direction != 1 or long_position.unrealized_pl <= 0:
                continue
            for short_position in positions:
                if short_position.direction != -1 or short_position.unrealized_pl <= 0:
                    continue
                score = long_position.unrealized_pl + short_position.unrealized_pl
                if score > best_score and best_score > self.minimum_previous_best_score:
                    best_score = score
                    best_pair = (long_position, short_position)
        if best_pair is None:
            return ()
        return tuple(HedgeCommand("close_trade", position.position_id) for position in best_pair)
