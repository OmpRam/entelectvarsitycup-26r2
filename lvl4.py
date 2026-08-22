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

# ==================== GRAPH BUILDING ====================


def build_graph():
    """Build adjacency with standard and fast edges."""
    graph = {}
    for route in ROUTES:
        a, b = route["between"]
        w = route["weight"]
        toll = route.get("toll", 0)
        if a not in graph:
            graph[a] = {}
        if b not in graph:
            graph[b] = {}
        # Store both standard and fast if fast exists
        if b not in graph[a]:
            graph[a][b] = {"standard": w, "fast": None, "toll": 0}
        else:
            # This is a fast route (duplicate edge with toll)
            graph[a][b]["fast"] = w
            graph[a][b]["toll"] = toll
        # Symmetric
        if a not in graph[b]:
            graph[b][a] = {"standard": w, "fast": None, "toll": 0}
        else:
            graph[b][a]["fast"] = w
            graph[b][a]["toll"] = toll
    return graph

# ==================== DIJKSTRA WITH FAST ROUTES ====================


def dijkstra(graph, src, use_fast=False, value_per_tick=1.0):
    """
    Dijkstra with edge cost = time + toll / value_per_tick
    (converts toll to time cost).
    """
    dist = {v: math.inf for v in graph}
    prev = {v: None for v in graph}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, edge in graph[u].items():
            if use_fast and edge["fast"] is not None:
                time = edge["fast"]
                toll = edge["toll"]
            else:
                time = edge["standard"]
                toll = 0
            cost = time + toll / value_per_tick
            nd = d + cost
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def shortest_path(graph, src, dst, use_fast=False, value_per_tick=1.0):
    dist, prev = dijkstra(graph, src, use_fast, value_per_tick)
    if dist[dst] == math.inf:
        return None, None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    # Recalculate actual time and toll for the path
    total_time = 0
    total_toll = 0
    for i in range(len(path)-1):
        a, b = path[i], path[i+1]
        edge = graph[a][b]
        if use_fast and edge["fast"] is not None:
            total_time += edge["fast"]
            total_toll += edge["toll"]
        else:
            total_time += edge["standard"]
    return path, total_time, total_toll

# ==================== VALUE PER TICK ESTIMATION ====================


def estimate_value_per_tick():
    """Estimate max enteloot per tick from gathering/crafting."""
    best = 0
    # Consider raw gathering
    for node_id, info in NODES.items():
        resource = info["resource"]
        sell = RESOURCE_PRICES[resource]["sell_price"]
        value = info["yield"] * sell / info["gather-time"]
        best = max(best, value)
    # Consider crafting (simple single-resource recipes)
    for item, recipe in RECIPES.items():
        if not recipe.get("sellable", False):
            continue
        if len(recipe["inputs"]) != 1:
            continue
        res, qty = next(iter(recipe["inputs"].items()))
        # find best node for that resource
        node_info = max(
            (n for n in NODES.values() if n["resource"] == res),
            key=lambda n: n["yield"] / n["gather-time"],
            default=None
        )
        if node_info is None:
            continue
        # craft time (assume affinity town)
        craft_time = CRAFT_TIME_AFFINITY  # best case
        gather_time_per_unit = node_info["gather-time"] / node_info["yield"]
        total_time_per_item = gather_time_per_unit * qty + craft_time
        # find best sell price
        sell_price = max(TOWNS[t]["item-rates"].get(item, 0) for t in TOWNS)
        if sell_price > 0:
            value = sell_price / total_time_per_item
            best = max(best, value)
    # Also consider multi-resource recipes (approximate)
    for item, recipe in RECIPES.items():
        if not recipe.get("sellable", False):
            continue
        if len(recipe["inputs"]) == 1:
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
        total_time += CRAFT_TIME_AFFINITY  # assume affinity
        sell_price = max(TOWNS[t]["item-rates"].get(item, 0) for t in TOWNS)
        if sell_price > 0:
            value = sell_price / total_time
            best = max(best, value)
    return max(best, 1.0)  # at least 1

# ==================== STATE MANAGEMENT ====================


