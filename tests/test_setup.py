from fractions import Fraction

from registry import initialize_defaults, register
from registry.calibrations import ChannelCalibration, RevisionCatalog
from registry.channels import Channel, ChannelCatalog
from samples.portal_fixture import STATION
from sessions.opening import start
from sessions.runs import RunStore
from tests import ShiftCase


class TestSetup(ShiftCase):
    def test_repeat_init(self):
        revision_id = self.register_r1()
        self.reopen()
        self.assertEqual(initialize_defaults(self.db), self.default_id)
        self.assertEqual(initialize_defaults(self.db), self.default_id)
        self.assertEqual(self.db.execute('SELECT count(*) FROM stations').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM channels').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)
        with self.subTest(case_id='init_repeat.manual_revision'):
            revision = RevisionCatalog(self.db).resolve(STATION, revision_id)
            self.assertEqual(revision.name, 'R1')
            self.assertEqual(revision.for_channel('salinity').scale, Fraction(1, 3))
            run_id, _ = self.open_run(revision_id=revision_id)
            self.assertEqual(RunStore(self.db).load(run_id).revision_id, revision_id)
        with self.subTest(case_id='init_repeat.revision_immutable'):
            self.assertEqual(register(self.db, STATION, 'R1', (), (
                ChannelCalibration('turbidity', 'NTU', Fraction(1, 2), lower='0/2', upper='4/2'),
                ChannelCalibration('salinity', 'g/L', '2/6', upper='14/12'),
            )), revision_id)
            with self.assertRaisesRegex(ValueError, 'different content'):
                register(self.db, STATION, 'R1', (Channel('extra', 'g/L'),), (
                    ChannelCalibration('salinity', 'g/L', 2),
                ))
            self.assertNotIn('extra', ChannelCatalog(self.db).for_station(STATION))
            self.assertEqual(RevisionCatalog(self.db).resolve(STATION, revision_id), revision)
            self.assertEqual(self.db.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)

    def test_wrong_revision(self):
        foreign = register(self.db, 'north-bank', 'R1', (Channel('salinity', 'g/L'),), (
            ChannelCalibration('salinity', 'g/L', 9),
        ))
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            start(self.db, self.portal, STATION, foreign, ('salinity',), 0)
        self.assertEqual(self.portal.active_handles, ())
        self.assertEqual(self.db.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        with self.subTest(case_id='wrong_revision.invalid_channel'):
            with self.assertRaisesRegex(ValueError, 'unknown or uncalibrated'):
                self.open_run(('unknown',))
            partial = register(self.db, STATION, 'salinity-only', (), (
                ChannelCalibration('salinity', 'g/L'),
            ))
            with self.assertRaisesRegex(ValueError, 'unknown or uncalibrated'):
                self.open_run(('turbidity',), revision_id=partial)
        with self.subTest(case_id='wrong_revision.portal_reject'):
            self.portal.registrations_enabled = False
            with self.assertRaisesRegex(OSError, 'rejected registration'):
                self.open_run()
        self.assertEqual(self.portal.active_handles, ())
        self.assertEqual(self.db.execute('SELECT count(*) FROM runs').fetchone()[0], 0)

    def test_registration_rejects_unknown_unit_and_inexact_input(self):
        with self.assertRaisesRegex(ValueError, 'unknown unit'):
            Channel('salinity', 'unknown')
        for value in (0.1, True, '1/0'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ChannelCalibration('salinity', 'g/L', value)
        with self.assertRaisesRegex(ValueError, 'incompatible units'):
            register(self.db, 'new-station', 'R1', (Channel('salinity', 'g/L'),), (
                ChannelCalibration('salinity', 'mg/L'),
            ))
        self.assertEqual(self.db.execute('SELECT count(*) FROM stations').fetchone()[0], 1)

    def test_failed_local_open_releases_registration(self):
        self.db.execute('''
            CREATE TRIGGER reject_open BEFORE INSERT ON runs
            BEGIN SELECT RAISE(ABORT, 'local run write rejected'); END
        ''')
        import sqlite3
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'local run write rejected'):
            self.open_run()
        self.assertEqual(self.portal.active_handles, ())
        self.assertEqual(self.db.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
