from archive.artifacts import artifact_digest, decode_artifact, encode_artifact
from archive.eligibility import validate_evidence_binding
from archive.results import ResultStore, result_id_for
from evidence.intake import CaptureContext
from evidence.intervals import validate_interval
from quality.evaluation import evaluate_shift
from registry.channels import normalize_channels, require_name
from sessions.runs import validate_position


class StoredEvidenceError(ValueError):
    pass


def verify_artifact(stored):
    try:
        if type(stored.payload) is not str or artifact_digest(stored.payload) != stored.digest:
            raise ValueError('artifact digest mismatch')
        artifact = decode_artifact(stored.payload)
        if encode_artifact(artifact) != stored.payload:
            raise ValueError('noncanonical artifact')
        validate_position(artifact.run_id, 'run identity')
        validate_position(artifact.first_seq, 'first eligible sequence')
        validate_interval(artifact.interval)
        require_name(artifact.observer, 'observer')
        for interval in artifact.no_match:
            validate_interval(interval, allow_empty=False)
        if (artifact.run_id == 0 or stored.run_id != artifact.run_id
                or artifact.result_id != stored.result_id
                or artifact.result_id != result_id_for(artifact.run_id)
                or stored.end != artifact.interval.end
                or artifact.station != artifact.revision.station
                or artifact.condition != normalize_channels(artifact.condition)):
            raise ValueError('artifact identity or fixed binding mismatch')
        context = CaptureContext(
            artifact.run_id, artifact.interval.start, artifact.condition,
            artifact.observer, artifact.first_seq,
        )
        report = validate_evidence_binding(context, artifact.interval, artifact.frames, artifact.receipts)
        if report.missing or report.no_match != artifact.no_match:
            raise ValueError('frozen coverage does not match original evidence')
        expected = evaluate_shift(artifact.frames, artifact.revision, artifact.condition)
        if expected != artifact.quality:
            raise ValueError('frozen quality does not match the original evidence')
        return artifact
    except (TypeError, AttributeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise StoredEvidenceError(f'damaged evidence for {stored.result_id!r}: {exc}') from exc


def get(db, result_id):
    try:
        stored = ResultStore(db).load(result_id)
    except (TypeError, ValueError) as exc:
        raise StoredEvidenceError(f'damaged result index for {result_id!r}') from exc
    return verify_artifact(stored)
