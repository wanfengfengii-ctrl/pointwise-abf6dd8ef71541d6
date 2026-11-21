from dataclasses import dataclass
from fractions import Fraction
import json

from registry.channels import ChannelCatalog, require_name
from registry.units import require_same_unit, resolve_unit


def parse_rational(value):
    if isinstance(value, Fraction):
        return value
    if type(value) not in (int, str):
        raise ValueError('calibration requires an exact rational')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f'invalid rational: {value!r}') from exc


def rational_pair(value):
    return [value.numerator, value.denominator]


def rational_from_pair(data):
    if (type(data) is not list or len(data) != 2
            or any(type(item) is not int for item in data) or data[1] <= 0):
        raise ValueError('invalid rational pair')
    return Fraction(*data)


@dataclass(frozen=True)
class ChannelCalibration:
    channel: str
    unit: str
    scale: Fraction = Fraction(1)
    offset: Fraction = Fraction(0)
    lower: Fraction | None = None
    upper: Fraction | None = None

    def __post_init__(self):
        require_name(self.channel, 'channel name')
        resolve_unit(self.unit)
        for name in ('scale', 'offset'):
            object.__setattr__(self, name, parse_rational(getattr(self, name)))
        for name in ('lower', 'upper'):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, parse_rational(value))
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError('lower limit exceeds upper limit')

    def to_data(self):
        return {
            'channel': self.channel,
            'unit': self.unit,
            'scale': rational_pair(self.scale),
            'offset': rational_pair(self.offset),
            'lower': None if self.lower is None else rational_pair(self.lower),
            'upper': None if self.upper is None else rational_pair(self.upper),
        }

    @classmethod
    def from_data(cls, data):
        return cls(
            data['channel'], data['unit'],
            rational_from_pair(data['scale']), rational_from_pair(data['offset']),
            None if data['lower'] is None else rational_from_pair(data['lower']),
            None if data['upper'] is None else rational_from_pair(data['upper']),
        )


def _ordered_calibrations(calibrations):
    items = tuple(calibrations)
    if not items or any(not isinstance(item, ChannelCalibration) for item in items):
        raise ValueError('revision requires channel calibrations')
    if len({item.channel for item in items}) != len(items):
        raise ValueError('duplicate calibration for a channel')
    return tuple(sorted(items, key=lambda item: item.channel))


@dataclass(frozen=True)
class StationRevision:
    revision_id: int
    station: str
    name: str
    calibrations: tuple[ChannelCalibration, ...]

    def __post_init__(self):
        if type(self.revision_id) is not int or self.revision_id <= 0:
            raise ValueError('invalid revision identity')
        require_name(self.station, 'station')
        require_name(self.name, 'revision name')
        object.__setattr__(self, 'calibrations', _ordered_calibrations(self.calibrations))

    def for_channel(self, channel):
        for item in self.calibrations:
            if item.channel == channel:
                return item
        raise ValueError(f'uncalibrated channel {channel!r}')

    def to_data(self):
        return {
            'revision_id': self.revision_id,
            'station': self.station,
            'name': self.name,
            'calibrations': [item.to_data() for item in self.calibrations],
        }

    @classmethod
    def from_data(cls, data):
        return cls(
            data['revision_id'], data['station'], data['name'],
            tuple(ChannelCalibration.from_data(item) for item in data['calibrations']),
        )


class RevisionCatalog:
    def __init__(self, db):
        self.db = db

    def find_id(self, station, name):
        row = self.db.execute(
            'SELECT revision_id FROM revisions WHERE station = ? AND name = ?',
            (station, name),
        ).fetchone()
        return None if row is None else row['revision_id']

    def store(self, station, name, calibrations):
        require_name(name, 'revision name')
        items = _ordered_calibrations(calibrations)
        channels = ChannelCatalog(self.db).for_station(station)
        for item in items:
            declared = channels.get(item.channel)
            if declared is None:
                raise ValueError(f'undeclared channel {item.channel!r}')
            require_same_unit(resolve_unit(item.unit), resolve_unit(declared.unit))
        specification = json.dumps([item.to_data() for item in items], sort_keys=True)
        existing = self.find_id(station, name)
        if existing is not None:
            if self.resolve(station, existing).calibrations != items:
                raise ValueError(f'revision {name!r} already has different content')
            return existing
        cursor = self.db.execute(
            'INSERT INTO revisions(station, name, specification) VALUES (?, ?, ?)',
            (station, name, specification),
        )
        return cursor.lastrowid

    def resolve(self, station, revision_id):
        if type(revision_id) is not int or revision_id <= 0:
            raise ValueError('invalid revision identity')
        row = self.db.execute(
            'SELECT station, name, specification FROM revisions WHERE revision_id = ?',
            (str(revision_id),),
        ).fetchone()
        if row is None or row['station'] != station:
            raise ValueError(f'revision {revision_id} does not belong to station {station!r}')
        return StationRevision(
            revision_id, row['station'], row['name'],
            tuple(ChannelCalibration.from_data(item)
                  for item in json.loads(row['specification'])),
        )
