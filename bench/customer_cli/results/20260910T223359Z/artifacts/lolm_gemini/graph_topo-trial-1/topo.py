class CycleError(ValueError):
    def __init__(self, cycle):
        super().__init__(f"Cycle detected: {cycle}")
        self.cycle = cycle

def toposort(graph):
    # Normalize: include all nodes, even those only appearing as dependencies
    all_nodes = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)
    
    # Build a dependency graph: node -> nodes that depend on it
    # But the prompt says graph[node] = [dependencies]
    # So we need to reverse this to find what nodes are "ready" (no outstanding dependencies)
    
    # Let's track dependencies for each node
    # in_degree: how many dependencies a node has that haven't been processed
    # dependents: mapping from dependency to nodes that depend on it
    
    in_degree = {node: 0 for node in all_nodes}
    dependents = {node: [] for node in all_nodes}
    
    for node, deps in graph.items():
        for dep in deps:
            dependents[dep].append(node)
            in_degree[node] += 1
            
    # Kahn's algorithm with deterministic choice (smallest ready node)
    import heapq
    ready = [node for node in all_nodes if in_degree[node] == 0]
    heapq.heapify(ready)
    
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        
        for dependent in dependents[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(ready, dependent)
                
    if len(result) < len(all_nodes):
        # Cycle detected. Find the cycle for the error.
        # This is more complex, but we can find any cycle using DFS
        def find_cycle():
            visited = {} # node -> path_index
            stack = []
            
            def dfs(u, path):
                visited[u] = len(path)
                stack.append(u)
                for v in graph.get(u, []):
                    if v in visited:
                        cycle = stack[visited[v]:] + [v]
                        return cycle
                    if v not in visited:
                        res = dfs(v, path + [u])
                        if res: return res
                stack.pop()
                del visited[u]
                return None
            
            for node in sorted(all_nodes):
                if node not in visited:
                    res = dfs(node, [])
                    if res: return res
            return None

        cycle = find_cycle()
        raise CycleError(cycle)
        
    return result
