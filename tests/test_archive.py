from contextlib import closing
from fractions import Fraction
import json
import sqlite3

from archive import StoredEvidenceError, get, seal
from archive.artifacts import artifact_digest
from archive.results import ResultStore
from database import open_database
from evidence.intervals import Interval
from quality.limits import LimitStatus
from registry import register
from registry.calibrations import ChannelCalibration
from samples.portal_fixture import DAY_SOURCE, STATION
from sessions.driver import step
from sessions.runs import RunStatus, RunStore
from tests import ShiftCase


class TestArchive(ShiftCase):
    def _capture_exact(self, *, extra=False):
        r1 = self.register_r1()
        run_id, handle = self.open_run(revision_id=r1)
        source = DAY_SOURCE + ((('salinity', 99),) if extra else ())
        self.portal.advance(*source)
        for seq in ((3, 1, 5) if extra else (3, 1)):
            self.portal.emit_frame(handle, seq)
        self.portal.emit_receipt(handle, 0, len(source))
        step(self.db, self.portal, run_id)
        return r1, run_id, handle

    def test_gap(self):
        run_id, handle = self.open_run()
        self.portal.advance(*DAY_SOURCE)
        self.portal.emit_frame(handle, 3)
        self.portal.emit_receipt(handle, 2, 5)
        step(self.db, self.portal, run_id)
        outcome = seal(self.db, run_id, 5, portal=self.portal)
        self.assertIsNone(outcome.result_id)
        self.assertEqual(outcome.missing, (Interval(0, 2),))
        self.assertIsNone(ResultStore(self.db).find_by_run(run_id))
        self.assertEqual(RunStore(self.db).load(run_id).status, RunStatus.ACTIVE)
        self.portal.emit_frame(handle, 1)
        self.portal.emit_receipt(handle, 0, 2)
        step(self.db, self.portal, run_id)
        self.assertIsNotNone(seal(self.db, run_id, 5, portal=self.portal).result_id)

    def test_disjoint_receipts(self):
        r1 = self.register_r1()
        run_id, handle = self.open_run(('salinity', 'turbidity'), revision_id=r1)
        self.portal.advance(('salinity', 3), ('salinity', 3), ('salinity', 3),
                            ('salinity', 4), ('salinity', 3))
        for seq in (3, 4, 0):
            self.portal.emit_frame(handle, seq)
        self.portal.emit_receipt(handle, 0, 1)
        self.portal.emit_receipt(handle, 3, 5)
        step(self.db, self.portal, run_id)
        refused = seal(self.db, run_id, 5, portal=self.portal)
        self.assertEqual(refused.missing, (Interval(1, 3),))
        self.assertIsNone(refused.result_id)
        self.assertIsNone(ResultStore(self.db).find_by_run(run_id))
        for seq in (1, 2):
            self.portal.emit_frame(handle, seq)
        self.portal.emit_receipt(handle, 1, 3)
        step(self.db, self.portal, run_id)
        fixed = seal(self.db, run_id, 5, portal=self.portal)
        artifact = get(self.db, fixed.result_id)
        self.assertEqual([frame.seq for frame in artifact.frames], [0, 1, 2, 3, 4])
        self.assertEqual(artifact.no_match, ())
        salinity, turbidity = artifact.quality.summaries
        self.assertEqual((salinity.mean, salinity.valid_count), (Fraction(16, 15), 5))
        self.assertEqual((turbidity.mean, turbidity.valid_count), (None, 0))

    def test_bad_end_and_evidence(self):
        run_id, handle = self.open_run(start_seq=1)
        self.portal.advance(('turbidity', 1), ('turbidity', 2))
        with self.subTest(case_id='gap.bad_end'):
            with self.assertRaisesRegex(ValueError, 'invalid interval'):
                seal(self.db, run_id, 0, portal=self.portal)
        self.portal.emit_receipt(handle, 0, 2)
        step(self.db, self.portal, run_id)
        with self.subTest(case_id='gap.bad_evidence'):
            self.db.execute('UPDATE receipts SET condition = ? WHERE run_id = ?',
                            (json.dumps(['turbidity']), run_id))
            with self.assertRaisesRegex(ValueError, 'different observation'):
                seal(self.db, run_id, 2, portal=self.portal)
        self.assertIsNone(ResultStore(self.db).find_by_run(run_id))
        self.assertEqual(RunStore(self.db).load(run_id).status, RunStatus.ACTIVE)

    def test_offline_exact(self):
        r1, run_id, handle = self._capture_exact(extra=True)
        register(self.db, STATION, 'R2', (), (ChannelCalibration('salinity', 'g/L', 2),))
        outcome = seal(self.db, run_id, 5, portal=self.portal)
        self.assertEqual(outcome.missing, ())
        self.assertIsNone(outcome.release_error)
        self.assertNotIn(handle, self.portal.active_handles)
        self.portal.shutdown()
        artifact = get(self.reopen(), outcome.result_id)
        with self.subTest(case_id='reopen.frozen_revision'):
            self.assertEqual((artifact.revision.revision_id, artifact.revision.name), (r1, 'R1'))
            self.assertEqual(artifact.revision.for_channel('salinity').scale, Fraction(1, 3))
        with self.subTest(case_id='reopen.half_open'):
            self.assertEqual(artifact.interval, Interval(0, 5))
            self.assertEqual([(frame.seq, frame.value, frame.provenance) for frame in artifact.frames],
                             [(1, 3, 'qingwan/source/1'), (3, 4, 'qingwan/source/3')])
            self.assertEqual(artifact.no_match, (Interval(0, 1), Interval(2, 3), Interval(4, 5)))
            receipt, = artifact.receipts
            self.assertEqual((receipt.observer, receipt.interval, receipt.condition),
                             (handle, Interval(0, 6), ('salinity',)))
        with self.subTest(case_id='reopen.exact_mean'):
            readings = artifact.quality.readings
            self.assertEqual([item.reading.quantity.value for item in readings], [Fraction(1), Fraction(4, 3)])
            self.assertEqual([item.status for item in readings], [LimitStatus.WITHIN, LimitStatus.ABOVE])
            summary, = artifact.quality.summaries
            self.assertEqual((summary.unit.symbol, summary.valid_count, summary.mean, summary.above_count),
                             ('g/L', 2, Fraction(7, 6), 1))
        with self.subTest(case_id='reopen.unknown_result'):
            with self.assertRaises(KeyError):
                get(self.db, 'shift-999')

    def test_mixed_units(self):
        r1 = self.register_r1()
        run_id, handle = self.open_run(('turbidity', 'salinity', 'salinity'), revision_id=r1)
        self.portal.advance(('salinity', 4), ('turbidity', 4), ('turbidity', 6), ('salinity', 3))
        for seq in (2, 0, 3, 1):
            self.portal.emit_frame(handle, seq)
        self.portal.emit_receipt(handle, 0, 4)
        step(self.db, self.portal, run_id)
        fixed = seal(self.db, run_id, 4, portal=self.portal)
        self.portal.shutdown()
        artifact = get(self.reopen(), fixed.result_id)
        self.assertEqual(artifact.condition, ('salinity', 'turbidity'))
        self.assertEqual([(item.reading.quantity.value, item.status.value) for item in artifact.quality.readings],
                         [(Fraction(4, 3), 'above'), (Fraction(2), 'within'),
                          (Fraction(3), 'above'), (Fraction(1), 'within')])
        self.assertEqual([(item.channel, item.unit.symbol, item.mean, item.valid_count, item.above_count)
                          for item in artifact.quality.summaries],
                         [('salinity', 'g/L', Fraction(7, 6), 2, 1),
                          ('turbidity', 'NTU', Fraction(5, 2), 2, 1)])

    def test_proven_empty(self):
        run_id, handle = self.open_run()
        self.portal.advance(('turbidity', 4), ('turbidity', 5))
        with self.subTest(case_id='empty.without_receipt'):
            self.assertEqual(step(self.db, self.portal, run_id).new_frames, 0)
            first = seal(self.db, run_id, 2, portal=self.portal)
            self.assertEqual(first.missing, (Interval(0, 2),))
            self.assertIsNone(first.result_id)
        self.portal.emit_receipt(handle, 0, 2)
        self.assertEqual(step(self.db, self.portal, run_id).new_receipts, 1)
        final = seal(self.db, run_id, 2, portal=self.portal)
        self.portal.shutdown()
        artifact = get(self.reopen(), final.result_id)
        self.assertEqual(artifact.frames, ())
        self.assertEqual(artifact.no_match, (Interval(0, 2),))
        summary, = artifact.quality.summaries
        self.assertEqual(summary.valid_count, 0)
        self.assertIsNone(summary.mean)

    def test_zero_width_seal(self):
        run_id, _ = self.open_run(start_seq=4)
        fixed = seal(self.db, run_id, 4, portal=self.portal)
        artifact = get(self.db, fixed.result_id)
        self.assertEqual((artifact.interval, artifact.frames, artifact.receipts, artifact.no_match),
                         (Interval(4, 4), (), (), ()))
        self.assertIsNone(artifact.quality.summaries[0].mean)

    def test_commit_failure(self):
        r1, old_run, _ = self._capture_exact()
        old = seal(self.db, old_run, 5, portal=self.portal)
        new_run, handle = self.open_run(revision_id=r1, start_seq=5)
        self.portal.advance(('salinity', 9))
        self.portal.emit_frame(handle, 5)
        self.portal.emit_receipt(handle, 5, 6)
        step(self.db, self.portal, new_run)
        self.db.executescript('''
            CREATE TABLE allowed_commit(run_id INTEGER PRIMARY KEY);
            CREATE TABLE commit_guard (
                run_id INTEGER REFERENCES allowed_commit(run_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER reject_commit AFTER UPDATE OF status ON runs
            WHEN NEW.status = 'sealed'
            BEGIN INSERT INTO commit_guard(run_id) VALUES (NEW.run_id); END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            seal(self.db, new_run, 6, portal=self.portal)
        self.assertFalse(self.db.in_transaction)
        self.assertIn(handle, self.portal.active_handles)
        with closing(open_database(self.path)) as reader:
            self.assertEqual(get(reader, old.result_id).quality.summaries[0].mean, Fraction(7, 6))
            self.assertIsNone(ResultStore(reader).find_by_run(new_run))
            self.assertEqual(RunStore(reader).load(new_run).status, RunStatus.ACTIVE)
            self.assertEqual(reader.execute('SELECT count(*) FROM commit_guard').fetchone()[0], 0)
        with self.subTest(case_id='rollback.retry'):
            self.db.execute('DROP TRIGGER reject_commit')
            retried = seal(self.db, new_run, 6, portal=self.portal)
            self.assertIsNotNone(retried.result_id)
            self.assertNotIn(handle, self.portal.active_handles)
            self.assertEqual(get(self.db, retried.result_id).quality.summaries[0].mean, Fraction(3))
        with self.subTest(case_id='rollback.seal_retry'):
            self.portal.shutdown()
            self.assertEqual(seal(self.db, new_run, 6, portal=self.portal).result_id, retried.result_id)
            with self.assertRaisesRegex(ValueError, 'different cutoff'):
                seal(self.db, new_run, 7, portal=self.portal)
            self.assertEqual(self.db.execute('SELECT count(*) FROM results').fetchone()[0], 2)
            self.assertEqual(get(self.db, old.result_id).quality.summaries[0].mean, Fraction(7, 6))

    def test_damaged_evidence(self):
        _, run_id, _ = self._capture_exact()
        fixed = seal(self.db, run_id, 5, portal=self.portal)
        path = self.path.with_name('damaged.sqlite')
        with closing(open_database(path)) as damaged:
            self.db.backup(damaged)
            stored = ResultStore(damaged).load(fixed.result_id)
            data = json.loads(stored.payload)
            data['frames'][0]['value'] = 6
            modified = json.dumps(data, sort_keys=True, separators=(',', ':'))
            damaged.execute('UPDATE results SET payload = ? WHERE result_id = ?',
                            (modified, fixed.result_id))
        self.portal.shutdown()
        self.assertEqual(get(self.reopen(), fixed.result_id).frames[0].value, 3)
        with closing(open_database(path)) as damaged:
            with self.assertRaisesRegex(StoredEvidenceError, 'digest mismatch'):
                get(damaged, fixed.result_id)
            damaged.execute('UPDATE results SET digest = ? WHERE result_id = ?',
                            (artifact_digest(modified), fixed.result_id))
            with self.assertRaisesRegex(StoredEvidenceError, 'quality does not match'):
                get(damaged, fixed.result_id)
