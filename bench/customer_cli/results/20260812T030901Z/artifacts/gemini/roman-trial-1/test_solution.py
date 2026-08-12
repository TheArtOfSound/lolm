from solution import to_roman, from_roman

def test():
    # 1. Round trip for 1-3999
    for i in range(1, 4000):
        roman = to_roman(i)
        assert from_roman(roman) == i, f"Failed round-trip for {i}"

    # 2. Test invalid inputs for to_roman
    for invalid in [0, 4000, 1.5, "I"]:
        try:
            to_roman(invalid)
            assert False, f"Should have raised ValueError for {invalid}"
        except ValueError:
            pass

    # 3. Test invalid inputs for from_roman
    for invalid in ['IIII', 'VV', 'IC', '', 'ABC', 'MIM']:
        try:
            from_roman(invalid)
            # MIM is invalid (should be CM XCVIII for 998, etc. - wait, actually M is 1000, M-I+M is 1999? no. MIM is not a valid form.)
            # Wait, check if 'MIM' is invalid.
            # 1999 is MCMXCIX. MIM is not standard.
            # My regex should catch these.
            assert False, f"Should have raised ValueError for {invalid}"
        except ValueError:
            pass
    
    print("All tests passed!")

if __name__ == "__main__":
    test()
