from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Interval:
    start: int
    end: int


def validate_interval(interval, *, allow_empty=True):
    if not isinstance(interval, Interval):
        raise ValueError('expected an interval')
    if (type(interval.start) is not int or type(interval.end) is not int
            or interval.start < 0 or interval.end < interval.start):
        raise ValueError(f'invalid interval {interval!r}')
    if not allow_empty and interval.start == interval.end:
        raise ValueError('receipt interval must be nonempty')
    return interval


def intersect_interval(left, right):
    validate_interval(left)
    validate_interval(right)
    start = max(left.start, right.start)
    end = min(left.end, right.end)
    return Interval(start, end) if start < end else None


def normalize_intervals(intervals):
    merged = []
    for item in sorted(validate_interval(interval) for interval in intervals):
        if item.start == item.end:
            continue
        if merged and item.start <= merged[-1].end:
            last = merged[-1]
            merged[-1] = Interval(last.start, max(last.end, item.end))
        else:
            merged.append(item)
    return tuple(merged)


def subtract_intervals(intervals, exclusions):
    bases = normalize_intervals(intervals)
    cuts = normalize_intervals(exclusions)
    remaining = []
    index = 0
    for base in bases:
        cursor = base.start
        while index < len(cuts) and cuts[index].end <= cursor:
            index += 1
        while index < len(cuts) and cuts[index].start < base.end:
            cut = cuts[index]
            if cursor < cut.start:
                remaining.append(Interval(cursor, cut.start))
            cursor = max(cursor, cut.end)
            if cursor >= base.end:
                break
            index += 1
        if cursor < base.end:
            remaining.append(Interval(cursor, base.end))
    return tuple(remaining)
