from dataclasses import dataclass

from archive.artifacts import ArchiveArtifact, artifact_digest, encode_artifact
from archive.eligibility import assess_seal
from archive.results import ResultStore, StoredResult, result_id_for
from database import transaction
from evidence.intervals import Interval, validate_interval
from quality.evaluation import evaluate_shift
from registry.calibrations import RevisionCatalog
from sessions.closing import finish_run, release_observer, sealed_result_for
from sessions.runs import RunStore


@dataclass(frozen=True)
class SealOutcome:
    result_id: str | None
    missing: tuple[Interval, ...] = ()
    release_error: str | None = None


def seal(db, run_id, end, *, portal):
    with transaction(db, write=True):
        run = RunStore(db).load(run_id)
        validate_interval(Interval(run.start_seq, end))
        results = ResultStore(db)
        existing = sealed_result_for(run, end)
        if existing is not None:
            record = results.find_by_run(run_id)
            if record is None or record.result_id != existing or record.end != end:
                raise ValueError('published result is inconsistent with the sealed run')
            return SealOutcome(existing)
        decision = assess_seal(db, run, end)
        selection = decision.selection
        if selection is None:
            return SealOutcome(None, decision.missing)
        revision = RevisionCatalog(db).resolve(run.station, run.revision_id)
        quality = evaluate_shift(selection.frames, revision, run.condition)
        result_id = result_id_for(run_id)
        artifact = ArchiveArtifact(
            result_id, run_id, run.station, selection.interval, run.condition, run.observer,
            run.first_seq, revision, selection.frames, selection.receipts, selection.no_match, quality,
        )
        payload = encode_artifact(artifact)
        results.insert(StoredResult(result_id, run_id, end, payload, artifact_digest(payload)))
        finish_run(db, run, end, result_id)
    return SealOutcome(result_id, release_error=release_observer(portal, run.observer))
