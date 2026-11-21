from dataclasses import dataclass
from dataclasses import replace

from registry.calibrations import ChannelCalibration
from registry.channels import Channel


@dataclass(frozen=True)
class StationManifest:
    station: str
    channels: tuple[Channel, ...]
    revision_name: str
    calibrations: tuple[ChannelCalibration, ...]

    def for_declared_channels(self, declared):
        # Default coefficients are the identity in each declared unit.
        units = {name: channel.unit for name, channel in declared.items()}
        return tuple(replace(item, unit=units[item.channel]) for item in self.calibrations)


def default_manifest():
    channels = (Channel('salinity', 'g/L'), Channel('turbidity', 'NTU'))
    return StationManifest(
        'qingwan', channels, 'R0',
        tuple(ChannelCalibration(channel.name, channel.unit) for channel in channels),
    )
