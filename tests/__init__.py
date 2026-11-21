from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import open_database
from registry import initialize_defaults, register
from registry.calibrations import ChannelCalibration
from samples.portal_fixture import STATION, ScriptedPortal
from sessions.opening import start
from sessions.runs import RunStore


class ShiftCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / 'station.sqlite'
        self.db = open_database(self.path)
        self.addCleanup(lambda: self.db.close())
        self.portal = ScriptedPortal()
        self.addCleanup(self.portal.shutdown)
        self.default_id = initialize_defaults(self.db)

    def reopen(self):
        self.db.close()
        self.db = open_database(self.path)
        return self.db

    def register_r1(self):
        return register(self.db, STATION, 'R1', (), (
            ChannelCalibration('salinity', 'g/L', '1/3', upper='7/6'),
            ChannelCalibration('turbidity', 'NTU', '1/2', lower=0, upper=2),
        ))

    def open_run(self, condition=('salinity',), *, revision_id=None, start_seq=0):
        run_id = start(
            self.db, self.portal, STATION,
            self.default_id if revision_id is None else revision_id, condition, start_seq,
        )
        return run_id, RunStore(self.db).load(run_id).observer
