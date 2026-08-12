from topo import toposort, CycleError

def test_basic():
    # A depends on B, B depends on C
    # C -> B -> A
    graph = {'A': ['B'], 'B': ['C']}
    assert toposort(graph) == ['C', 'B', 'A']
    
def test_empty():
    assert toposort({}) == []

def test_multiple_deps():
    # A -> [B, C], B -> [D], C -> [D]
    # D -> B, D -> C, B -> A, C -> A
    # Order: D, B, C, A or D, C, B, A
    # Deterministic: D, B, C, A
    graph = {'A': ['B', 'C'], 'B': ['D'], 'C': ['D']}
    assert toposort(graph) == ['D', 'B', 'C', 'A']

def test_cycle():
    # A -> B -> A
    graph = {'A': ['B'], 'B': ['A']}
    try:
        toposort(graph)
    except CycleError as e:
        assert e.cycle[0] == e.cycle[-1]
        assert len(e.cycle) >= 2
        # Check that it's a valid path in the graph
        # A depends on B (A: [B]) -> B -> A (B: [A])
        # A depends on B, B depends on A
        # My toposort builds adjacency for dependencies:
        # A: [B] means B -> A
        # B: [A] means A -> B
        # So A -> B -> A is valid.
    else:
        assert False, "Should have raised CycleError"

def test_cycle_complex():
    # A -> B -> C -> A
    graph = {'A': ['B'], 'B': ['C'], 'C': ['A']}
    try:
        toposort(graph)
    except CycleError as e:
        print(f"Cycle: {e.cycle}")
        assert e.cycle[0] == e.cycle[-1]
    else:
        assert False, "Should have raised CycleError"

def test_node_only_in_deps():
    # B depends on C
    graph = {'B': ['C']}
    # Expected: C, B
    assert toposort(graph) == ['C', 'B']

if __name__ == "__main__":
    test_basic()
    test_empty()
    test_multiple_deps()
    test_cycle()
    test_cycle_complex()
    test_node_only_in_deps()
    print("All tests passed!")
