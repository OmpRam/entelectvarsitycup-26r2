import json
import heapq
import math
from typing import Dict, List, Tuple, Optional

# ==================== LOAD DATA ====================
with open("4.txt") as f:
    data = json.load(f)
with open("resources.json") as f:
    resources = json.load(f)

TOTAL_TICKS = data['run']['total_ticks']
STARTING_TOWN = data['run']['starting_town']
STARTING_ENTELOOT = data['run']['starting_enteloot']

TOWNS = data['towns']
NODES = data['nodes']
ROUTES = data['routes']

RESOURCE_PRICES = resources['resources']
RECIPES = resources['recipes']
COMPONENTS = resources['components']
UPGRADES = resources['upgrades']
CRAFT_TIME_BASE = resources['constants']['craft_time_base']
CRAFT_TIME_AFFINITY = resources['constants']['craft_time_affinity']

# ==================== GRAPH ====================
def build_graph():
    graph = {}
    for route in ROUTES:
        a, b = route["between"]
        w = route["weight"]
        toll = route.get("toll", 0)
        if a not in graph:
            graph[a] = {}
        if b not in graph:
            graph[b] = {}
        if b not in graph[a]:
            graph[a][b] = {"standard": w, "fast": None, "toll": 0}
        else:
            graph[a][b]["fast"] = w
            graph[a][b]["toll"] = toll
        if a not in graph[b]:
            graph[b][a] = {"standard": w, "fast": None, "toll": 0}
        else:
            graph[b][a]["fast"] = w
            graph[b][a]["toll"] = toll
    return graph

def dijkstra_time_toll(graph, src):
    dist = {v: math.inf for v in graph}
    prev = {v: None for v in graph}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, edge in graph[u].items():
            # Always use fast if available (tolls are worth it for time savings)
            if edge["fast"] is not None:
                time = edge["fast"]
                toll = edge["toll"]
            else:
                time = edge["standard"]
                toll = 0
            nd = d + time
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev

def get_path_time_toll(graph, src, dst):
    dist, prev = dijkstra_time_toll(graph, src)
    if dist[dst] == math.inf:
        return None, None, None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    total_time = 0
    total_toll = 0
    for i in range(len(path)-1):
        a, b = path[i], path[i+1]
        edge = graph[a][b]
        if edge["fast"] is not None:
            total_time += edge["fast"]
            total_toll += edge["toll"]
        else:
            total_time += edge["standard"]
    return path, total_time, total_toll

# Precompute shortest paths between all towns and nodes
def precompute_distances(graph):
    all_vertices = list(graph.keys())
    time_matrix = {v: {} for v in all_vertices}
    toll_matrix = {v: {} for v in all_vertices}
    for src in all_vertices:
        dist, prev = dijkstra_time_toll(graph, src)
        for dst in all_vertices:
            if dist[dst] == math.inf:
                continue
            time_matrix[src][dst] = dist[dst]
            # reconstruct path for toll
            path = [dst]
            while path[-1] != src:
                path.append(prev[path[-1]])
            path.reverse()
            toll = 0
            for i in range(len(path)-1):
                a, b = path[i], path[i+1]
                edge = graph[a][b]
                if edge["fast"] is not None:
                    toll += edge["toll"]
            toll_matrix[src][dst] = toll
    return time_matrix, toll_matrix

