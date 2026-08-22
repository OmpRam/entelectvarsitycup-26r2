import json
import heapq
import math

# loading given data into memory
with open("1.txt") as file, open("resources.json") as resources_file:
    data = json.load(file)
    resources = json.load(resources_file)

# initial data
TOTAL_TICKS = data['run']['total_ticks']
STARTING_TOWN = data['run']['starting_town']
STARTING_ENTELOOT = data['run']['starting_enteloot']

# json
TOWNS = data['towns']
NODES = data['nodes']
ROUTES = data['routes']
RESOURCE_PRICES = resources['resources']  

# utils method
def build_graph():
    adj = {}
    for route in ROUTES:
        a, b = route["between"]
        w = route["weight"]
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))
    return adj

def dijkstra(adj, src):
    dist = {v: math.inf for v in adj}
    prev = {}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev

def shortest_path(adj, src, dst):
    dist, prev = dijkstra(adj, src)
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    return list(reversed(path)), dist[dst]

def pick_best_node(adj):
    """Find the node with best profit per tick including travel overhead"""
    dist_from_start, _ = dijkstra(adj, STARTING_TOWN)
    best_node, best_value, best_town, best_travel_time = None, -1, None, 0

    for node_id, info in NODES.items():
        resource = info["resource"]
        sell_price = RESOURCE_PRICES[resource]["sell_price"]
        # Value per gather
        value_per_gather = info["yield"] * sell_price
        
        # Calculate travel time to nearest town (for selling)
        dist_from_node, _ = dijkstra(adj, node_id)
        
        # Find nearest town
        nearest_town = None
        min_dist = float('inf')
        for town in TOWNS:
            if town in dist_from_node:
                if dist_from_node[town] < min_dist:
                    min_dist = dist_from_node[town]
                    nearest_town = town
        
        if nearest_town is None:
            continue
            
        # Total travel time: start -> node -> nearest_town + 1 tick for selling
        travel_to_node = dist_from_start.get(node_id, float('inf'))
        if travel_to_node == float('inf'):
            continue
            
        total_travel = travel_to_node + min_dist + 1  # +1 for sell action
        
        # How many times can we gather in the remaining time?
        gather_time = info["gather-time"]
        remaining_ticks = TOTAL_TICKS - total_travel
        if remaining_ticks <= 0:
            continue
            
        max_gathers = remaining_ticks // gather_time
        if max_gathers <= 0:
            continue
            
        total_value = max_gathers * value_per_gather
        value_per_tick = total_value / total_travel
        
        if value_per_tick > best_value:
            best_value = value_per_tick
            best_node = node_id
            best_town = nearest_town
            best_travel_time = total_travel
            
    return best_node, best_town, best_value, best_travel_time

def build_actions(adj):
    target_node, sell_town, rate, total_travel = pick_best_node(adj)
    
    if target_node is None:
        print("No valid node found!")
        return []
        
    resource = NODES[target_node]["resource"]
    yld = NODES[target_node]["yield"]
    gather_time = NODES[target_node]["gather-time"]


    path_to_node, d_to_node = shortest_path(adj, STARTING_TOWN, target_node)
    path_to_town, d_to_town = shortest_path(adj, target_node, sell_town)


    overhead = d_to_node + d_to_town + 1 
    max_gathers = (TOTAL_TICKS - overhead) // gather_time
    
    print(f"\nBest node: {target_node} ({resource}, {rate:.2f} Enteloot/tick)")
    print(f"Route to node: {' -> '.join(path_to_node)}")
    print(f"Route to town: {' -> '.join(path_to_town)}")
    print(f"Travel overhead: {overhead} ticks")
    print(f"Planned gathers: {max_gathers} ({max_gathers * yld} {resource})")

    # build actions
    actions = []
    
    for i in range(len(path_to_node) - 1):
        actions.append({"type": "travel", "destination": path_to_node[i + 1]})
    
    for _ in range(max_gathers):
        actions.append({"type": "gather"})
    
    # travel to sell town
    for i in range(len(path_to_town) - 1):
        actions.append({"type": "travel", "destination": path_to_town[i + 1]})
    
    actions.append({"type": "sell", "item": resource, "quantity": max_gathers * yld})

    return actions

