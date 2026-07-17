from __future__ import annotations


def order_timeout_min_for_distance(
    distance_pips: float,
    timeframe: str,
    default_timeout_min: int,
    timeout_by_distance_pips: tuple[tuple[float, int], ...],
    timeout_cap_by_timeframe: dict[str, int],
) -> int:
    timeout_min = 60
    for border_pips, candidate_timeout_min in timeout_by_distance_pips:
        if distance_pips <= border_pips:
            timeout_min = candidate_timeout_min
            break
    return min(timeout_min, timeout_cap_by_timeframe.get(timeframe.lower(), default_timeout_min))
