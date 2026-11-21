from sessions.runs import RunStatus, RunStore


def sealed_result_for(run, end):
    if run.status is RunStatus.ACTIVE:
        return None
    if run.sealed_end != end:
        raise ValueError('sealed run has a different cutoff')
    if run.result_id is None:
        raise ValueError('sealed run is missing its result binding')
    return run.result_id


def finish_run(db, run, end, result_id):
    if run.status is not RunStatus.ACTIVE:
        raise RuntimeError('only an active run can be sealed')
    RunStore(db).mark_sealed(run.run_id, end, result_id)


def release_observer(portal, observer):
    try:
        portal.release(observer)
    except Exception as exc:
        return f'{type(exc).__name__}: {exc}'
    return None
