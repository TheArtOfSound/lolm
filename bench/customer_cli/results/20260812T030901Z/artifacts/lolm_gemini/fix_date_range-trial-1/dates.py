from datetime import date, timedelta

def daterange(start, end, step_days=1):
    if not isinstance(step_days, int) or isinstance(step_days, bool) or step_days == 0:
        raise ValueError("step_days must be a non-zero integer")
    
    out = []
    current = start
    
    if step_days > 0:
        while current <= end:
            out.append(current)
            current += timedelta(days=step_days)
    else:
        while current >= end:
            out.append(current)
            current += timedelta(days=step_days)
            
    return out

def business_days(start, end, holidays=()):
    if start > end:
        return []
    dates = daterange(start, end, step_days=1)
    return [d for d in dates if d.weekday() < 5 and d not in holidays]
