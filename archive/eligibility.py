from dataclasses import dataclass

from evidence.coverage import inspect_coverage, validate_selection
from evidence.frames import FrameLedger, RawFrame
from evidence.intake import CaptureContext
from evidence.intervals import Interval, validate_interval
from evidence.receipts import CoverageReceipt, ReceiptLedger


@dataclass(frozen=True)
class SealSelection:
    interval: Interval
    frames: tuple[RawFrame, ...]
    receipts: tuple[CoverageReceipt, ...]
    no_match: tuple[Interval, ...]


@dataclass(frozen=True)
class SealDecision:
    missing: tuple[Interval, ...]
    selection: SealSelection | None


def validate_evidence_binding(context, interval, frames, receipts):
    if interval.start != context.start_seq:
        raise ValueError('frozen interval must start at the run start')
    validate_selection(context, interval, frames, receipts)
    return inspect_coverage(interval, frames, receipts)


def assess_seal(db, run, end):
    interval = validate_interval(Interval(run.start_seq, end))
    frames = FrameLedger(db).in_range(run.run_id, interval)
    receipts = ReceiptLedger(db).intersecting(run.run_id, interval)
    report = validate_evidence_binding(CaptureContext.from_run(run), interval, frames, receipts)
    if report.missing:
        return SealDecision(report.missing, None)
    return SealDecision((), SealSelection(interval, frames, receipts, report.no_match))
