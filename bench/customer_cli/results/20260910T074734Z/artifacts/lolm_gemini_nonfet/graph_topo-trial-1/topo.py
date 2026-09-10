class CycleError(ValueError):
    def __init__(self, message, cycle):
        super().__init__(message)
        self.cycle = cycle

def toposort(graph):
    # Collect all nodes
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)
    
    # Build adj list: node -> nodes that depend on it
    # We want dependencies first, so if A depends on B (A: [B]), 
    # B should come before A in topological sort.
    # The requirement: "graph maps a node to the list of nodes it depends on, so dependencies come first in the output."
    # So if A depends on B, order: B, ..., A.
    # This means an edge from B to A.
    
    adj = {node: [] for node in nodes}
    in_degree = {node: 0 for node in nodes}
    
    for node, deps in graph.items():
        for dep in deps:
            adj[dep].append(node)
            in_degree[node] += 1
            
    # Kahn's algorithm
    import heapq
    queue = [n for n in nodes if in_degree[n] == 0]
    heapq.heapify(queue)
    
    result = []
    while queue:
        u = heapq.heappop(queue)
        result.append(u)
        
        for v in sorted(adj[u]):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(queue, v)
                
    if len(result) < len(nodes):
        # Cycle detected, find it
        # Need to find any cycle in the graph.
        # Graph here: nodes with edges adj[u] -> v
        visited = {} # node -> path_index
        path = []
        
        def find_cycle(u, p):
            visited[u] = len(path)
            path.append(u)
            for v in sorted(adj[u]):
                if v in visited:
                    cycle = path[visited[v]:] + [v]
                    return cycle
                if v not in processed:
                    c = find_cycle(v, path)
                    if c: return c
            path.pop()
            processed.add(u)
            
        processed = set()
        for node in sorted(nodes):
            if node not in processed:
                cycle = find_cycle(node, [])
                if cycle:
                    raise CycleError("Cycle detected", cycle)
                    
    return result
