from solution import compare

def test_basic():
    assert compare("1.0.0", "1.0.1") == -1
    assert compare("1.1.0", "1.0.1") == 1
    assert compare("1.0.0", "1.0.0") == 0

def test_prerelease():
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.0.0-alpha", "1.0.0-alpha.1") == -1
    assert compare("1.0.0-alpha.1", "1.0.0-beta") == -1
    assert compare("1.0.0-beta", "1.0.0-rc.1") == -1
    assert compare("1.0.0-10", "1.0.0-2") == 1

def test_metadata():
    assert compare("1.0.0+20130313144700", "1.0.0+exp.sha.5114f85") == 0

def test_malformed():
    for v in ["1.2", "x.y.z", ""]:
        try:
            compare(v, "1.0.0")
        except ValueError:
            continue
        else:
            raise Exception(f"Failed to raise ValueError for {v}")

if __name__ == "__main__":
    try:
        test_basic()
        test_prerelease()
        test_metadata()
        test_malformed()
        print("All tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")
        exit(1)
