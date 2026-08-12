"""Retry helper."""
import time
from functools import wraps


def retry(attempts=3, on=(Exception,), sleep=time.sleep, delay=0):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            wrapper.calls = 0
            last_exception = None
            for index in range(attempts):
                wrapper.calls += 1
                try:
                    return fn(*args, **kwargs)
                except on as e:
                    last_exception = e
                    if index < attempts - 1:
                        sleep(delay * (2 ** index))
            raise last_exception
        return wrapper

    return decorator


def test_retry():
    # Test successful call
    @retry(attempts=3)
    def success():
        return "ok"

    assert success() == "ok"
    assert success.calls == 1

    # Test retry on specific exception
    @retry(attempts=3, on=(ValueError,), delay=0.01)
    def fail_twice_succeed():
        if fail_twice_succeed.calls < 3:
            raise ValueError("fail")
        return "ok"

    assert fail_twice_succeed() == "ok"
    assert fail_twice_succeed.calls == 3

    # Test re-raise final exception
    @retry(attempts=2, on=(ValueError,), delay=0.01)
    def always_fail():
        raise ValueError("error")

    try:
        always_fail()
    except ValueError as e:
        assert str(e) == "error"
    assert always_fail.calls == 2

    # Test propagation of other exceptions
    @retry(attempts=3, on=(ValueError,), delay=0.01)
    def raise_other():
        raise TypeError("other")

    try:
        raise_other()
    except TypeError:
        pass
    assert raise_other.calls == 1

    # Test ValueError for attempts < 1
    try:
        @retry(attempts=0)
        def bad(): pass
    except ValueError:
        pass
    else:
        assert False, "Should have raised ValueError"

    print("All tests passed!")


if __name__ == "__main__":
    test_retry()
