from dataclasses import dataclass

from database import read_integer


@dataclass(frozen=True)
class StoredResult:
    result_id: str
    run_id: int
    end: int
    payload: str
    digest: str


def result_id_for(run_id):
    return f'shift-{run_id}'


def _decode_row(row):
    return StoredResult(
        row['result_id'], row['run_id'], read_integer(row['end_seq']), row['payload'], row['digest'],
    )


class ResultStore:
    def __init__(self, db):
        self.db = db

    def insert(self, stored):
        self.db.execute(
            'INSERT INTO results(result_id, run_id, end_seq, payload, digest) VALUES (?, ?, ?, ?, ?)',
            (stored.result_id, stored.run_id, str(stored.end), stored.payload, stored.digest),
        )

    def load(self, result_id):
        if type(result_id) is not str:
            raise KeyError(result_id)
        row = self.db.execute('SELECT * FROM results WHERE result_id = ?', (result_id,)).fetchone()
        if row is None:
            raise KeyError(result_id)
        return _decode_row(row)

    def find_by_run(self, run_id):
        row = self.db.execute('SELECT * FROM results WHERE run_id = ?', (run_id,)).fetchone()
        return None if row is None else _decode_row(row)
