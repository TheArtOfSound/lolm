import time
import functools

def retry(attempts=3, on=(Exception,), sleep=time.sleep, delay=0):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            wrapper.calls = 0
            for i in range(attempts):
                wrapper.calls += 1
                try:
                    return fn(*args, **kwargs)
                except on:
                    if i == attempts - 1:
                        raise
                    sleep(delay * (2 ** i))
        return wrapper
    return decorator
