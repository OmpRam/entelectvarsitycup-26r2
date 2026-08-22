import json
import heapq
import math


# building level 2 solution on top of level 1 solution because they have like the same backbone
# loading given data into memory
with open("2.txt") as file, open("resources.json") as resources_file:
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

# level 2 unlocks
RECIPES = resources['recipes']
COMPONENTS = resources['components']
UPGRADES = resources['upgrades']
CRAFT_TIME_BASE = resources['constants']['craft_time_base']
CRAFT_TIME_AFFINITY = resources['constants']['craft_time_affinity']


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

def pick_best_recipe(adj):
    best = None

    for item_name, recipe in RECIPES.items():
        if not recipe.get("sellable"):
            continue
        if len(recipe["inputs"]) != 1:
            continue 

        resource, qty_needed = next(iter(recipe["inputs"].items()))

        candidate_nodes = [(nid, info) for nid, info in NODES.items() if info["resource"] == resource]
        if not candidate_nodes:
            continue
        node_id, node_info = max(candidate_nodes, key=lambda x: x[1]["yield"] / x[1]["gather-time"])

        dist_from_node, _ = dijkstra(adj, node_id)
        affinity_towns = [t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", []) and t in dist_from_node]
        if affinity_towns:
            craft_town = min(affinity_towns, key=lambda t: dist_from_node[t])
            craft_time = CRAFT_TIME_AFFINITY
        else:
            craft_town = min((t for t in TOWNS if t in dist_from_node), key=lambda t: dist_from_node[t])
            craft_time = CRAFT_TIME_BASE

        sell_town = max(TOWNS, key=lambda t: TOWNS[t]["item-rates"].get(item_name, 0))
        sell_price = TOWNS[sell_town]["item-rates"][item_name]

        ticks_per_item = node_info["gather-time"] * (qty_needed / node_info["yield"]) + craft_time
        rate = sell_price / ticks_per_item

        if best is None or rate > best["rate"]:
            best = {
                "item": item_name, "resource": resource, "qty_needed": qty_needed,
                "node": node_id, "node_info": node_info,
                "craft_town": craft_town, "craft_time": craft_time,
                "sell_town": sell_town, "sell_price": sell_price,
                "rate": rate,
            }

    return best


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

    print(f"\n[raw-sell plan] node {target_node} ({resource}, {rate:.2f} Enteloot/tick)")
    print(f"Route: {' -> '.join(path_to_node)}, then {' -> '.join(path_to_town)}")
    print(f"Planned gathers: {max_gathers} ({max_gathers * yld} {resource})")

    return actions

def build_craft_actions(adj, plan):
    resource, qty_needed = plan["resource"], plan["qty_needed"]
    node_info, gather_time, yld = plan["node_info"], plan["node_info"]["gather-time"], plan["node_info"]["yield"]
    craft_time = plan["craft_time"]

    path_to_node, d_to_node = shortest_path(adj, STARTING_TOWN, plan["node"])
    path_to_craft, d_to_craft = shortest_path(adj, plan["node"], plan["craft_town"])
    path_to_sell, d_to_sell = shortest_path(adj, plan["craft_town"], plan["sell_town"])
    overhead = d_to_node + d_to_craft + d_to_sell + 1  # +1 for the final sell action

    G, gather_actions, ticks_used = 0, 0, overhead
    while True:
        resource_needed = (G + 1) * qty_needed
        gather_actions_needed = math.ceil(resource_needed / yld)
        extra_ticks = (gather_actions_needed - gather_actions) * gather_time + craft_time
        if ticks_used + extra_ticks > TOTAL_TICKS:
            break
        ticks_used += extra_ticks
        gather_actions = gather_actions_needed
        G += 1

    actions = []
    for i in range(len(path_to_node) - 1):
        actions.append({"type": "travel", "destination": path_to_node[i + 1]})
    for _ in range(gather_actions):
        actions.append({"type": "gather"})
    for i in range(len(path_to_craft) - 1):
        actions.append({"type": "travel", "destination": path_to_craft[i + 1]})
    if G > 0:
        actions.append({"type": "craft", "item": plan["item"], "quantity": G})
    for i in range(len(path_to_sell) - 1):
        actions.append({"type": "travel", "destination": path_to_sell[i + 1]})
    if G > 0:
        actions.append({"type": "sell", "item": plan["item"], "quantity": G})

    print(f"\n[craft plan] {plan['item']} from {resource} at {plan['node']} "
          f"({plan['rate']:.2f} Enteloot/tick)")
    print(f"Gather {gather_actions}x at {plan['node']} -> craft {G}x at {plan['craft_town']} "
          f"-> sell at {plan['sell_town']} for {plan['sell_price']}/unit")

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
                tick = min(tick + 1, TOTAL_TICKS)
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

        elif a_type == "craft":
            item, qty = action.get("item"), action.get("quantity")
            recipe = RECIPES.get(item) or COMPONENTS.get(item)
            if recipe is None:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            has_affinity = "crafting" in TOWNS.get(location, {}).get("affinities", [])
            craft_time = CRAFT_TIME_AFFINITY if has_affinity else CRAFT_TIME_BASE
            total_ticks_needed = qty * craft_time
            enough_inputs = all(inventory.get(res, 0) >= amt * qty for res, amt in recipe["inputs"].items())
            if not enough_inputs or tick + total_ticks_needed > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            tick += total_ticks_needed
            for res, amt in recipe["inputs"].items():
                inventory[res] -= amt * qty
            inventory[item] = inventory.get(item, 0) + qty

        elif a_type == "sell":
            item, qty = action.get("item"), action.get("quantity")
            if tick + 1 > TOTAL_TICKS or inventory.get(item, 0) < qty:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            tick += 1
            inventory[item] -= qty

            if item in RESOURCE_PRICES:
                price = RESOURCE_PRICES[item]["sell_price"]
            else:
                price = TOWNS.get(location, {}).get("item-rates", {}).get(item, 0)
            enteloot += qty * price
            items_sold += qty

        elif a_type == "build":
            upgrade_name = action.get("upgrade")
            upgrade = None
            for category in UPGRADES.values():
                if upgrade_name in category:
                    upgrade = category[upgrade_name]
                    break
            if upgrade is None:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            enough_components = all(inventory.get(c, 0) >= amt for c, amt in upgrade["components"].items())
            build_time = upgrade["build_time"]
            if not enough_components or enteloot < upgrade["enteloot_cost"] or tick + build_time > TOTAL_TICKS:
                tick = min(tick + 1, TOTAL_TICKS)
                continue
            tick += build_time
            for c, amt in upgrade["components"].items():
                inventory[c] -= amt
            enteloot -= upgrade["enteloot_cost"]

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


text = f"{'-'*60} STARTING DATA {'-'*60}\nTotal ticks: {TOTAL_TICKS}\nStarting town: {STARTING_TOWN}\nStarting enteloot: {STARTING_ENTELOOT}"
print(text)

# worker methods
graph = build_graph()
raw_actions = build_actions(graph)
raw_result = simulate(raw_actions, graph)

recipe_plan = pick_best_recipe(graph)
craft_actions = build_craft_actions(graph, recipe_plan)
craft_result = simulate(craft_actions, graph)

if craft_result["enteloot"] >= raw_result["enteloot"]:
    action_list, result, plan_name = craft_actions, craft_result, f"craft {recipe_plan['item']}"
else:
    action_list, result, plan_name = raw_actions, raw_result, "raw-sell"

held_value = sum(qty * RESOURCE_PRICES[r]["sell_price"] for r, qty in result["passive_resources"].items())
grand_total = result["enteloot"] + result["passive_enteloot"]

print(f"\n\n{'*'*10} RESULTS ({plan_name} plan chosen) {'*'*10}")
print(f"Final tick reached: {result['final_tick']}/{TOTAL_TICKS}")
print(f"Enteloot from active selling: {result['enteloot']}")
print(f"Items sold: {result['items_sold']}")
print(f"Remaining inventory: {result['inventory']}")
print(f"Passive Enteloot generated by all towns: {result['passive_enteloot']}")
print(f"Passive resources accumulated (held, unsold): {result['passive_resources']} (value {held_value})")
print(f"TOTAL ENTELOOT AT END: {grand_total}")
print(f"COMBINED SCORE-RELEVANT TOTAL (Enteloot + held value): {grand_total + held_value}")

with open("level2_output.txt", "w") as out:
    json.dump({"actions": action_list}, out, indent=2)
print(f"\nWrote {len(action_list)} actions to level2_output.txt")