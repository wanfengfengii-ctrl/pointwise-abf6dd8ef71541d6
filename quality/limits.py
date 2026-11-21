from dataclasses import dataclass
from enum import Enum

from quality.conversion import ConvertedReading
from registry.units import require_same_unit, resolve_unit


class LimitStatus(str, Enum):
    WITHIN = 'within'
    BELOW = 'below'
    ABOVE = 'above'
    UNCONFIGURED = 'unconfigured'


@dataclass(frozen=True)
class LimitAssessment:
    reading: ConvertedReading
    status: LimitStatus


def assess_limits(reading, rule):
    if reading.channel != rule.channel:
        raise ValueError('limit rule is for a different channel')
    require_same_unit(reading.quantity.unit, resolve_unit(rule.unit))
    value = reading.quantity.value
    if rule.lower is None and rule.upper is None:
        status = LimitStatus.UNCONFIGURED
    elif rule.lower is not None and value < rule.lower:
        status = LimitStatus.BELOW
    elif rule.upper is not None and value > rule.upper:
        status = LimitStatus.ABOVE
    else:
        status = LimitStatus.WITHIN
    return LimitAssessment(reading, status)
