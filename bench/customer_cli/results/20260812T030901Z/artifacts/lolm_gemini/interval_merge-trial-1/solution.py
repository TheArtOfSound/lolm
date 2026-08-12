def merge(intervals):
    if not intervals:
        return []

    # Validate intervals
    for start, end in intervals:
        if start > end:
            raise ValueError(f"Invalid interval: [{start}, {end}] (start > end)")

    # Sort based on start time
    sorted_intervals = sorted(intervals, key=lambda x: x[0])

    merged = []
    for interval in sorted_intervals:
        if not merged:
            merged.append(interval)
        else:
            last_start, last_end = merged[-1]
            current_start, current_end = interval

            if current_start <= last_end:
                # Merge
                merged[-1] = [last_start, max(last_end, current_end)]
            else:
                # No overlap
                merged.append(interval)
    return merged
