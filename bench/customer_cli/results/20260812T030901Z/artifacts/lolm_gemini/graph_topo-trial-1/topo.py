class CycleError(ValueError):
    def __init__(self, cycle):
        super().__init__(f"Cycle detected: {cycle}")
        self.cycle = cycle

def toposort(graph):
    # Collect all unique nodes
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)
    
    # Adjacency list: B -> [A] (B is a dependency of A)
    adj = {node: [] for node in nodes}
    in_degree = {node: 0 for node in nodes}
    
    for node, deps in graph.items():
        for dep in deps:
            adj[dep].append(node)
            in_degree[node] += 1
            
    # Kahn's algorithm with priority queue (heap) for deterministic order
    import heapq
    queue = [node for node in nodes if in_degree[node] == 0]
    heapq.heapify(queue)
    
    result = []
    while queue:
        u = heapq.heappop(queue)
        result.append(u)
        
        for v in sorted(adj[u]):  # Sort neighbors to ensure determinism
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(queue, v)
                
    if len(result) != len(nodes):
        # Cycle detected, find the cycle
        # We perform a DFS to find the cycle
        
        visited = {} # node -> path_index
        path = []
        
        def find_cycle(u):
            visited[u] = len(path)
            path.append(u)
            for v in sorted(adj[u]):
                if v in visited:
                    idx = visited[v]
                    return path[idx:] + [v]
                if v not in processed:
                    cycle = find_cycle(v)
                    if cycle:
                        return cycle
            path.pop()
            del visited[u]
            processed.add(u)
            return None

        processed = set()
        # Ensure we check nodes in a sorted order
        for node in sorted(nodes):
            if node not in processed:
                cycle = find_cycle(node)
                if cycle:
                    raise CycleError(cycle)
        
    return result