class State:
    def __init__(self):
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
        self.value_per_tick = estimate_value_per_tick()
        # Keep track of boost timers (not used if we ignore upkeep)
        self.boost_end_tick = {}  # town -> tick when boost expires

    def travel(self, dest, use_fast=False):
        path, time, toll = shortest_path(
            self.graph, self.location, dest, use_fast, self.value_per_tick)
        if path is None:
            return False
        if self.tick + time > TOTAL_TICKS:
            return False
        if self.enteloot < toll:
            return False
        self.tick += time
        self.enteloot -= toll
        self.location = dest
        self.actions.append({"type": "travel", "destination": dest, "fast": use_fast} if use_fast else {
                            "type": "travel", "destination": dest})
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

    def craft(self, item, qty):
        if self.location not in TOWNS:
            return False
        recipe = RECIPES.get(item) or COMPONENTS.get(item)
        if recipe is None:
            return False
        # check ingredients
        for res, amt in recipe["inputs"].items():
            if self.inventory.get(res, 0) < amt * qty:
                return False
        craft_time = recipe.get("craft_time", 2)
        if "crafting" in TOWNS[self.location].get("affinities", []):
            craft_time = 1
        total_time = craft_time * qty
        if self.tick + total_time > TOTAL_TICKS:
            return False
        # consume
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
        # price
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
        # find upgrade def
        upgrade_def = None
        for cat in UPGRADES.values():
            if upgrade_name in cat:
                upgrade_def = cat[upgrade_name]
                break
        if upgrade_def is None:
            return False
        # check prerequisites
        prereq = upgrade_def.get("prerequisite")
        if prereq is not None:
            if prereq == "any_prod":
                prod_upgrades = [
                    "farmhouse", "pier", "fertilised-fields", "quarry", "woodlands", "pottery-house"]
                if not any(u in self.upgrades[self.location] for u in prod_upgrades):
                    return False
            elif prereq == "two_prod":
                prod_upgrades = [
                    "farmhouse", "pier", "fertilised-fields", "quarry", "woodlands", "pottery-house"]
                if sum(1 for u in self.upgrades[self.location] if u in prod_upgrades) < 2:
                    return False
            else:
                if prereq not in self.upgrades[self.location]:
                    return False
        # check components and enteloot
        for comp, amt in upgrade_def["components"].items():
            if self.inventory.get(comp, 0) < amt:
                return False
        if self.enteloot < upgrade_def["enteloot_cost"]:
            return False
        build_time = upgrade_def["build_time"]
        if self.tick + build_time > TOTAL_TICKS:
            return False
        # consume
        for comp, amt in upgrade_def["components"].items():
            self.inventory[comp] -= amt
        self.enteloot -= upgrade_def["enteloot_cost"]
        self.tick += build_time
        self.upgrades[self.location].append(upgrade_name)
        self.actions.append({"type": "build", "upgrade": upgrade_name})
        self._accumulate(build_time)
        # apply production upgrade effect (doubling) will be handled in _accumulate
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
        # check inputs
        for comp, amt in tool_def["inputs"].items():
            if self.inventory.get(comp, 0) < amt:
                return False
        craft_time = 1 if "crafting" in TOWNS[self.location].get(
            "affinities", []) else 2
        if self.tick + craft_time > TOTAL_TICKS:
            return False
        for comp, amt in tool_def["inputs"].items():
            self.inventory[comp] -= amt
        self.tick += craft_time
        self.actions.append(
            {"type": "craft", "item": tool_name, "quantity": 1})
        self._accumulate(craft_time)
        if tool_name == "boots":
            self.has_boots = True
        else:
            self.has_pickaxe = True
        return True

    def upkeep(self):
        """Perform upkeep on current town (boost enteloot)."""
        if self.location not in TOWNS:
            return False
        if self.tick + 5 > TOTAL_TICKS:
            return False
        self.tick += 5
        self.actions.append({"type": "upkeep"})
        # boost effect: double enteloot production for 50 ticks (75 with fire-station)
        duration = 75 if "fire-station" in self.upgrades[self.location] else 50
        self.boost_end_tick[self.location] = self.tick + duration
        # but accumulation during upkeep is already accounted? We'll handle in _accumulate with boost check.
        self._accumulate(5)
        return True

    def _accumulate(self, ticks):
        """Accumulate passive production for all towns for given ticks."""
        for town, info in TOWNS.items():
            # resources
            rate = info["production"]["rate"]
            for res, amt in info["production"]["resources"].items():
                # check production upgrades
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
                    self.town_production[town][res] = self.town_production[town].get(
                        res, 0) + cycles * amt
            # enteloot
            rate = info["enteloot"]["rate"]
            amount = info["enteloot"]["amount"]
            # civic upgrades
            bonus = 0
            for u in self.upgrades[town]:
                if u == "rec-center":
                    bonus += 0.2
                elif u == "school":
                    bonus += 0.5
                elif u == "library":
                    bonus += 0.5
                elif u == "police-station":
                    # reduce rate by 2 (min 1)
                    rate = max(1, rate - 2)
            amount = int(amount * (1 + bonus))
            # check if town is boosted
            if town in self.boost_end_tick and self.boost_end_tick[town] > self.tick:
                # boost active: double amount
                amount *= 2
            cycles = ticks // rate
            if cycles > 0:
                self.town_enteloot[town] = self.town_enteloot.get(
                    town, 0) + cycles * amount

    def flush_inventory(self):
        """Sell all inventory at nearest town."""
        # find nearest town
        nearest = None
        min_dist = float('inf')
        for town in TOWNS:
            path, time, toll = shortest_path(
                self.graph, self.location, town, False, self.value_per_tick)
            if path is not None and time < min_dist:
                min_dist = time
                nearest = town
        if nearest is None:
            return
        self.travel(nearest)
        # sell everything
        for item in list(self.inventory.keys()):
            qty = self.inventory.get(item, 0)
            if qty > 0:
                self.sell(item, qty)

    def get_final_enteloot(self):
        total = self.enteloot
        for town, amt in self.town_enteloot.items():
            total += amt
        return total

