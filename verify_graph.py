import json

def verify_graph():
    with open("newmarket_graph.json", "r") as f:
        graph = json.load(f)
        
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    
    print(f"Graph loaded:")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Edges: {len(edges)}")
    
    # 1. Check node uniqueness
    node_ids = set()
    for n in nodes:
        nid = n["id"]
        if nid in node_ids:
            print(f"  Warning: Duplicate node ID: {nid}")
        node_ids.add(nid)
        
    print(f"  Unique Node IDs: {len(node_ids)}")
    
    # 2. Build adjacency list (undirected)
    adj = {nid: set() for nid in node_ids}
    
    missing_nodes = set()
    for edge in edges:
        s = edge["source"]
        t = edge["target"]
        
        if s not in adj:
            missing_nodes.add(s)
            continue
        if t not in adj:
            missing_nodes.add(t)
            continue
            
        adj[s].add(t)
        adj[t].add(s)
        
    if missing_nodes:
        print(f"  Error: {len(missing_nodes)} edge endpoints are missing from the nodes list!")
        print("  Missing endpoints:", list(missing_nodes)[:10])
    else:
        print("  All edge endpoints are valid nodes.")
        
    # 3. Analyze node degrees
    isolated_nodes = []
    for nid, neighbors in adj.items():
        if len(neighbors) == 0:
            # Check what type of node it is
            node_obj = next(n for n in nodes if n["id"] == nid)
            isolated_nodes.append(node_obj)
            
    print(f"  Isolated nodes: {len(isolated_nodes)}")
    if isolated_nodes:
        print("  Sample isolated nodes (first 10):")
        for inode in isolated_nodes[:10]:
            print(f"    - ID: {inode['id']}, Type: {inode['type']}, Level: {inode['level']}, Name: {inode.get('name')}")
            
    # 4. Check connected components
    visited = set()
    components = []
    
    for nid in node_ids:
        if nid in visited:
            continue
            
        # Run BFS/DFS to find all reachable nodes
        comp = []
        queue = [nid]
        visited.add(nid)
        
        while queue:
            curr = queue.pop(0)
            comp.append(curr)
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(comp)
        
    print(f"  Number of connected components: {len(components)}")
    components.sort(key=len, reverse=True)
    for idx, c in enumerate(components):
        print(f"    Component {idx+1}: {len(c)} nodes")
        if len(c) < 10:
            # Print details of very small components
            for n_id in c:
                n_obj = next(n for n in nodes if n["id"] == n_id)
                print(f"      - ID: {n_obj['id']}, Type: {n_obj['type']}, Level: {n_obj['level']}, Name: {n_obj.get('name')}")
                
    # 5. Summary
    if len(components) == 1:
        print("\nSuccess: The graph is fully connected! Any node can reach any other node.")
    else:
        print(f"\nWarning: The graph has {len(components)} components. Agents in smaller components might be isolated.")

if __name__ == "__main__":
    verify_graph()
