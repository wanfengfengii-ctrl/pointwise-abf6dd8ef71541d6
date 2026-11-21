from database import transaction
from registry.calibrations import RevisionCatalog
from registry.channels import ChannelCatalog, require_channels, require_name
from sessions.portal import Registration, check_registration
from sessions.runs import RunStore, validate_position


def start(db, portal, station, revision_id, condition, start_seq):
    require_name(station, 'station')
    validate_position(start_seq, 'run start')
    revision = RevisionCatalog(db).resolve(station, revision_id)
    condition = require_channels(condition, ChannelCatalog(db).for_station(station))
    condition = require_channels(condition, (item.channel for item in revision.calibrations))
    registration = portal.register(station, condition)
    try:
        check_registration(registration)
        with transaction(db, write=True):
            return RunStore(db).insert(
                station, revision_id, start_seq, condition,
                registration.observer, registration.first_seq,
            )
    except BaseException as exc:
        if isinstance(registration, Registration) and registration.observer:
            try:
                portal.release(registration.observer)
            except Exception as release_error:
                exc.add_note(f'opening cleanup failed: {release_error}')
        raise
