from dataclasses import dataclass, field

from evidence.frames import RawFrame
from evidence.intervals import Interval, validate_interval
from evidence.receipts import CoverageReceipt
from registry.channels import require_channels, require_name
from sessions.portal import Delivery, Registration
from sessions.runs import validate_position


STATION = 'qingwan'
SOURCE_CHANNELS = ('salinity', 'turbidity')
DAY_SOURCE = (('turbidity', 5), ('salinity', 3), ('turbidity', 6), ('salinity', 4), ('turbidity', 7))
ESTUARY_REPLAY_START = 98
ESTUARY_REPLAY = (
    ('turbidity', 6), ('salinity', 7), ('turbidity', 8),
    ('salinity', 9), ('salinity', 10), ('turbidity', 11),
)


@dataclass
class _Observer:
    registration: Registration
    condition: tuple[str, ...]
    matching: dict[int, tuple[str, int]] = field(default_factory=dict)
    sent: set[int] = field(default_factory=set)
    deliveries: list[Delivery] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryRead:
    frames: tuple[RawFrame, ...]
    receipts: tuple[CoverageReceipt, ...]
    unavailable: tuple[Interval, ...]
    pending: tuple[Interval, ...]


class ScriptedPortal:
    def __init__(self, *, first_seq=0, history_limit=8, station=STATION):
        self.station = require_name(station, 'station')
        self.next_seq = validate_position(first_seq)
        self.history_limit = validate_position(history_limit, 'history capacity')
        self.history_floor = self.next_seq
        self._history = {}
        self._observers = {}
        self._observer_count = 0
        self._online = True
        self.registrations_enabled = True

    @property
    def active_handles(self):
        return tuple(self._observers)

    def _require_online(self):
        if not self._online:
            raise OSError('portal is offline')

    def _require_station(self, station):
        if station != self.station:
            raise ValueError(f'portal does not serve {station!r}')

    def register(self, station, condition):
        self._require_online()
        self._require_station(station)
        if not self.registrations_enabled:
            raise OSError('portal rejected registration')
        condition = require_channels(condition, SOURCE_CHANNELS)
        self._observer_count += 1
        handle = f'{station}/observer-{self._observer_count}'
        registration = Registration(handle, self.next_seq)
        self._observers[handle] = _Observer(registration, condition)
        return registration

    def poll(self, observer, after):
        self._require_online()
        deliveries = self._observers[observer].deliveries
        validate_position(after, 'delivery position')
        if after > len(deliveries):
            raise ValueError('unknown acknowledgement position')
        return tuple(deliveries[after:])

    def release(self, observer):
        self._observers.pop(observer, None)

    def shutdown(self):
        self._online = False
        self._observers.clear()

    def advance(self, *samples):
        self._require_online()
        for channel, value in samples:
            if channel not in SOURCE_CHANNELS or type(value) is not int:
                raise ValueError('invalid source sample')
        for channel, value in samples:
            seq = self.next_seq
            sample = channel, value
            self._history[seq] = sample
            for observer in self._observers.values():
                if channel in observer.condition:
                    observer.matching[seq] = sample
            self.next_seq += 1
            if self.next_seq - self.history_floor > self.history_limit:
                del self._history[self.history_floor]
                self.history_floor += 1

    def append_event(self, handle, event, *, observer=None, condition=None, position=None):
        """Append a transport event, including malformed input for refusal cases."""
        self._require_online()
        state = self._observers[handle]
        delivery = Delivery(
            handle if observer is None else observer,
            state.condition if condition is None else condition,
            len(state.deliveries) + 1 if position is None else position,
            event,
        )
        state.deliveries.append(delivery)
        return delivery

    def emit_frame(self, handle, seq, *, provenance=None):
        state = self._observers[handle]
        channel, value = state.matching[seq]
        if provenance is None:
            provenance = f'{self.station}/source/{seq}'
        delivery = self.append_event(handle, RawFrame(seq, channel, value, handle, provenance))
        state.sent.add(seq)
        return delivery

    def emit_receipt(self, handle, start, end):
        state = self._observers[handle]
        interval = validate_interval(Interval(start, end), allow_empty=False)
        if start < state.registration.first_seq or end > self.next_seq:
            raise ValueError('observation cannot certify that interval')
        if any(start <= seq < end and seq not in state.sent for seq in state.matching):
            raise ValueError('matching frames still await delivery')
        receipt_id = f'{start}-{end}'
        return self.append_event(handle, CoverageReceipt(
            receipt_id, interval, state.condition, handle, f'{handle}/receipt/{receipt_id}',
        ))

    def read_history(self, station, condition, start, end):
        self._require_online()
        self._require_station(station)
        validate_interval(Interval(start, end))
        condition = require_channels(condition, SOURCE_CHANNELS)
        unavailable_end = min(end, self.history_floor)
        unavailable = (Interval(start, unavailable_end),) if start < unavailable_end else ()
        pending_start = max(start, self.next_seq)
        pending = (Interval(pending_start, end),) if pending_start < end else ()
        lo, hi = max(start, self.history_floor), min(end, self.next_seq)
        if lo >= hi:
            return HistoryRead((), (), unavailable, pending)
        observer = f'{station}/history'
        frames = tuple(
            RawFrame(seq, channel, value, observer, f'{station}/source/{seq}')
            for seq, (channel, value) in self._history.items()
            if lo <= seq < hi and channel in condition
        )
        receipt_id = f'{lo}-{hi}/{",".join(condition)}'
        receipt = CoverageReceipt(
            receipt_id, Interval(lo, hi), condition, observer, f'{observer}/receipt/{receipt_id}',
        )
        return HistoryRead(frames, (receipt,), unavailable, pending)
