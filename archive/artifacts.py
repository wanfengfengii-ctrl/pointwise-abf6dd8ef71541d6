from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from evidence.frames import RawFrame
from evidence.intervals import Interval
from evidence.receipts import CoverageReceipt
from quality.conversion import ConvertedReading
from quality.evaluation import QualityReport
from quality.limits import LimitAssessment, LimitStatus
from quality.summary import ChannelSummary
from registry.calibrations import StationRevision, rational_from_pair, rational_pair
from registry.units import Quantity, resolve_unit
from sessions.runs import validate_position


@dataclass(frozen=True)
class ArchiveArtifact:
    result_id: str
    run_id: int
    station: str
    interval: Interval
    condition: tuple[str, ...]
    observer: str
    first_seq: int
    revision: StationRevision
    frames: tuple[RawFrame, ...]
    receipts: tuple[CoverageReceipt, ...]
    no_match: tuple[Interval, ...]
    quality: QualityReport


def _quality_data(report):
    readings = []
    for assessed in report.readings:
        reading = assessed.reading
        readings.append({
            'seq': reading.seq,
            'channel': reading.channel,
            'value': rational_pair(reading.quantity.value),
            'unit': reading.quantity.unit.symbol,
            'status': assessed.status.value,
        })
    summaries = []
    for summary in report.summaries:
        summaries.append({
            'channel': summary.channel,
            'unit': summary.unit.symbol,
            'valid_count': summary.valid_count,
            'mean': None if summary.mean is None else rational_pair(summary.mean),
            'below_count': summary.below_count,
            'above_count': summary.above_count,
        })
    return {'readings': readings, 'summaries': summaries}


def _read_quality(data):
    readings = []
    for item in data['readings']:
        quantity = Quantity(rational_from_pair(item['value']), resolve_unit(item['unit']))
        reading = ConvertedReading(validate_position(item['seq']), item['channel'], quantity)
        readings.append(LimitAssessment(reading, LimitStatus(item['status'])))
    summaries = []
    for item in data['summaries']:
        mean = None if item['mean'] is None else rational_from_pair(item['mean'])
        summaries.append(ChannelSummary(
            item['channel'], resolve_unit(item['unit']),
            validate_position(item['valid_count'], 'valid sample count'), mean,
            validate_position(item['below_count'], 'below-limit count'),
            validate_position(item['above_count'], 'above-limit count'),
        ))
    return QualityReport(tuple(readings), tuple(summaries))


def encode_artifact(artifact):
    data = {
        'version': 1,
        'result_id': artifact.result_id,
        'run_id': artifact.run_id,
        'station': artifact.station,
        'interval': asdict(artifact.interval),
        'condition': artifact.condition,
        'observer': artifact.observer,
        'first_seq': artifact.first_seq,
        'revision': artifact.revision.to_data(),
        'frames': [asdict(frame) for frame in artifact.frames],
        'receipts': [asdict(receipt) for receipt in artifact.receipts],
        'no_match': [asdict(interval) for interval in artifact.no_match],
        'quality': _quality_data(artifact.quality),
    }
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode_artifact(payload):
    data = json.loads(payload)
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('unsupported archive artifact version')
    receipts = tuple(CoverageReceipt(
        item['receipt_id'], Interval(**item['interval']), tuple(item['condition']),
        item['observer'], item['provenance'],
    ) for item in data['receipts'])
    return ArchiveArtifact(
        data['result_id'], data['run_id'], data['station'], Interval(**data['interval']),
        tuple(data['condition']), data['observer'], data['first_seq'],
        StationRevision.from_data(data['revision']),
        tuple(RawFrame(**item) for item in data['frames']), receipts,
        tuple(Interval(**item) for item in data['no_match']), _read_quality(data['quality']),
    )


def artifact_digest(payload):
    return sha256(payload.encode('utf-8')).hexdigest()
