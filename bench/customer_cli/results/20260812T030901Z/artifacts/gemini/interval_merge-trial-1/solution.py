def merge(intervals):
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = []

    for interval in sorted_intervals:
        start, end = interval
        if start > end:
            raise ValueError(f"Invalid interval: start {start} > end {end}")

        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    return merged
