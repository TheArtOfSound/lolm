from datetime import date, timedelta

def daterange(start, end, step_days=1):
    if not isinstance(step_days, int) or isinstance(step_days, bool) or step_days == 0:
        raise ValueError("step_days must be a non-zero integer")
    
    out = []
    current = start
    
    if step_days > 0:
        if start > end:
            return []
        while current <= end:
            out.append(current)
            current += timedelta(days=step_days)
    else:
        if start < end:
            return []
        while current >= end:
            out.append(current)
            current += timedelta(days=step_days)
            
    return out

def business_days(start, end, holidays=()):
    # Business days are Mon-Fri (weekday < 5)
    # The requirement is inclusive range dates (Mon-Fri) that are not in holidays.
    # daterange is inclusive.
    return [d for d in daterange(start, end) if d.weekday() < 5 and d not in holidays]

# Simple verification script
if __name__ == "__main__":
    s = date(2026, 8, 1)
    e = date(2026, 8, 5)
    print(f"daterange({s}, {e}, 1): {daterange(s, e, 1)}")
    
    s = date(2026, 8, 5)
    e = date(2026, 8, 1)
    print(f"daterange({s}, {e}, -1): {daterange(s, e, -1)}")
    
    s = date(2026, 8, 1)
    e = date(2026, 8, 7)
    holidays = (date(2026, 8, 3),)
    print(f"business_days({s}, {e}, {holidays}): {business_days(s, e, holidays)}")