def simulate(actions, adj):
    tick = 0
    enteloot = STARTING_ENTELOOT
    location = STARTING_TOWN
    inventory = {}
    items_sold = 0
    action_index = 0

    print(f"\n=== SIMULATION START ===")
    print(f"Total ticks: {TOTAL_TICKS}")
    
    while tick < TOTAL_TICKS and action_index < len(actions):
        action = actions[action_index]
        action_index += 1
        a_type = action.get("type")

        if a_type == "travel":
            dest = action.get("destination")
            # Find the edge weight
            weight = None
            for nb, w in adj.get(location, []):
                if nb == dest:
                    weight = w
                    break
                    
            if weight is None or tick + weight > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                print(f"  Invalid travel to {dest} at tick {tick}")
                continue
                
            tick += weight
            location = dest
            # print(f"  Traveled to {dest} at tick {tick}")

        elif a_type == "gather":
            if location not in NODES:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
                
            info = NODES[location]
            if tick + info["gather-time"] > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
                
            tick += info["gather-time"]
            resource = info["resource"]
            inventory[resource] = inventory.get(resource, 0) + info["yield"]

        elif a_type == "sell":
            item = action.get("item")
            qty = action.get("quantity")
            
            if tick + 1 > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
                
            if inventory.get(item, 0) < qty:
                qty = inventory.get(item, 0)
                if qty == 0:
                    tick = min(tick + 1, TOTAL_TICKS)
                    continue
                    
            tick += 1
            price = RESOURCE_PRICES[item]["sell_price"]
            inventory[item] = inventory.get(item, 0) - qty
            enteloot += qty * price
            items_sold += qty
            print(f"  Sold {qty} {item} for {qty * price} Enteloot at tick {tick}")

        else:
            tick = min(tick + 1, TOTAL_TICKS)
            print(f"  Unknown action type: {a_type} at tick {tick}")

    print(f"Simulation ended at tick {tick}")
    
    passive_resources = {}
    passive_enteloot = 0
    
    for town_name, town_info in TOWNS.items():
        cycles = tick // town_info["enteloot"]["rate"]
        passive_enteloot += cycles * town_info["enteloot"]["amount"]
        
        prod_cycles = tick // town_info["production"]["rate"]
        for res, amt in town_info["production"]["resources"].items():
            passive_resources[res] = passive_resources.get(res, 0) + prod_cycles * amt

    return {
        "final_tick": tick,
        "enteloot": enteloot,
        "items_sold": items_sold,
        "inventory": inventory,
        "passive_resources": passive_resources,
        "passive_enteloot": passive_enteloot,
    }

def main():
    print(f"{'*'*10} STARTING DATA {'*'*10}")
    print(f"Total ticks: {TOTAL_TICKS}")
    print(f"Starting town: {STARTING_TOWN}")
    print(f"Starting enteloot: {STARTING_ENTELOOT}")
    print(f"Towns: {list(TOWNS.keys())}")
    print(f"Nodes: {list(NODES.keys())}")

    graph = build_graph()
    action_list = build_actions(graph)
    if not action_list:
        print("No actions generated!")
        return
        
    result = simulate(action_list, graph)


    held_value = 0
    for resource, qty in result["passive_resources"].items():
        if resource in RESOURCE_PRICES:
            held_value += qty * RESOURCE_PRICES[resource]["sell_price"]
            
    for resource, qty in result["inventory"].items():
        if resource in RESOURCE_PRICES and qty > 0:
            held_value += qty * RESOURCE_PRICES[resource]["sell_price"]

    grand_total = result["enteloot"] + result["passive_enteloot"]

    print(f"\n{'*'*10} RESULTS {'*'*10}")
    print(f"Final tick reached: {result['final_tick']}/{TOTAL_TICKS}")
    print(f"Enteloot from active selling: {result['enteloot']}")
    print(f"Items sold: {result['items_sold']}")
    print(f"Remaining inventory: {result['inventory']}")
    print(f"Passive Enteloot generated by all towns: {result['passive_enteloot']}")
    print(f"Passive resources accumulated: {result['passive_resources']} (value {held_value})")
    print(f"TOTAL ENTELOOT AT END: {grand_total}")
    print(f"COMBINED SCORE-RELEVANT TOTAL (Enteloot + held value): {grand_total + held_value}")

    with open("level1_output.txt", "w") as out:
        json.dump({"actions": action_list}, out, indent=2)
    print(f"\nWrote {len(action_list)} actions to level1_output.txt")

if __name__ == "__main__":
    main()