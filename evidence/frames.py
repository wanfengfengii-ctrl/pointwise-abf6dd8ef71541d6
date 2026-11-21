from dataclasses import dataclass

from database import read_integer
from registry.channels import require_name
from sessions.runs import validate_position


@dataclass(frozen=True)
class RawFrame:
    seq: int
    channel: str
    value: int
    observer: str
    provenance: str


class FrameConflict(ValueError):
    pass


def validate_frame(frame, *, observer, condition, first_seq):
    if not isinstance(frame, RawFrame):
        raise ValueError('expected an original frame')
    validate_position(frame.seq)
    require_name(frame.provenance, 'frame provenance')
    if frame.observer != observer or frame.channel not in condition:
        raise ValueError('frame is outside its observation binding')
    if frame.seq < first_seq or type(frame.value) is not int:
        raise ValueError('frame is ineligible or its value is not an integer')
    return frame


class FrameLedger:
    def __init__(self, db):
        self.db = db

    def record(self, run_id, frame):
        previous = self.db.execute(
            'SELECT channel, value FROM frames WHERE run_id = ? AND seq = ?',
            (run_id, str(frame.seq)),
        ).fetchone()
        if previous is not None:
            if (previous['channel'], read_integer(previous['value'])) != (frame.channel, frame.value):
                raise FrameConflict(f'conflicting original frame at sequence {frame.seq}')
            return False
        self.db.execute(
            'INSERT INTO frames(run_id, seq, channel, value, observer, provenance) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (run_id, str(frame.seq), frame.channel, str(frame.value), frame.observer, frame.provenance),
        )
        return True

    def in_range(self, run_id, interval):
        rows = self.db.execute(
            'SELECT seq, channel, value, observer, provenance FROM frames WHERE run_id = ?',
            (run_id,),
        )
        frames = []
        for row in rows:
            seq = validate_position(read_integer(row['seq']))
            if interval.start <= seq < interval.end:
                frames.append(RawFrame(
                    seq, row['channel'], read_integer(row['value']),
                    row['observer'], row['provenance'],
                ))
        return tuple(sorted(frames, key=lambda frame: frame.seq))
