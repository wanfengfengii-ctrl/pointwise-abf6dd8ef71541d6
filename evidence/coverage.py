from dataclasses import dataclass

from database import transaction
from evidence.frames import FrameLedger
from evidence.intake import CaptureContext
from evidence.intervals import (
    Interval, intersect_interval, normalize_intervals, subtract_intervals, validate_interval,
)
from evidence.receipts import ReceiptLedger, receipt_order
from sessions.runs import RunStore


@dataclass(frozen=True)
class CoverageReport:
    proven: tuple[Interval, ...]
    missing: tuple[Interval, ...]
    no_match: tuple[Interval, ...]


def inspect_coverage(interval, frames, receipts):
    validate_interval(interval)
    fragments = (intersect_interval(interval, receipt.interval) for receipt in receipts)
    proven = normalize_intervals(fragment for fragment in fragments if fragment is not None)
    occupied = (Interval(frame.seq, frame.seq + 1) for frame in frames)
    return CoverageReport(
        proven, subtract_intervals((interval,), proven), subtract_intervals(proven, occupied),
    )


def validate_selection(context, interval, frames, receipts):
    validate_interval(interval)
    if interval.start < context.start_seq:
        raise ValueError('target interval precedes run start')
    previous = interval.start - 1
    for frame in frames:
        context.check_frame(frame)
        if not previous < frame.seq < interval.end:
            raise ValueError('frames must be unique, ordered and within the target interval')
        previous = frame.seq
    seen_receipts = set()
    last_order = None
    for receipt in receipts:
        context.check_receipt(receipt)
        identity = receipt.observer, receipt.receipt_id
        order = receipt_order(receipt)
        if (identity in seen_receipts or (last_order is not None and order < last_order)
                or intersect_interval(interval, receipt.interval) is None):
            raise ValueError('invalid receipt selection')
        seen_receipts.add(identity)
        last_order = order


def coverage(db, run_id, start, end):
    interval = validate_interval(Interval(start, end))
    with transaction(db):
        run = RunStore(db).load(run_id)
        frames = FrameLedger(db).in_range(run_id, interval)
        receipts = ReceiptLedger(db).intersecting(run_id, interval)
        validate_selection(CaptureContext.from_run(run), interval, frames, receipts)
        return inspect_coverage(interval, frames, receipts)
