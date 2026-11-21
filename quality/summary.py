from dataclasses import dataclass
from fractions import Fraction

from quality.limits import LimitStatus
from registry.units import Unit, require_same_unit, resolve_unit


@dataclass(frozen=True)
class ChannelSummary:
    channel: str
    unit: Unit
    valid_count: int
    mean: Fraction | None
    below_count: int
    above_count: int


def summarize_channels(assessments, revision, condition):
    groups = {channel: [] for channel in condition}
    for assessment in assessments:
        channel = assessment.reading.channel
        if channel not in groups:
            raise ValueError(f'reading is outside the summary condition: {channel!r}')
        groups[channel].append(assessment)
    summaries = []
    for channel, readings in groups.items():
        unit = resolve_unit(revision.for_channel(channel).unit)
        total = Fraction(0)
        below = above = 0
        for assessment in readings:
            quantity = assessment.reading.quantity
            require_same_unit(quantity.unit, unit)
            total += quantity.value
            below += assessment.status is LimitStatus.BELOW
            above += assessment.status is LimitStatus.ABOVE
        count = len(readings)
        summaries.append(ChannelSummary(channel, unit, count, total / count if count else None, below, above))
    return tuple(summaries)
