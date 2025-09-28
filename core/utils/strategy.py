from __future__ import annotations

from typing import Dict, Tuple


def compute_direction_and_confidence(
    scores: Dict[str, float],
    weights: Dict[str, float] | None = None,
) -> Tuple[str, float]:
    """Compute direction and confidence from scores using the new policy.

    Direction is derived from polarity_strength:
      - > 0 => buy
      - < 0 => sell
      - = 0 => hold

    confidence = |polarity_strength| * (
        0.35 * impact_size +
        0.25 * time_proximity +
        0.15 * clarity +
        0.15 * volatility_sensitivity +
        0.10 * duration
    )

    Weights can be overridden via the `weights` argument, with the same keys
    as the score components.
    """
    if not scores:
        return "hold", 0.0

    impact_size = float(scores.get("impact_size") or 0.0)
    time_proximity = float(scores.get("time_proximity") or 0.0)
    clarity = float(scores.get("clarity") or 0.0)
    volatility_sensitivity = float(scores.get("volatility_sensitivity") or 0.0)
    duration = float(scores.get("duration") or 0.0)
    polarity_strength = float(scores.get("polarity_strength") or 0.0)

    # Direction from polarity_strength
    if polarity_strength > 0:
        direction = "buy"
    elif polarity_strength < 0:
        direction = "sell"
    else:
        direction = "hold"

    w = weights or {
        "impact_size": 0.35,
        "time_proximity": 0.25,
        "clarity": 0.15,
        "volatility_sensitivity": 0.15,
        "duration": 0.10,
    }

    base = (
        w.get("impact_size", 0.35) * impact_size
        + w.get("time_proximity", 0.25) * time_proximity
        + w.get("clarity", 0.15) * clarity
        + w.get("volatility_sensitivity", 0.15) * volatility_sensitivity
        + w.get("duration", 0.10) * duration
    )

    confidence = abs(polarity_strength) * base

    # Clamp to [0, 1]
    if confidence < 0.0:
        confidence = 0.0
    elif confidence > 1.0:
        confidence = 1.0

    return direction, confidence


__all__ = ["compute_direction_and_confidence"]


