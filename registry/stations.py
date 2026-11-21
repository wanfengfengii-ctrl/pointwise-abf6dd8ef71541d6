from database import transaction
from registry.calibrations import RevisionCatalog
from registry.channels import ChannelCatalog, require_name
from registry.manifests import default_manifest


def _ensure_station(db, station):
    require_name(station, 'station')
    db.execute('INSERT INTO stations(station) VALUES (?) ON CONFLICT DO NOTHING', (station,))


def register(db, station, name, channels, calibrations):
    with transaction(db, write=True):
        _ensure_station(db, station)
        ChannelCatalog(db).declare(station, channels)
        return RevisionCatalog(db).store(station, name, calibrations)


def initialize_defaults(db):
    manifest = default_manifest()
    with transaction(db, write=True):
        _ensure_station(db, manifest.station)
        channels = ChannelCatalog(db)
        declared = channels.for_station(manifest.station)
        channels.declare(manifest.station, (
            item for item in manifest.channels if item.name not in declared
        ))
        revisions = RevisionCatalog(db)
        existing = revisions.find_id(manifest.station, manifest.revision_name)
        if existing is not None:
            return existing
        return revisions.store(
            manifest.station, manifest.revision_name,
            manifest.for_declared_channels(channels.for_station(manifest.station)),
        )
