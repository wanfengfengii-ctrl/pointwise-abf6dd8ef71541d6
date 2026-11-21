from contextlib import contextmanager
import sqlite3


_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS stations (
    station TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS channels (
    station TEXT NOT NULL REFERENCES stations(station),
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    PRIMARY KEY (station, name)
);
CREATE TABLE IF NOT EXISTS revisions (
    revision_id INTEGER PRIMARY KEY,
    station TEXT NOT NULL REFERENCES stations(station),
    name TEXT NOT NULL,
    specification TEXT NOT NULL,
    UNIQUE (station, name)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY,
    station TEXT NOT NULL REFERENCES stations(station),
    revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
    start_seq TEXT NOT NULL,
    condition TEXT NOT NULL,
    observer TEXT NOT NULL,
    first_seq TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'active',
    sealed_end TEXT,
    result_id TEXT REFERENCES results(result_id),
    CHECK ((status = 'active' AND sealed_end IS NULL AND result_id IS NULL)
        OR (status = 'sealed' AND sealed_end IS NOT NULL AND result_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS frames (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    seq TEXT NOT NULL,
    channel TEXT NOT NULL,
    value TEXT NOT NULL,
    observer TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS receipts (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    observer TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    lo TEXT NOT NULL,
    hi TEXT NOT NULL,
    condition TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (run_id, observer, receipt_id)
);
CREATE TABLE IF NOT EXISTS results (
    result_id TEXT PRIMARY KEY,
    run_id INTEGER NOT NULL UNIQUE REFERENCES runs(run_id),
    end_seq TEXT NOT NULL,
    payload TEXT NOT NULL,
    digest TEXT NOT NULL
);
COMMIT;
"""


def open_database(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript(_SCHEMA)
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def transaction(db, *, write=False):
    db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def read_integer(text):
    # Decimal text keeps source integers independent of SQLite's signed range.
    if type(text) is not str:
        raise ValueError('expected stored integer text')
    value = int(text)
    if str(value) != text:
        raise ValueError('noncanonical stored integer')
    return value
