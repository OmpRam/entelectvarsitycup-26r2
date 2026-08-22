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

def dijkstra(graph, src):
    dist = {v: math.inf for v in graph}
    prev = {v: None for v in graph}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, edge in graph[u].items():
            if edge["fast"] is not None:
                time = edge["fast"]
            else:
                time = edge["standard"]
            nd = d + time
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev

def compute_distances(graph):
    town_names = list(TOWNS.keys())
    node_names = list(NODES.keys())
    
    town_dist = {t: {} for t in town_names}
    town_toll = {t: {} for t in town_names}
    
    for src in town_names:
        dist, prev = dijkstra(graph, src)
        for dst in town_names:
            if dst in dist and dist[dst] != math.inf:
                town_dist[src][dst] = dist[dst]
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
                town_toll[src][dst] = toll
    
    town_to_node = {t: {} for t in town_names}
    town_to_node_toll = {t: {} for t in town_names}
    
    for src in town_names:
        dist, prev = dijkstra(graph, src)
        for dst in node_names:
            if dst in dist and dist[dst] != math.inf:
                town_to_node[src][dst] = dist[dst]
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
                town_to_node_toll[src][dst] = toll
    
    node_to_town = {n: {} for n in node_names}
    node_to_town_toll = {n: {} for n in node_names}
    node_dist = {n: {} for n in node_names}
    
    for src in node_names:
        dist, prev = dijkstra(graph, src)
        for dst in node_names:
            if dst in dist and dist[dst] != math.inf:
                node_dist[src][dst] = dist[dst]
        for dst in town_names:
            if dst in dist and dist[dst] != math.inf:
                node_to_town[src][dst] = dist[dst]
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
                node_to_town_toll[src][dst] = toll
    
    return town_dist, town_toll, town_to_node, town_to_node_toll, node_to_town, node_to_town_toll, node_dist

