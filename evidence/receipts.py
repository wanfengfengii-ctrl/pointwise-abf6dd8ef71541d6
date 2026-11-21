from dataclasses import dataclass
import json

from database import read_integer
from evidence.intervals import Interval, intersect_interval, validate_interval
from registry.channels import require_name


@dataclass(frozen=True)
class CoverageReceipt:
    receipt_id: str
    interval: Interval
    condition: tuple[str, ...]
    observer: str
    provenance: str


def validate_receipt(receipt, *, observer, condition, first_seq):
    if not isinstance(receipt, CoverageReceipt):
        raise ValueError('expected a coverage receipt')
    require_name(receipt.receipt_id, 'receipt identity')
    require_name(receipt.provenance, 'receipt provenance')
    validate_interval(receipt.interval, allow_empty=False)
    if receipt.observer != observer or receipt.condition != condition:
        raise ValueError('receipt is bound to a different observation')
    if receipt.interval.start < first_seq:
        raise ValueError('receipt predates observation eligibility')
    return receipt


def _from_row(row):
    condition = json.loads(row['condition'])
    if type(condition) is not list:
        raise ValueError('invalid stored receipt condition')
    return CoverageReceipt(
        row['receipt_id'], Interval(read_integer(row['lo']), read_integer(row['hi'])),
        tuple(condition), row['observer'], row['provenance'],
    )


def receipt_order(receipt):
    return receipt.interval, receipt.observer, receipt.receipt_id


class ReceiptLedger:
    def __init__(self, db):
        self.db = db

    def record(self, run_id, receipt):
        previous = self.db.execute(
            'SELECT * FROM receipts WHERE run_id = ? AND observer = ? AND receipt_id = ?',
            (run_id, receipt.observer, receipt.receipt_id),
        ).fetchone()
        if previous is not None:
            if _from_row(previous) != receipt:
                raise ValueError(f'conflicting receipt {receipt.receipt_id!r}')
            return False
        self.db.execute(
            'INSERT INTO receipts(run_id, observer, receipt_id, lo, hi, condition, provenance) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (run_id, receipt.observer, receipt.receipt_id, str(receipt.interval.start),
             str(receipt.interval.end), json.dumps(receipt.condition), receipt.provenance),
        )
        return True

    def intersecting(self, run_id, interval):
        rows = self.db.execute('SELECT * FROM receipts WHERE run_id = ?', (run_id,))
        receipts = []
        for row in rows:
            receipt = _from_row(row)
            validate_interval(receipt.interval, allow_empty=False)
            if intersect_interval(receipt.interval, interval) is not None:
                receipts.append(receipt)
        return tuple(sorted(receipts, key=receipt_order))
