from dataclasses import dataclass

from quality.conversion import convert_frame
from quality.limits import LimitAssessment, assess_limits
from quality.summary import ChannelSummary, summarize_channels
from registry.channels import require_channels


@dataclass(frozen=True)
class QualityReport:
    readings: tuple[LimitAssessment, ...]
    summaries: tuple[ChannelSummary, ...]


def evaluate_shift(frames, revision, condition):
    condition = require_channels(condition, (item.channel for item in revision.calibrations))
    readings = []
    for frame in sorted(frames, key=lambda item: item.seq):
        if frame.channel not in condition:
            raise ValueError(f'frame is outside the fixed quality condition: {frame.channel!r}')
        reading = convert_frame(frame, revision)
        readings.append(assess_limits(reading, revision.for_channel(frame.channel)))
    return QualityReport(tuple(readings), summarize_channels(readings, revision, condition))
