"""Small-sample statistical bounds used by evidence-readiness audits."""

import math
from statistics import NormalDist
from typing import Optional, Tuple


def wilson_score_interval(
    success_count: int,
    observation_count: int,
    confidence_level: float,
) -> Optional[Tuple[float, float]]:
    """Return a two-sided Wilson interval for a binomial proportion."""
    if (
        isinstance(success_count, bool)
        or isinstance(observation_count, bool)
        or not isinstance(success_count, int)
        or not isinstance(observation_count, int)
        or observation_count < 0
        or success_count < 0
        or success_count > observation_count
    ):
        raise ValueError("binomial counts must satisfy 0 <= successes <= observations")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(float(confidence_level))
        or not 0.0 < float(confidence_level) < 1.0
    ):
        raise ValueError("confidence_level must be finite and between 0 and 1")
    if observation_count == 0:
        return None
    confidence = float(confidence_level)
    z_score = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    proportion = success_count / float(observation_count)
    z_squared = z_score * z_score
    denominator = 1.0 + z_squared / observation_count
    center = (
        proportion + z_squared / (2.0 * observation_count)
    ) / denominator
    radius = (
        z_score
        * math.sqrt(
            proportion * (1.0 - proportion) / observation_count
            + z_squared / (4.0 * observation_count * observation_count)
        )
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


def wilson_score_upper_bound(
    success_count: int,
    observation_count: int,
    confidence_level: float,
) -> Optional[float]:
    """Return the upper endpoint of a two-sided Wilson score interval."""
    interval = wilson_score_interval(
        success_count,
        observation_count,
        confidence_level,
    )
    return interval[1] if interval is not None else None
