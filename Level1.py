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
    dist_from_start, _ = dijkstra(adj, STARTING_TOWN)
    best_node, best_rate, best_town = None, -1, None

    for node_id, info in NODES.items():
        resource = info["resource"]
        sell_price = RESOURCE_PRICES[resource]["sell_price"]
        rate = (info["yield"] * sell_price) / info["gather-time"]

        dist_from_node, _ = dijkstra(adj, node_id)
        nearest_town = min(
            (t for t in TOWNS if t in dist_from_node),
            key=lambda t: dist_from_node[t]
        )

        if rate > best_rate:
            best_rate = rate
            best_node = node_id
            best_town = nearest_town

    return best_node, best_town, best_rate


def build_actions(adj):
    target_node, sell_town, rate = pick_best_node(adj)
    resource = NODES[target_node]["resource"]
    yld = NODES[target_node]["yield"]
    gather_time = NODES[target_node]["gather-time"]

    path_to_node, d_to_node = shortest_path(adj, STARTING_TOWN, target_node)
    path_to_town, d_to_town = shortest_path(adj, target_node, sell_town)

    overhead = d_to_node + d_to_town + 1
    max_gathers = (TOTAL_TICKS - overhead) // gather_time

    actions = []
    for i in range(len(path_to_node) - 1):
        actions.append({"type": "travel", "destination": path_to_node[i + 1]})
    for _ in range(max_gathers):
        actions.append({"type": "gather"})
    for i in range(len(path_to_town) - 1):
        actions.append({"type": "travel", "destination": path_to_town[i + 1]})
    actions.append({"type": "sell", "item": resource, "quantity": max_gathers * yld})

    print(f"\nBest node: {target_node} ({resource}, {rate:.2f} Enteloot/tick)")
    print(f"Route: {' -> '.join(path_to_node)}, then {' -> '.join(path_to_town)}")
    print(f"Planned gathers: {max_gathers} ({max_gathers * yld} {resource})")

    return actions

def simulate(actions, adj):
    tick = 0
    enteloot = STARTING_ENTELOOT
    location = STARTING_TOWN
    inventory = {}
    items_sold = 0
    action_index = 0

    while tick < TOTAL_TICKS and action_index < len(actions):
        action = actions[action_index]
        action_index += 1
        a_type = action.get("type")

        if a_type == "travel":
            dest = action.get("destination")
            weight = next((w for nb, w in adj.get(location, []) if nb == dest), None)
            if weight is None or tick + weight > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)  # invalid action penalty
                continue
            tick += weight
            location = dest

        elif a_type == "gather":
            if location not in NODES or tick + NODES[location]["gather-time"] > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            info = NODES[location]
            tick += info["gather-time"]
            inventory[info["resource"]] = inventory.get(info["resource"], 0) + info["yield"]

        elif a_type == "sell":
            item, qty = action.get("item"), action.get("quantity")
            if tick + 1 > TOTAL_TICKS or inventory.get(item, 0) < qty:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            tick += 1
            inventory[item] -= qty
            enteloot += qty * RESOURCE_PRICES[item]["sell_price"]
            items_sold += qty

        else:
            tick = min(tick + 1, TOTAL_TICKS)


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


text = f"{'*'*10} STARTING DATA {'*'*10}\nTotal ticks: {TOTAL_TICKS}\nStarting town: {STARTING_TOWN}\nStarting enteloot: {STARTING_ENTELOOT}"
print(text)

graph = build_graph()
action_list = build_actions(graph)
result = simulate(action_list, graph)

held_value = sum(qty * RESOURCE_PRICES[r]["sell_price"] for r, qty in result["passive_resources"].items())
grand_total = result["enteloot"] + result["passive_enteloot"]

print(f"\n{'*'*10} RESULTS {'*'*10}")
print(f"Final tick reached: {result['final_tick']}/{TOTAL_TICKS}")
print(f"Enteloot from active selling: {result['enteloot']}")
print(f"Items sold: {result['items_sold']}")
print(f"Remaining inventory: {result['inventory']}")
print(f"Passive Enteloot generated by all towns: {result['passive_enteloot']}")
print(f"Passive resources accumulated (held, unsold): {result['passive_resources']} (value {held_value})")
print(f"TOTAL ENTELOOT AT END: {grand_total}")
print(f"COMBINED SCORE-RELEVANT TOTAL (Enteloot + held value): {grand_total + held_value}")

with open("level1_output.txt", "w") as out:
    json.dump({"actions": action_list}, out, indent=2)
print(f"\nWrote {len(action_list)} actions to level1_output.txt")