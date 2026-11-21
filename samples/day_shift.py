from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive import get, seal
from database import open_database
from evidence.coverage import coverage
from evidence.intervals import Interval
from registry import initialize_defaults, register
from registry.calibrations import ChannelCalibration
from sessions.driver import step
from sessions.opening import start
from samples.portal_fixture import DAY_SOURCE, STATION, ScriptedPortal


def _emit_scenario(artifact, cutoff, early_gap):
    expected = {'source_sequences': [1, 3], 'raw_values': [3, 4], 'first_gap': [[0, 2]]}
    actual = {
        'source_sequences': [frame.seq for frame in artifact.frames],
        'raw_values': [frame.value for frame in artifact.frames],
        'first_gap': [[span.start, span.end] for span in early_gap],
    }
    downstream_expected = {
        'values': ['1', '4/3'], 'mean': '7/6', 'unit': 'g/L',
        'limits': ['within', 'above'], 'no_match': [[0, 1], [2, 3], [4, 5]],
    }
    summary, = artifact.quality.summaries
    downstream_actual = {
        'values': [str(item.reading.quantity.value) for item in artifact.quality.readings],
        'mean': str(summary.mean),
        'unit': summary.unit.symbol,
        'limits': [item.status.value for item in artifact.quality.readings],
        'no_match': [[span.start, span.end] for span in artifact.no_match],
    }
    assert actual == expected
    assert downstream_actual == downstream_expected
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'reopen',
        'input': {'source': DAY_SOURCE, 'delivery': [3, 'receipt [2,5)', 1, 1, 'receipt [0,2)'],
                  'condition': ['salinity'], 'scale': '1/3', 'upper': '7/6', 'cutoff': cutoff},
        'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['sessions/driver.py', 'evidence/coverage.py', 'archive/publish.py',
                       'quality/evaluation.py', 'quality/summary.py', 'archive/audit.py'],
        'oracle': 'Hand-filter five positions. Divide 3 and 4 by 3 and average to 7/6. '
                  'Only 4/3 exceeds 7/6. Source positions 0, 2 and 4 are turbidity.',
    }, ensure_ascii=False, sort_keys=True))


def main():
    portal = ScriptedPortal()
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'qingwan.sqlite'
        with closing(open_database(path)) as db:
            default_id = initialize_defaults(db)
            revision_id = register(db, STATION, 'R1', (), (
                ChannelCalibration('salinity', 'g/L', '1/3', upper='7/6'),
            ))
            assert initialize_defaults(db) == default_id
            run_id = start(db, portal, STATION, revision_id, {'salinity'}, 0)
            handle, = portal.active_handles
            portal.advance(*DAY_SOURCE)
            portal.emit_frame(handle, 3)
            assert step(db, portal, run_id).new_frames == 1
            assert coverage(db, run_id, 0, 5).missing == (Interval(0, 5),)
            portal.emit_receipt(handle, 2, 5)
            portal.emit_frame(handle, 1)
            portal.emit_frame(handle, 1, provenance='redelivery/1')
            batch = step(db, portal, run_id)
            assert (batch.acknowledged, batch.new_frames, batch.new_receipts) == (3, 1, 1)
            first = seal(db, run_id, 5, portal=portal)
            assert first.result_id is None and first.missing == (Interval(0, 2),)
            portal.emit_receipt(handle, 0, 2)
            step(db, portal, run_id)
            fixed = seal(db, run_id, 5, portal=portal)
            assert fixed.result_id is not None and fixed.release_error is None
            register(db, STATION, 'R2', (), (ChannelCalibration('salinity', 'g/L', 2),))

            empty_id = start(db, portal, STATION, revision_id, {'salinity'}, 5)
            handle, = portal.active_handles
            portal.advance(('turbidity', 8), ('turbidity', 9))
            assert seal(db, empty_id, 7, portal=portal).missing == (Interval(5, 7),)
            portal.emit_receipt(handle, 5, 7)
            assert step(db, portal, empty_id).new_receipts == 1
            empty = seal(db, empty_id, 7, portal=portal)
            assert empty.result_id is not None
        portal.shutdown()
        with closing(open_database(path)) as db:
            artifact = get(db, fixed.result_id)
            assert artifact.revision.revision_id == revision_id
            assert tuple(frame.provenance for frame in artifact.frames) == (
                'qingwan/source/1', 'qingwan/source/3',
            )
            assert artifact.quality.summaries[0].mean == Fraction(7, 6)
            _emit_scenario(artifact, 5, first.missing)
            print(f'{artifact.result_id} 离线领取，盐度均值 {artifact.quality.summaries[0].mean} g/L')
            empty_artifact = get(db, empty.result_id)
            empty_summary, = empty_artifact.quality.summaries
            assert empty_artifact.frames == ()
            assert empty_artifact.no_match == (Interval(5, 7),)
            assert empty_summary.valid_count == 0 and empty_summary.mean is None
            print(f'{empty_artifact.result_id} 离线领取，[5,7) 已证无匹配，均值为空')


if __name__ == '__main__':
    main()
