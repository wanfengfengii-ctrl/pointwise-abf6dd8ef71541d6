"""Source-only examples for the observation cutover."""
from evidence.intervals import Interval
from samples.portal_fixture import ESTUARY_REPLAY, ESTUARY_REPLAY_START, STATION, ScriptedPortal


START = ESTUARY_REPLAY_START
CUT = 100
LATE_START = 102
END = 104
OLD = ("salinity",)
NEW = ("turbidity",)
BEFORE_CUT = ESTUARY_REPLAY[:2]
BEFORE_LATE_START = ESTUARY_REPLAY[2:4]
TAIL = ESTUARY_REPLAY[4:]


def new_portal(*, history_limit=2):
    return ScriptedPortal(first_seq=START, history_limit=history_limit)


def show_early_source():
    portal = new_portal()
    old = portal.register(STATION, OLD)
    portal.advance(*BEFORE_CUT)
    new = portal.register(STATION, NEW)
    assert (old.first_seq, new.first_seq) == (START, CUT)
    portal.advance(*BEFORE_LATE_START, *TAIL)
    for seq in (101, 99, 102):
        portal.emit_frame(old.observer, seq)
    old_receipt = portal.emit_receipt(old.observer, START, END).event
    portal.emit_frame(new.observer, 103)
    tail = portal.emit_receipt(new.observer, LATE_START, END).event
    assert tail.interval == Interval(LATE_START, END)
    assert old_receipt.interval == Interval(START, END)
    assert portal.read_history(STATION, NEW, CUT, LATE_START).unavailable == (
        Interval(CUT, LATE_START),
    )
    try:
        portal.emit_receipt(new.observer, CUT, LATE_START)
    except ValueError as exc:
        assert "await delivery" in str(exc)
    else:
        raise AssertionError("portal certified an undelivered matching frame")
    delayed = portal.emit_frame(new.observer, CUT).event
    head = portal.emit_receipt(new.observer, CUT, LATE_START).event
    assert (delayed.seq, delayed.channel, delayed.value) == (100, "turbidity", 8)
    assert head.interval == Interval(CUT, LATE_START)
    print("early observer", new.first_seq, "old proof", old_receipt.interval,
          "new proofs", tail.interval, head.interval, "delayed frame", delayed)


def show_late_source():
    portal = new_portal()
    portal.advance(*BEFORE_CUT, *BEFORE_LATE_START)
    new = portal.register(STATION, NEW)
    assert new.first_seq == LATE_START
    retained = portal.read_history(STATION, NEW, CUT, LATE_START)
    empty = portal.read_history(STATION, NEW, 101, LATE_START)
    assert tuple(frame.seq for frame in retained.frames) == (100,)
    assert tuple(receipt.interval for receipt in retained.receipts) == (Interval(CUT, LATE_START),)
    assert empty.frames == () and tuple(receipt.interval for receipt in empty.receipts) == (
        Interval(101, LATE_START),
    )
    portal.advance(*TAIL)
    expired = portal.read_history(STATION, NEW, CUT, LATE_START)
    assert expired.frames == expired.receipts == expired.pending == ()
    assert expired.unavailable == (Interval(CUT, LATE_START),)
    print("late observer", new.first_seq, "retained frame", retained.frames[0],
          "empty proof", empty.receipts[0].interval, "expired", expired.unavailable)


def main():
    show_early_source()
    show_late_source()


if __name__ == "__main__":
    main()
