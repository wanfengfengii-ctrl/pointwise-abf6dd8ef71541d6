from dataclasses import dataclass

from registry.units import resolve_unit


def require_name(value, label):
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f'invalid {label}: {value!r}')
    return value


@dataclass(frozen=True)
class Channel:
    name: str
    unit: str

    def __post_init__(self):
        require_name(self.name, 'channel name')
        resolve_unit(self.unit)


def normalize_channels(channels):
    if isinstance(channels, (str, bytes)):
        raise ValueError('condition requires a collection of channel names')
    try:
        names = {require_name(name, 'channel name') for name in channels}
    except TypeError as exc:
        raise ValueError('condition requires a collection of channel names') from exc
    if not names:
        raise ValueError('empty channel condition')
    return tuple(sorted(names))


def require_channels(condition, available):
    condition = normalize_channels(condition)
    missing = set(condition).difference(available)
    if missing:
        raise ValueError(f'unknown or uncalibrated channels: {sorted(missing)!r}')
    return condition


class ChannelCatalog:
    def __init__(self, db):
        self.db = db

    def declare(self, station, channels):
        existing = self.for_station(station)
        for channel in channels:
            if not isinstance(channel, Channel):
                raise ValueError('expected a Channel declaration')
            previous = existing.get(channel.name)
            if previous is not None:
                if previous != channel:
                    raise ValueError(f'channel unit already fixed: {channel.name}')
                continue
            self.db.execute(
                'INSERT INTO channels(station, name, unit) VALUES (?, ?, ?)',
                (station, channel.name, channel.unit),
            )
            existing[channel.name] = channel

    def for_station(self, station):
        rows = self.db.execute(
            'SELECT name, unit FROM channels WHERE station = ? ORDER BY name',
            (station,),
        )
        return {row['name']: Channel(row['name'], row['unit']) for row in rows}
