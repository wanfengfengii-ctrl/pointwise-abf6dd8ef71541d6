from dataclasses import replace

from evidence.coverage import coverage
from evidence.frames import FrameConflict, FrameLedger, RawFrame
from evidence.intervals import Interval
from evidence.receipts import CoverageReceipt, ReceiptLedger
from samples.portal_fixture import DAY_SOURCE, ESTUARY_REPLAY, ESTUARY_REPLAY_START, STATION, ScriptedPortal
from sessions.driver import step
from sessions.runs import RunStore
from tests import ShiftCase


class TestCapture(ShiftCase):
    def test_reorder(self):
        run_id, handle = self.open_run()
        self.portal.advance(*DAY_SOURCE)
        self.portal.emit_frame(handle, 3)
        step(self.db, self.portal, run_id)
        with self.subTest(case_id='order.coverage_classification'):
            report = coverage(self.db, run_id, 0, 5)
            self.assertEqual((report.proven, report.missing, report.no_match), ((), (Interval(0, 5),), ()))
        self.portal.emit_receipt(handle, 2, 5)
        self.portal.emit_frame(handle, 1)
        self.portal.emit_frame(handle, 1, provenance='redelivery/1')
        report = step(self.db, self.portal, run_id)
        with self.subTest(case_id='order.late_frame'):
            self.assertEqual((report.acknowledged, report.new_frames, report.new_receipts, report.position),
                             (3, 1, 1, 4))
            frames = FrameLedger(self.db).in_range(run_id, Interval(0, 5))
            self.assertEqual([(item.seq, item.value, item.provenance) for item in frames],
                             [(1, 3, 'qingwan/source/1'), (3, 4, 'qingwan/source/3')])
        result = coverage(self.db, run_id, 0, 5)
        self.assertEqual(result.proven, (Interval(2, 5),))
        self.assertEqual(result.missing, (Interval(0, 2),))
        self.assertEqual(result.no_match, (Interval(2, 3), Interval(4, 5)))
        self.portal.emit_receipt(handle, 2, 5)
        replay = step(self.db, self.portal, run_id)
        self.assertEqual((replay.acknowledged, replay.new_frames, replay.new_receipts), (1, 0, 0))
        self.assertEqual(coverage(self.db, run_id, 0, 5), result)

    def test_conflict(self):
        run_id, handle = self.open_run()
        self.portal.advance(*DAY_SOURCE, ('salinity', 8))
        self.portal.emit_frame(handle, 1)
        step(self.db, self.portal, run_id)
        self.portal.emit_frame(handle, 3)
        self.portal.append_event(handle, RawFrame(1, 'salinity', 9, handle, 'conflicting/1'))
        self.portal.emit_frame(handle, 5)
        for _ in range(2):
            with self.assertRaisesRegex(FrameConflict, 'sequence 1'):
                step(self.db, self.portal, run_id)
            with self.subTest(case_id='conflict.accepted_prefix'):
                run = RunStore(self.db).load(run_id)
                self.assertEqual(run.position, 2)
                frames = FrameLedger(self.db).in_range(run_id, Interval(0, 6))
                self.assertEqual([(frame.seq, frame.value) for frame in frames], [(1, 3), (3, 4)])
                self.assertEqual(frames[0].provenance, 'qingwan/source/1')

    def test_receipt_binding(self):
        for label in ('wrong condition', 'wrong source', 'inverted interval', 'wrong envelope'):
            with self.subTest(case_id='order.receipt_binding', input=label):
                begin = self.portal.next_seq
                run_id, handle = self.open_run(start_seq=begin)
                self.portal.advance(('turbidity', 1), ('turbidity', 2))
                self.portal.emit_receipt(handle, begin, begin + 1)
                step(self.db, self.portal, run_id)
                receipt = CoverageReceipt('later', Interval(begin + 1, begin + 2),
                                          ('salinity',), handle, 'portal/later')
                envelope = {}
                if label == 'wrong condition':
                    receipt = replace(receipt, condition=('turbidity',))
                elif label == 'wrong source':
                    receipt = replace(receipt, observer='another-observer')
                elif label == 'inverted interval':
                    receipt = replace(receipt, interval=Interval(begin + 2, begin + 1))
                else:
                    envelope['observer'] = 'another-observer'
                self.portal.append_event(handle, receipt, **envelope)
                with self.assertRaises(ValueError):
                    step(self.db, self.portal, run_id)
                self.assertEqual(RunStore(self.db).load(run_id).position, 1)
                actual = ReceiptLedger(self.db).intersecting(run_id, Interval(begin, begin + 2))
                self.assertEqual([item.interval for item in actual], [Interval(begin, begin + 1)])

    def test_late_registration_and_portal_failure(self):
        self.portal.advance(('salinity', 3), ('turbidity', 4))
        run_id, handle = self.open_run()
        self.assertEqual(RunStore(self.db).load(run_id).first_seq, 2)
        self.portal.advance(('salinity', 8))
        self.portal.emit_frame(handle, 2)
        self.portal.emit_receipt(handle, 2, 3)
        step(self.db, self.portal, run_id)
        self.assertEqual(coverage(self.db, run_id, 0, 3).missing, (Interval(0, 2),))
        self.portal.shutdown()
        with self.assertRaisesRegex(OSError, 'offline'):
            step(self.db, self.portal, run_id)
        self.assertEqual(RunStore(self.db).load(run_id).position, 2)

    def test_independent_observations_and_retained_history(self):
        portal = ScriptedPortal(first_seq=ESTUARY_REPLAY_START, history_limit=2)
        self.addCleanup(portal.shutdown)
        portal.advance(*ESTUARY_REPLAY[:2])
        old = portal.register(STATION, ('salinity',))
        early = portal.register(STATION, ('turbidity',))
        self.assertEqual((old.first_seq, early.first_seq), (100, 100))
        portal.advance(*ESTUARY_REPLAY[2:4])
        portal.emit_frame(old.observer, 101)
        old_receipt = portal.emit_receipt(old.observer, 100, 102).event
        self.assertEqual(old_receipt.condition, ('salinity',))
        late = portal.register(STATION, ('turbidity',))
        self.assertEqual(late.first_seq, 102)
        retained = portal.read_history(STATION, ('turbidity',), 100, 102)
        self.assertEqual([frame.seq for frame in retained.frames], [100])
        self.assertEqual([item.interval for item in retained.receipts], [Interval(100, 102)])
        self.assertEqual(retained.unavailable, ())
        portal.advance(*ESTUARY_REPLAY[4:])
        portal.emit_frame(early.observer, 103)
        self.assertEqual([item.event.seq for item in portal.poll(early.observer, 0)], [103])
        with self.assertRaisesRegex(ValueError, 'still await delivery'):
            portal.emit_receipt(early.observer, 100, 104)
        portal.emit_frame(early.observer, 100)
        early_receipt = portal.emit_receipt(early.observer, 100, 104).event
        self.assertEqual(early_receipt.interval, Interval(100, 104))
        portal.emit_frame(late.observer, 103)
        self.assertEqual(portal.emit_receipt(late.observer, 102, 104).event.interval, Interval(102, 104))
        expired = portal.read_history(STATION, ('turbidity',), 100, 105)
        self.assertEqual([frame.seq for frame in expired.frames], [103])
        self.assertEqual(expired.unavailable, (Interval(100, 102),))
        self.assertEqual(expired.pending, (Interval(104, 105),))
        self.assertEqual([item.interval for item in expired.receipts], [Interval(102, 104)])
        empty = portal.read_history(STATION, ('salinity',), 103, 104)
        self.assertEqual(empty.frames, ())
        self.assertEqual([item.interval for item in empty.receipts], [Interval(103, 104)])