# ==================== STATE ====================
class State:
    def __init__(self, town_dist, town_toll, town_to_node, town_to_node_toll, node_to_town, node_to_town_toll, node_dist):
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
        self.town_dist = town_dist
        self.town_toll = town_toll
        self.town_to_node = town_to_node
        self.town_to_node_toll = town_to_node_toll
        self.node_to_town = node_to_town
        self.node_to_town_toll = node_to_town_toll
        self.node_dist = node_dist
        self.affinity_towns = [t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", [])]
        self.prod_upgrades = ["farmhouse", "pier", "fertilised-fields", "quarry", "woodlands", "pottery-house"]
        self.civic_chain = ["rec-center", "fire-station", "school", "police-station", "library"]

    def travel_town(self, dest):
        if self.location in self.town_dist and dest in self.town_dist[self.location]:
            time = self.town_dist[self.location][dest]
            toll = self.town_toll[self.location][dest]
        elif self.location in self.node_to_town and dest in self.node_to_town[self.location]:
            time = self.node_to_town[self.location][dest]
            toll = self.node_to_town_toll[self.location][dest]
        else:
            return False
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

    def travel_node(self, dest):
        if self.location in self.town_to_node and dest in self.town_to_node[self.location]:
            time = self.town_to_node[self.location][dest]
            toll = self.town_to_node_toll[self.location][dest]
        elif self.location in self.node_dist and dest in self.node_dist[self.location]:
            time = self.node_dist[self.location][dest]
            toll = 0
        else:
            return False
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

    def travel(self, dest):
        if dest in TOWNS:
            return self.travel_town(dest)
        elif dest in NODES:
            return self.travel_node(dest)
        return False

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
        """Gather until we have at least amount."""
        if self.inventory.get(resource, 0) >= amount:
            return True
        
        # Try up to 10 times to find a good node
        for attempt in range(10):
            best_node = None
            best_score = -1
            
            for nid, info in NODES.items():
                if info["resource"] != resource:
                    continue
                if self.location in self.town_to_node and nid in self.town_to_node[self.location]:
                    travel_time = self.town_to_node[self.location][nid]
                elif self.location in self.node_dist and nid in self.node_dist[self.location]:
                    travel_time = self.node_dist[self.location][nid]
                else:
                    continue
                # Amortize travel over 20 gathers
                amortized_travel = travel_time / 20
                score = info["yield"] / (info["gather-time"] + amortized_travel)
                if score > best_score:
                    best_score = score
                    best_node = nid
            
            if best_node is None:
                return False
            
            self.travel(best_node)
            
            # Gather as much as possible
            gather_count = 0
            while self.inventory.get(resource, 0) < amount and self.tick < TOTAL_TICKS - 10:
                if not self.gather():
                    break
                gather_count += 1
                if gather_count > 50:  # Avoid infinite loops
                    break
            
            if self.inventory.get(resource, 0) >= amount:
                return True
        
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
            if self.location in self.town_dist and town in self.town_dist[self.location]:
                d = self.town_dist[self.location][town]
                if d < min_dist:
                    min_dist = d
                    nearest = town
            elif self.location in self.node_to_town and town in self.node_to_town[self.location]:
                d = self.node_to_town[self.location][town]
                if d < min_dist:
                    min_dist = d
                    nearest = town
        if nearest is not None:
            self.travel(nearest)
        for item in list(self.inventory.keys()):
            qty = self.inventory.get(item, 0)
            if qty > 0:
                self.sell(item, qty)

    def get_total_enteloot(self):
        return self.enteloot + sum(self.town_enteloot.values())

# ==================== HELPERS ====================
def craft_component(state, component, qty):
    recipe = COMPONENTS.get(component)
    if recipe is None:
        return False
    for res, amt in recipe["inputs"].items():
        needed = amt * qty - state.inventory.get(res, 0)
        if needed > 0:
            state.gather_until(res, needed)
    if state.affinity_towns:
        best_aff = min(state.affinity_towns, key=lambda t: state.town_dist[state.location][t] if state.location in state.town_dist and t in state.town_dist[state.location] else float('inf'))
        if state.location != best_aff:
            state.travel(best_aff)
    return state.craft(component, qty)

def build_production_upgrades(state):
    print("Building production upgrades...")
    town_priority = []
    for town in TOWNS:
        info = TOWNS[town]
        priority = 0
        if "crafting" in info.get("affinities", []):
            priority += 100
        priority += info["enteloot"]["amount"] / info["enteloot"]["rate"]
        town_priority.append((priority, town))
    town_priority.sort(reverse=True)
    
    upgrades_built = 0
    max_upgrades = 18  # Build in as many towns as possible
    for _, town in town_priority:
        if upgrades_built >= max_upgrades:
            break
        for upgrade in state.prod_upgrades:
            if upgrade in state.upgrades[town]:
                continue
            if state.location != town:
                state.travel(town)
            upgrade_def = None
            for cat in UPGRADES.values():
                if upgrade in cat:
                    upgrade_def = cat[upgrade]
                    break
            if upgrade_def is None:
                continue
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
                upgrades_built += 1
                print(f"  Built {upgrade} in {town} ({upgrades_built}/{max_upgrades})")

def build_civic_upgrades(state):
    print("Building civic upgrades...")
    candidates = []
    for town, upgrades in state.upgrades.items():
        prod_count = sum(1 for u in upgrades if u in state.prod_upgrades)
        if prod_count >= 1:
            candidates.append((prod_count, town))
    candidates.sort(reverse=True)
    
    civic_built = 0
    for _, town in candidates[:8]:  # Build in up to 8 towns
        if state.location != town:
            state.travel(town)
        for upgrade in state.civic_chain:
            if upgrade in state.upgrades[town]:
                continue
            upgrade_def = None
            for cat in UPGRADES.values():
                if upgrade in cat:
                    upgrade_def = cat[upgrade]
                    break
            if upgrade_def is None:
                continue
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
                print(f"  Built {upgrade} in {town} ({civic_built} civic upgrades)")

# ==================== MAIN ====================
def solve():
    print("=== ULTIMATE LEVEL 4 SOLVER ===")
    print(f"Total ticks: {TOTAL_TICKS}")
    print(f"Towns: {len(TOWNS)}, Nodes: {len(NODES)}")
    
    print("Building graph...")
    graph = build_graph()
    
    print("Computing distances (this may take a moment)...")
    town_dist, town_toll, town_to_node, town_to_node_toll, node_to_town, node_to_town_toll, node_dist = compute_distances(graph)
    print(f"  Town-to-town distances: {len(town_dist)} towns")
    print(f"  Town-to-node distances: {len(town_to_node)} towns")
    
    state = State(town_dist, town_toll, town_to_node, town_to_node_toll, node_to_town, node_to_town_toll, node_dist)
    
    # ---- PHASE 0: Gather ore ----
    print("\nPhase 0: Gathering ore")
    state.gather_until("ore", 25)  # More ore for multiple police stations
    print(f"  Ore: {state.inventory.get('ore', 0)}")
    
    # ---- PHASE 1: Craft tools ----
    print("\nPhase 1: Crafting tools")
    for i in range(4):
        craft_component(state, "iron-fittings", 1)
    craft_component(state, "planks", 4)
    craft_component(state, "rope", 4)
    if state.affinity_towns:
        best_aff = min(state.affinity_towns, key=lambda t: state.town_dist[state.location][t] if state.location in state.town_dist and t in state.town_dist[state.location] else float('inf'))
        state.travel(best_aff)
    state.craft_tool("boots")
    state.craft_tool("pickaxe")
    print("  Tools crafted!")
    
    # ---- PHASE 2: Production upgrades ----
    print("\nPhase 2: Production upgrades")
    build_production_upgrades(state)
    
    # ---- PHASE 3: Civic upgrades ----
    print("\nPhase 3: Civic upgrades")
    build_civic_upgrades(state)
    
    # ---- PHASE 4: MASSIVE CRAFTING ----
    print("\nPhase 4: Massive crafting loop")
    
    best_items = {}
    for town, info in TOWNS.items():
        if "item-rates" not in info:
            continue
        best_item = max(info["item-rates"], key=info["item-rates"].get)
        if best_item in RECIPES and best_item not in COMPONENTS:
            best_items[town] = (best_item, info["item-rates"][best_item])
    
    sorted_towns = sorted(best_items.items(), key=lambda x: x[1][1], reverse=True)[:15]
    print(f"  Using {len(sorted_towns)} towns for crafting")
    
    BATCH = 40  # Larger batch for efficiency
    
    iteration = 0
    last_report = 0
    
    print(f"  Starting craft loop at tick {state.tick}")
    
    while state.tick < TOTAL_TICKS - 500:
        for town, (item, price) in sorted_towns:
            if state.tick >= TOTAL_TICKS - 500:
                break
            
            # Travel to selling town
            if state.location != town:
                state.travel(town)
            
            recipe = RECIPES[item]
            
            # Gather resources
            for res, amt in recipe["inputs"].items():
                needed = amt * BATCH
                if state.inventory.get(res, 0) < needed:
                    state.gather_until(res, needed - state.inventory.get(res, 0))
            
            # Travel to affinity town for crafting
            if state.affinity_towns:
                best_aff = min(state.affinity_towns, key=lambda t: state.town_dist[state.location][t] if state.location in state.town_dist and t in state.town_dist[state.location] else float('inf'))
                if state.location != best_aff:
                    state.travel(best_aff)
            
            # Try crafting
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
            if iteration - last_report >= 10:
                last_report = iteration
                total_upgrades = sum(len(u) for u in state.upgrades.values())
                towns_with_upgrades = sum(1 for u in state.upgrades.values() if u)
                print(f"  Tick {state.tick:>6}: Enteloot={state.enteloot:>12,}, Upgrades={total_upgrades:>2} in {towns_with_upgrades:>2} towns, Loop={iteration:>3}")
    
    # ---- PHASE 5: Final flush ----
    print("\nPhase 5: Final flush")
    state.flush()
    
    # ---- RESULTS ----
    final = state.get_total_enteloot()
    total_upgrades = sum(len(u) for u in state.upgrades.values())
    towns_with_upgrades = sum(1 for u in state.upgrades.values() if u)
    
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print(f"Final Enteloot: {final:,}")
    print(f"Ticks used: {state.tick:,} / {TOTAL_TICKS:,}")
    print(f"Total actions: {len(state.actions):,}")
    print(f"Towns with upgrades: {towns_with_upgrades}")
    print(f"Total upgrades built: {total_upgrades}")
    print(f"Tools: Boots={state.has_boots}, Pickaxe={state.has_pickaxe}")
    print("="*70)
    
    with open("level4_output.txt", "w") as f:
        json.dump({"actions": state.actions}, f, indent=2)
    print("Output written to level4_output.txt")

if __name__ == "__main__":
    solve()