from dataclasses import dataclass

from registry.units import Quantity, resolve_unit


@dataclass(frozen=True)
class ConvertedReading:
    seq: int
    channel: str
    quantity: Quantity


def convert_frame(frame, revision):
    rule = revision.for_channel(frame.channel)
    if type(frame.value) is not int:
        raise ValueError('original value must be an integer')
    value = frame.value * rule.scale + rule.offset
    return ConvertedReading(frame.seq, frame.channel, Quantity(value, resolve_unit(rule.unit)))
