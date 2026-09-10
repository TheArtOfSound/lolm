class CycleError(ValueError):
    def __init__(self, cycle):
        super().__init__(f"Cycle detected: {cycle}")
        self.cycle = cycle

def toposort(graph):
    # nodes are keys and all values in the graph
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)
    
    # build the graph in terms of who depends on whom
    # input: node -> dependencies (nodes that must come before)
    # output: node -> nodes that depend on it
    adj = {node: [] for node in nodes}
    in_degree = {node: 0 for node in nodes}
    
    for node, deps in graph.items():
        for dep in deps:
            adj[dep].append(node)
            in_degree[node] += 1
            
    # Kahn's algorithm with deterministic tie-breaking
    import heapq
    queue = [node for node in nodes if in_degree[node] == 0]
    heapq.heapify(queue)
    
    result = []
    while queue:
        u = heapq.heappop(queue)
        result.append(u)
        # Sort neighbors for deterministic processing
        for v in sorted(adj[u]):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                heapq.heappush(queue, v)
                
    if len(result) < len(nodes):
        # Find cycle using DFS
        visited = {} # node -> state: 0=unvisited, 1=visiting, 2=visited
        parent = {}
        
        def find_cycle(u):
            visited[u] = 1
            # Sort neighbors for deterministic cycle finding
            for v in sorted(adj.get(u, [])):
                if visited.get(v, 0) == 1:
                    # Found cycle
                    cycle = [v, u]
                    curr = u
                    while curr != v:
                        curr = parent[curr]
                        cycle.append(curr)
                    return cycle[::-1]
                if visited.get(v, 0) == 0:
                    parent[v] = u
                    res = find_cycle(v)
                    if res: return res
            visited[u] = 2
            return None

        # Try starting DFS from all nodes to ensure we cover all components
        for node in sorted(list(nodes)):
            if visited.get(node, 0) == 0:
                cycle = find_cycle(node)
                if cycle:
                    raise CycleError(cycle)
                    
    return result