# ==================== STATE ====================
class State:
    def __init__(self, time_matrix, toll_matrix):
        self.location = STARTING_TOWN
        self.enteloot = STARTING_ENTELOOT
        self.inventory = {}
        self.tick = 0
        self.actions = []
        self.has_boots = False
        self.has_pickaxe = False
        self.upgrades = {town: [] for town in TOWNS}
        self.town_production = {town: {} for town in TOWNS}
        for town, info in TOWNS.items():
            for res, amt in info["production"]["resources"].items():
                self.town_production[town][res] = 0
        self.town_enteloot = {town: 0 for town in TOWNS}
        self.graph = build_graph()
        self.time_matrix = time_matrix
        self.toll_matrix = toll_matrix
        self.affinity_towns = [t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", [])]
        self.prod_upgrades = ["farmhouse", "pier", "fertilised-fields", "quarry", "woodlands", "pottery-house"]
        self.civic_chain = ["rec-center", "fire-station", "school", "police-station", "library"]

    def travel(self, dest):
        if dest not in self.time_matrix[self.location]:
            return False
        time = self.time_matrix[self.location][dest]
        toll = self.toll_matrix[self.location][dest]
        if self.tick + time > TOTAL_TICKS:
            return False
        if self.enteloot < toll:
            return False
        self.tick += time
        self.enteloot -= toll
        self.location = dest
        self.actions.append({"type": "travel", "destination": dest})
        self._accumulate(time)
        return True

    def gather(self):
        if self.location not in NODES:
            return False
        info = NODES[self.location]
        gtime = info["gather-time"]
        if self.has_pickaxe:
            gtime = max(1, gtime - 1)
        if self.tick + gtime > TOTAL_TICKS:
            return False
        self.tick += gtime
        res = info["resource"]
        y = info["yield"]
        self.inventory[res] = self.inventory.get(res, 0) + y
        self.actions.append({"type": "gather"})
        self._accumulate(gtime)
        return True

    def gather_until(self, resource, amount):
        """Gather until we have at least amount. Returns True if successful."""
        start_amount = self.inventory.get(resource, 0)
        gathered = start_amount
        while gathered < amount:
            # Find best node: max yield / (gather_time + travel_time*0.1)
            best_node = None
            best_score = -1
            for nid, info in NODES.items():
                if info["resource"] != resource:
                    continue
                if nid not in self.time_matrix[self.location]:
                    continue
                travel_time = self.time_matrix[self.location][nid]
                score = info["yield"] / (info["gather-time"] + travel_time * 0.05)
                if score > best_score:
                    best_score = score
                    best_node = nid
            if best_node is None:
                return False
            self.travel(best_node)
            # Gather until we either have enough or run out of time
            attempts = 0
            while self.inventory.get(resource, 0) < amount and self.tick < TOTAL_TICKS - 10:
                if not self.gather():
                    break
                attempts += 1
            if self.tick >= TOTAL_TICKS - 10:
                break
        return self.inventory.get(resource, 0) >= amount

    def craft(self, item, qty):
        if self.location not in TOWNS:
            return False
        recipe = RECIPES.get(item) or COMPONENTS.get(item)
        if recipe is None:
            return False
        for res, amt in recipe["inputs"].items():
            if self.inventory.get(res, 0) < amt * qty:
                return False
        craft_time = recipe.get("craft_time", 2)
        if "crafting" in TOWNS[self.location].get("affinities", []):
            craft_time = 1
        total_time = craft_time * qty
        if self.tick + total_time > TOTAL_TICKS:
            return False
        for res, amt in recipe["inputs"].items():
            self.inventory[res] -= amt * qty
        self.inventory[item] = self.inventory.get(item, 0) + qty
        self.tick += total_time
        self.actions.append({"type": "craft", "item": item, "quantity": qty})
        self._accumulate(total_time)
        return True

    def sell(self, item, qty):
        if self.location not in TOWNS:
            return False
        if self.inventory.get(item, 0) < qty:
            return False
        if self.tick + 1 > TOTAL_TICKS:
            return False
        if item in RESOURCE_PRICES:
            price = RESOURCE_PRICES[item]["sell_price"]
        else:
            price = TOWNS[self.location]["item-rates"].get(item, 0)
        if price == 0:
            return False
        self.inventory[item] -= qty
        self.enteloot += price * qty
        self.tick += 1
        self.actions.append({"type": "sell", "item": item, "quantity": qty})
        self._accumulate(1)
        return True

    def build(self, upgrade_name):
        if self.location not in TOWNS:
            return False
        upgrade_def = None
        for cat in UPGRADES.values():
            if upgrade_name in cat:
                upgrade_def = cat[upgrade_name]
                break
        if upgrade_def is None:
            return False
        prereq = upgrade_def.get("prerequisite")
        if prereq is not None:
            if prereq == "any_prod":
                if not any(u in self.upgrades[self.location] for u in self.prod_upgrades):
                    return False
            elif prereq == "two_prod":
                if sum(1 for u in self.upgrades[self.location] if u in self.prod_upgrades) < 2:
                    return False
            else:
                if prereq not in self.upgrades[self.location]:
                    return False
        for comp, amt in upgrade_def["components"].items():
            if self.inventory.get(comp, 0) < amt:
                return False
        if self.enteloot < upgrade_def["enteloot_cost"]:
            return False
        build_time = upgrade_def["build_time"]
        if self.tick + build_time > TOTAL_TICKS:
            return False
        for comp, amt in upgrade_def["components"].items():
            self.inventory[comp] -= amt
        self.enteloot -= upgrade_def["enteloot_cost"]
        self.tick += build_time
        self.upgrades[self.location].append(upgrade_name)
        self.actions.append({"type": "build", "upgrade": upgrade_name})
        self._accumulate(build_time)
        return True

    def craft_tool(self, tool_name):
        if self.location not in TOWNS:
            return False
        tool_def = resources["tools"].get(tool_name)
        if tool_def is None:
            return False
        if tool_name == "boots" and self.has_boots:
            return False
        if tool_name == "pickaxe" and self.has_pickaxe:
            return False
        for comp, amt in tool_def["inputs"].items():
            if self.inventory.get(comp, 0) < amt:
                return False
        craft_time = 1 if "crafting" in TOWNS[self.location].get("affinities", []) else 2
        if self.tick + craft_time > TOTAL_TICKS:
            return False
        for comp, amt in tool_def["inputs"].items():
            self.inventory[comp] -= amt
        self.tick += craft_time
        self.actions.append({"type": "craft", "item": tool_name, "quantity": 1})
        self._accumulate(craft_time)
        if tool_name == "boots":
            self.has_boots = True
        else:
            self.has_pickaxe = True
        return True

    def _accumulate(self, ticks):
        for town, info in TOWNS.items():
            rate = info["production"]["rate"]
            for res, amt in info["production"]["resources"].items():
                prod_upgrade_map = {
                    "farmhouse": "sheep",
                    "pier": "fish",
                    "fertilised-fields": "wheat",
                    "quarry": "stone",
                    "woodlands": "wood",
                    "pottery-house": "clay"
                }
                for u in self.upgrades[town]:
                    if u in prod_upgrade_map and prod_upgrade_map[u] == res:
                        amt *= 2
                cycles = ticks // rate
                if cycles > 0:
                    self.town_production[town][res] = self.town_production[town].get(res, 0) + cycles * amt
            rate = info["enteloot"]["rate"]
            amount = info["enteloot"]["amount"]
            bonus = 0
            for u in self.upgrades[town]:
                if u == "rec-center":
                    bonus += 0.2
                elif u == "school":
                    bonus += 0.5
                elif u == "library":
                    bonus += 0.5
                elif u == "police-station":
                    rate = max(1, rate - 2)
            amount = int(amount * (1 + bonus))
            cycles = ticks // rate
            if cycles > 0:
                self.town_enteloot[town] = self.town_enteloot.get(town, 0) + cycles * amount

    def flush(self):
        for town, resources_prod in self.town_production.items():
            for res, amt in resources_prod.items():
                if amt > 0:
                    self.inventory[res] = self.inventory.get(res, 0) + amt
                    self.town_production[town][res] = 0
        nearest = None
        min_dist = float('inf')
        for town in TOWNS:
            if town in self.time_matrix[self.location]:
                if self.time_matrix[self.location][town] < min_dist:
                    min_dist = self.time_matrix[self.location][town]
                    nearest = town
        if nearest is not None:
            self.travel(nearest)
        for item in list(self.inventory.keys()):
            qty = self.inventory.get(item, 0)
            if qty > 0:
                self.sell(item, qty)

    def get_total_enteloot(self):
        return self.enteloot + sum(self.town_enteloot.values())

# ==================== BUILD HELPERS ====================
def craft_component(state, component, qty):
    """Craft a component, gathering resources if needed."""
    recipe = COMPONENTS.get(component)
    if recipe is None:
        return False
    for res, amt in recipe["inputs"].items():
        needed = amt * qty - state.inventory.get(res, 0)
        if needed > 0:
            state.gather_until(res, needed)
    # Travel to affinity town for crafting
    if state.affinity_towns:
        best_aff = min(state.affinity_towns, key=lambda t: state.time_matrix[state.location][t] if t in state.time_matrix[state.location] else float('inf'))
        if state.location != best_aff:
            state.travel(best_aff)
    return state.craft(component, qty)

def build_production_upgrades(state):
    """Build production upgrades in as many towns as possible."""
    print("Building production upgrades...")
    
    # Sort towns by potential: affinity first, then enteloot rate
    town_priority = []
    for town in TOWNS:
        info = TOWNS[town]
        priority = 0
        if "crafting" in info.get("affinities", []):
            priority += 100
        # Higher enteloot rate = better for civic upgrades later
        priority += info["enteloot"]["amount"] / info["enteloot"]["rate"]
        town_priority.append((priority, town))
    town_priority.sort(reverse=True)
    
    upgrades_built = 0
    for _, town in town_priority:
        # Build each production upgrade in this town
        for upgrade in state.prod_upgrades:
            if upgrade in state.upgrades[town]:
                continue
            # Travel to town
            if state.location != town:
                state.travel(town)
            
            # Craft all components
            upgrade_def = None
            for cat in UPGRADES.values():
                if upgrade in cat:
                    upgrade_def = cat[upgrade]
                    break
            if upgrade_def is None:
                continue
            
            # Gather/craft components
            success = True
            for comp, amt in upgrade_def["components"].items():
                if comp in COMPONENTS:
                    if not craft_component(state, comp, amt):
                        success = False
                        break
                else:
                    if not state.gather_until(comp, amt):
                        success = False
                        break
            if not success:
                continue
            
            # Build
            if state.build(upgrade):
                upgrades_built += 1
                print(f"  Built {upgrade} in {town} (total: {upgrades_built})")
                # Stop after building in enough towns (we want spread, not all in one town)
                if upgrades_built >= 15:
                    return

def build_civic_upgrades(state):
    """Build civic upgrades in towns with production upgrades."""
    print("Building civic upgrades...")
    
    # Find towns with production upgrades
    candidates = []
    for town, upgrades in state.upgrades.items():
        prod_count = sum(1 for u in upgrades if u in state.prod_upgrades)
        if prod_count >= 1:
            candidates.append((prod_count, town))
    candidates.sort(reverse=True)
    
    civic_built = 0
    for _, town in candidates[:5]:  # Top 5 towns
        if state.location != town:
            state.travel(town)
        for upgrade in state.civic_chain:
            if upgrade in state.upgrades[town]:
                continue
            # Check prerequisites
            upgrade_def = None
            for cat in UPGRADES.values():
                if upgrade in cat:
                    upgrade_def = cat[upgrade]
                    break
            if upgrade_def is None:
                continue
            
            # Check if we can afford/build it
            # Craft components
            success = True
            for comp, amt in upgrade_def["components"].items():
                if comp in COMPONENTS:
                    if not craft_component(state, comp, amt):
                        success = False
                        break
                else:
                    if not state.gather_until(comp, amt):
                        success = False
                        break
            if not success:
                continue
            if state.build(upgrade):
                civic_built += 1
                print(f"  Built {upgrade} in {town}")

def estimate_value_per_tick():
    """Estimate best value per tick from crafting."""
    best = 20.0
    for item, recipe in RECIPES.items():
        if not recipe.get("sellable", False):
            continue
        total_time = 0
        for res, qty in recipe["inputs"].items():
            node_info = max(
                (n for n in NODES.values() if n["resource"] == res),
                key=lambda n: n["yield"] / n["gather-time"],
                default=None
            )
            if node_info is None:
                total_time = None
                break
            total_time += (node_info["gather-time"] / node_info["yield"]) * qty
        if total_time is None:
            continue
        total_time += CRAFT_TIME_AFFINITY
        sell_price = max(TOWNS[t]["item-rates"].get(item, 0) for t in TOWNS)
        if sell_price > 0:
            best = max(best, sell_price / total_time)
    return best

# ==================== MAIN ====================
def solve():
    print("=== ULTIMATE LEVEL 4 SOLVER ===")
    print(f"Total ticks: {TOTAL_TICKS}")
    
    # Precompute distances
    print("Building graph...")
    graph = build_graph()
    print("Precomputing distances...")
    time_matrix, toll_matrix = precompute_distances(graph)
    
    state = State(time_matrix, toll_matrix)
    
    # ---- PHASE 0: Gather ore for tools ----
    print("Phase 0: Gathering ore")
    state.gather_until("ore", 20)  # 4 fittings for tools + 6 for police-stations
    
    # ---- PHASE 1: Craft tools ----
    print("Phase 1: Crafting tools")
    for _ in range(4):
        craft_component(state, "iron-fittings", 1)
    craft_component(state, "planks", 4)
    craft_component(state, "rope", 4)
    if state.affinity_towns:
        best_aff = min(state.affinity_towns, key=lambda t: state.time_matrix[state.location][t] if t in state.time_matrix[state.location] else float('inf'))
        state.travel(best_aff)
    state.craft_tool("boots")
    state.craft_tool("pickaxe")
    
    # ---- PHASE 2: Production upgrades in multiple towns ----
    print("\nPhase 2: Production upgrades")
    build_production_upgrades(state)
    
    # ---- PHASE 3: Civic upgrades ----
    print("\nPhase 3: Civic upgrades")
    build_civic_upgrades(state)
    
    # ---- PHASE 4: MASSIVE CRAFTING ----
    print("\nPhase 4: Massive crafting loop")
    
    # Precompute best items per town
    best_items = {}
    for town, info in TOWNS.items():
        if "item-rates" not in info:
            continue
        best_item = max(info["item-rates"], key=info["item-rates"].get)
        if best_item in RECIPES:
            best_items[town] = (best_item, info["item-rates"][best_item])
    
    sorted_towns = sorted(best_items.items(), key=lambda x: x[1][1], reverse=True)[:15]
    
    BATCH = 25  # Craft 25 at a time for efficiency
    
    iteration = 0
    while state.tick < TOTAL_TICKS - 300:
        for town, (item, price) in sorted_towns:
            if state.tick >= TOTAL_TICKS - 300:
                break
            
            # Travel to selling town
            if state.location != town:
                state.travel(town)
            
            recipe = RECIPES[item]
            
            # Gather resources for batch
            for res, amt in recipe["inputs"].items():
                needed = amt * BATCH
                if state.inventory.get(res, 0) < needed:
                    state.gather_until(res, needed - state.inventory.get(res, 0))
            
            # Travel to affinity town for crafting
            if state.affinity_towns:
                best_aff = min(state.affinity_towns, key=lambda t: state.time_matrix[state.location][t] if t in state.time_matrix[state.location] else float('inf'))
                if state.location != best_aff:
                    state.travel(best_aff)
            
            # Craft
            if not state.craft(item, BATCH):
                # Retry with more resources
                for res, amt in recipe["inputs"].items():
                    needed = amt * BATCH
                    if state.inventory.get(res, 0) < needed:
                        state.gather_until(res, needed - state.inventory.get(res, 0))
                if not state.craft(item, BATCH):
                    continue
            
            # Travel back to selling town
            if state.location != town:
                state.travel(town)
            
            state.sell(item, BATCH)
            
            iteration += 1
            if iteration % 50 == 0:
                print(f"  Tick {state.tick}, Enteloot: {state.enteloot}, Upgrades: {sum(len(u) for u in state.upgrades.values())}")
    
    # ---- PHASE 5: Final flush ----
    print("\nPhase 5: Final flush")
    state.flush()
    
    # ---- RESULTS ----
    final = state.get_total_enteloot()
    total_upgrades = sum(len(u) for u in state.upgrades.values())
    towns_with_upgrades = sum(1 for u in state.upgrades.values() if u)
    
    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"Final Enteloot: {final:,}")
    print(f"Ticks used: {state.tick:,}")
    print(f"Total actions: {len(state.actions):,}")
    print(f"Towns with upgrades: {towns_with_upgrades}")
    print(f"Total upgrades built: {total_upgrades}")
    print(f"Tools: Boots={state.has_boots}, Pickaxe={state.has_pickaxe}")
    print("="*60)
    
    with open("level4_output.txt", "w") as f:
        json.dump({"actions": state.actions}, f, indent=2)
    print("Output written to level4_output.txt")

if __name__ == "__main__":
    solve()