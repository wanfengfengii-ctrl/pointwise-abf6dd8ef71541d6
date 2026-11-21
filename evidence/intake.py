from dataclasses import dataclass
from enum import Enum

from evidence.frames import FrameLedger, RawFrame, validate_frame
from evidence.receipts import CoverageReceipt, ReceiptLedger, validate_receipt


@dataclass(frozen=True)
class CaptureContext:
    run_id: int
    start_seq: int
    condition: tuple[str, ...]
    observer: str
    first_seq: int

    @classmethod
    def from_run(cls, run):
        return cls(run.run_id, run.start_seq, run.condition, run.observer, run.first_seq)

    def check_frame(self, frame):
        return validate_frame(
            frame, observer=self.observer, condition=self.condition, first_seq=self.first_seq,
        )

    def check_receipt(self, receipt):
        return validate_receipt(
            receipt, observer=self.observer, condition=self.condition, first_seq=self.first_seq,
        )


class IntakeOutcome(Enum):
    NEW_FRAME = 'new frame'
    NEW_RECEIPT = 'new receipt'
    REPLAY = 'replay'
    BEFORE_START = 'before start'


def accept_event(db, context, event):
    if isinstance(event, RawFrame):
        context.check_frame(event)
        if event.seq < context.start_seq:
            return IntakeOutcome.BEFORE_START
        if FrameLedger(db).record(context.run_id, event):
            return IntakeOutcome.NEW_FRAME
        return IntakeOutcome.REPLAY
    if isinstance(event, CoverageReceipt):
        context.check_receipt(event)
        if event.interval.end <= context.start_seq:
            return IntakeOutcome.BEFORE_START
        if ReceiptLedger(db).record(context.run_id, event):
            return IntakeOutcome.NEW_RECEIPT
        return IntakeOutcome.REPLAY
    raise ValueError('unknown evidence event')