# ==================== PLANNING FUNCTIONS ====================


def gather_resource(state, resource, amount):
    """Gather specified amount of resource from best node."""
    # find best node for that resource considering distance and yield
    candidates = []
    for nid, info in NODES.items():
        if info["resource"] == resource:
            path, time, toll = shortest_path(
                state.graph, state.location, nid, False, state.value_per_tick)
            if path is None:
                continue
            # value per tick of gathering this resource
            value = info["yield"] * \
                RESOURCE_PRICES[resource]["sell_price"] / info["gather-time"]
            candidates.append((nid, time, info, value))
    if not candidates:
        return False
    # pick node with best value per tick considering travel overhead
    # simple: pick node with highest value per tick
    candidates.sort(key=lambda x: x[3], reverse=True)
    best_node = candidates[0][0]
    # travel there
    if not state.travel(best_node):
        return False
    # gather until we have enough
    gathered = 0
    while state.inventory.get(resource, 0) < amount:
        if not state.gather():
            break
    return True


def craft_component(state, component, qty):
    """Craft a component, gathering resources if needed."""
    recipe = COMPONENTS.get(component)
    if recipe is None:
        return False
    # ensure we have ingredients
    for res, amt in recipe["inputs"].items():
        needed = amt * qty - state.inventory.get(res, 0)
        if needed > 0:
            gather_resource(state, res, needed)
    # travel to affinity town for crafting
    affinity_town = next(
        (t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", [])), None)
    if affinity_town is not None:
        state.travel(affinity_town)
    return state.craft(component, qty)


def build_upgrade(state, upgrade_name, town=None):
    """Build an upgrade, crafting components first."""
    # find upgrade def
    upgrade_def = None
    for cat in UPGRADES.values():
        if upgrade_name in cat:
            upgrade_def = cat[upgrade_name]
            break
    if upgrade_def is None:
        return False
    # craft all components
    for comp, amt in upgrade_def["components"].items():
        if comp in COMPONENTS:
            # craft it
            craft_component(state, comp, amt)
        else:
            # it's a resource, gather
            gather_resource(state, comp, amt)
    # travel to target town if specified, else current
    if town is not None and state.location != town:
        state.travel(town)
    return state.build(upgrade_name)


def build_civic_chain(state, town):
    """Build civic upgrades in a town in order."""
    chain = ["rec-center", "fire-station",
             "school", "police-station", "library"]
    for upgrade in chain:
        if upgrade in state.upgrades[town]:
            continue
        # build it
        if build_upgrade(state, upgrade, town):
            pass
        else:
            break

# ==================== MAIN SOLVER ====================


def solve():
    state = State()
    print(f"Value per tick estimate: {state.value_per_tick:.2f}")

    # ---- PHASE 0: Gather ore for tools and police-station ----
    print("Phase 0: Gathering ore")
    # 4 iron-fittings for tools (2 each) + 2 for police-station (2 each)
    total_ore_needed = 12
    gather_resource(state, "ore", total_ore_needed)

    # ---- PHASE 1: Craft tools ----
    print("Phase 1: Crafting tools")
    # craft iron-fittings
    for _ in range(4):  # need 4 for boots+pickaxe
        craft_component(state, "iron-fittings", 1)
    # craft planks and rope for tools
    craft_component(state, "planks", 2)  # for pickaxe
    craft_component(state, "rope", 2)    # for boots
    # also need wood/ore for more fittings? already have.
    # travel to affinity town
    affinity_town = next(
        (t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", [])), "Demacia")
    state.travel(affinity_town)
    # craft boots
    state.craft_tool("boots")
    # craft pickaxe
    state.craft_tool("pickaxe")

    # ---- PHASE 2: Build production upgrades in multiple towns ----
    print("Phase 2: Building production upgrades")
    production_upgrades = [
        "farmhouse", "pier", "fertilised-fields", "quarry", "woodlands", "pottery-house"]
    # pick towns: we want to spread across towns with high resource production and affinity
    # For simplicity, we'll pick first 6 towns with affinity or high production
    target_towns = []
    for town in TOWNS:
        if "crafting" in TOWNS[town].get("affinities", []):
            target_towns.append(town)
    # if not enough, add others
    if len(target_towns) < 6:
        for town in TOWNS:
            if town not in target_towns:
                target_towns.append(town)
                if len(target_towns) == 6:
                    break
    # build each upgrade in a different town
    for i, upgrade in enumerate(production_upgrades):
        town = target_towns[i % len(target_towns)]
        build_upgrade(state, upgrade, town)

    # ---- PHASE 3: Build civic upgrades in best towns ----
    print("Phase 3: Building civic upgrades")
    # find towns with most production upgrades (at least 1 for rec-center, 2 for fire-station)
    # We'll pick towns that have many production upgrades and high enteloot.
    # For simplicity, we'll pick the first town that has at least 2 prod upgrades.
    civic_town = None
    for town, upgrades in state.upgrades.items():
        prod_count = sum(1 for u in upgrades if u in production_upgrades)
        if prod_count >= 2:
            civic_town = town
            break
    if civic_town is None:
        civic_town = target_towns[0]
    # build civic chain
    build_civic_chain(state, civic_town)
    # also maybe build in another town to spread development? but limited time.

    # ---- PHASE 4: Craft and sell high-value goods ----
    print("Phase 4: Crafting and selling goods")
    # We'll iterate over towns, find best item to craft, gather resources, craft, sell.
    # To avoid excessive actions, we'll do a limited number of cycles.
    # For each town, we'll craft the item that sells best there.
    for town, info in TOWNS.items():
        if "item-rates" not in info:
            continue
        # find best item
        item_rates = info["item-rates"]
        best_item = max(item_rates, key=item_rates.get)
        best_price = item_rates[best_item]
        # check if recipe exists
        if best_item not in RECIPES:
            continue
        recipe = RECIPES[best_item]
        # We'll craft 5 of them
        qty = 5
        # gather ingredients
        for res, amt in recipe["inputs"].items():
            needed = amt * qty - state.inventory.get(res, 0)
            if needed > 0:
                gather_resource(state, res, needed)
        # travel to affinity town for crafting (if not already)
        affinity_town = next(
            (t for t in TOWNS if "crafting" in TOWNS[t].get("affinities", [])), None)
        if affinity_town is not None and state.location != affinity_town:
            state.travel(affinity_town)
        # craft
        if state.craft(best_item, qty):
            # travel to selling town
            state.travel(town)
            state.sell(best_item, qty)
        else:
            # if craft fails, maybe gather more
            pass

    # ---- PHASE 5: Final cleanup ----
    print("Phase 5: Final flush")
    # collect all passive resources into inventory
    for town, resources_prod in state.town_production.items():
        for res, amt in resources_prod.items():
            if amt > 0:
                state.inventory[res] = state.inventory.get(res, 0) + amt
                state.town_production[town][res] = 0
    state.flush_inventory()

    # ---- OUTPUT ----
    final_enteloot = state.get_final_enteloot()
    print(f"Final Enteloot: {final_enteloot}")
    print(f"Total actions: {len(state.actions)}")
    print(f"Ticks used: {state.tick}")

    with open("level4_output.txt", "w") as f:
        json.dump({"actions": state.actions}, f, indent=2)
    print("Output written to level4_output.txt")


if __name__ == "__main__":
    solve()
