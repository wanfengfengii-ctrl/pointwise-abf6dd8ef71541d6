from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from evidence.frames import RawFrame
from evidence.receipts import CoverageReceipt
from registry.channels import require_name
from sessions.runs import validate_position


@dataclass(frozen=True)
class Registration:
    observer: str
    first_seq: int


@dataclass(frozen=True)
class Delivery:
    observer: str
    condition: tuple[str, ...]
    position: int
    event: RawFrame | CoverageReceipt


class ObservationPortal(Protocol):
    def register(self, station: str, condition: tuple[str, ...]) -> Registration:
        ...

    def poll(self, observer: str, after: int) -> Iterable[Delivery]:
        ...

    def release(self, observer: str) -> None:
        ...


def check_registration(registration):
    if not isinstance(registration, Registration):
        raise ValueError('invalid portal registration')
    require_name(registration.observer, 'observer')
    validate_position(registration.first_seq, 'first eligible sequence')
    return registration


def check_delivery(delivery, observer, condition, previous):
    if not isinstance(delivery, Delivery):
        raise ValueError('invalid portal delivery')
    if delivery.observer != observer or delivery.condition != condition:
        raise ValueError('delivery is bound to a different observation')
    validate_position(delivery.position, 'delivery position')
    if delivery.position != previous + 1:
        raise ValueError('delivery position is out of order')
