import json
import heapq
import math
from copy import deepcopy
from collections import defaultdict

with open("2.txt", encoding="utf-8") as file:
    data = json.load(file)

with open("resources.json", encoding="utf-8") as file:
    resources = json.load(file)

TOTAL_TICKS = data["run"]["total_ticks"]
STARTING_TOWN = data["run"]["starting_town"]
STARTING_ENTELOOT = data["run"]["starting_enteloot"]

TOWNS = data["towns"]
NODES = data["nodes"]
ROUTES = data["routes"]

RESOURCE_PRICES = resources["resources"]
RECIPES = resources["recipes"]
COMPONENTS = resources["components"]
UPGRADES = resources["upgrades"]

CRAFT_TIME_BASE = resources["constants"]["craft_time_base"]
CRAFT_TIME_AFFINITY = resources["constants"]["craft_time_affinity"]

INVALID_ACTION_TICKS = resources["constants"]["invalid_action_ticks"]

ALL_UPGRADES = {}

for category_name, category in UPGRADES.items():
    for upgrade_name, upgrade in category.items():
        ALL_UPGRADES[upgrade_name] = {
            **upgrade,
            "category": category_name
        }

PRODUCTION_UPGRADES = set(UPGRADES["production"].keys())
CIVIC_UPGRADES = set(UPGRADES["civic"].keys())

def build_graph():
    """
    Level 2 only uses normal routes.

    Duplicate routes can exist. Keeping the minimum weight is enough
    because both have zero toll in Level 2.
    """
    graph = defaultdict(dict)

    for route in ROUTES:
        a, b = route["between"]
        weight = route["weight"]

        if b not in graph[a] or weight < graph[a][b]:
            graph[a][b] = weight

        if a not in graph[b] or weight < graph[b][a]:
            graph[b][a] = weight

    return graph

def dijkstra(graph, source):
    distances = {vertex: math.inf for vertex in graph}
    previous = {}

    distances[source] = 0
    queue = [(0, source)]

    while queue:
        current_distance, current = heapq.heappop(queue)

        if current_distance != distances[current]:
            continue

        for neighbour, weight in graph[current].items():
            new_distance = current_distance + weight

            if new_distance < distances[neighbour]:
                distances[neighbour] = new_distance
                previous[neighbour] = current

                heapq.heappush(
                    queue,
                    (new_distance, neighbour)
                )

    return distances, previous

def shortest_path(graph, source, destination):
    if source == destination:
        return [source], 0

    distances, previous = dijkstra(graph, source)

    if distances.get(destination, math.inf) == math.inf:
        return None, math.inf

    path = [destination]

    while path[-1] != source:
        path.append(previous[path[-1]])

    path.reverse()

    return path, distances[destination]

def append_travel(actions, graph, source, destination):
    """
    Append the actual edge-by-edge travel actions required to move
    from source to destination.

    Returns the destination location.
    """
    path, _ = shortest_path(graph, source, destination)

    if path is None:
        raise ValueError(
            f"No path exists from {source} to {destination}"
        )

    for vertex in path[1:]:
        actions.append({
            "type": "travel",
            "destination": vertex
        })

    return destination

class GameState:

    def __init__(self):
        self.tick = 0
        self.location = STARTING_TOWN

        self.enteloot = STARTING_ENTELOOT
        self.inventory = defaultdict(int)

        self.production_cycles = {
            town: 0
            for town in TOWNS
        }

        self.enteloot_cycles = {
            town: 0
            for town in TOWNS
        }

        self.town_upgrades = {
            town: set(TOWNS[town].get("upgrades", []))
            for town in TOWNS
        }

        self.items_sold = 0
        self.invalid_actions = 0

        self.infrastructure_score = 0
        self.invested_enteloot = 0

        for town in TOWNS:
            for upgrade_name in self.town_upgrades[town]:
                if upgrade_name in ALL_UPGRADES:
                    upgrade = ALL_UPGRADES[upgrade_name]

                    self.infrastructure_score += (
                        upgrade["score_value"]
                    )

                    self.invested_enteloot += (
                        upgrade["enteloot_cost"]
                    )

    def clone(self):
        return deepcopy(self)

    def town_production_amounts(self, town):
        """
        Return the production amount after production upgrades.
        """
        amounts = dict(
            TOWNS[town]["production"]["resources"]
        )

        for upgrade_name in self.town_upgrades[town]:
            upgrade = ALL_UPGRADES.get(upgrade_name)

            if not upgrade:
                continue

            effect = upgrade.get("effect", {})

            if effect.get("type") == "production_double":
                resource = effect["resource"]

                if resource in amounts:
                    amounts[resource] *= 2

        return amounts

    def town_enteloot_amount(self, town):
        """
        Apply all Enteloot percentage bonuses.

        The specification says percentage bonuses stack additively
        before flooring.
        """
        base_amount = TOWNS[town]["enteloot"]["amount"]

        bonus = 0.0

        for upgrade_name in self.town_upgrades[town]:
            upgrade = ALL_UPGRADES.get(upgrade_name)

            if not upgrade:
                continue

            effect = upgrade.get("effect", {})

            if effect.get("type") == "enteloot_amount_pct":
                bonus += effect["value"]

        return math.floor(
            base_amount * (1 + bonus)
        )

    def town_enteloot_rate(self, town):
        rate = TOWNS[town]["enteloot"]["rate"]

        for upgrade_name in self.town_upgrades[town]:
            upgrade = ALL_UPGRADES.get(upgrade_name)

            if not upgrade:
                continue

            effect = upgrade.get("effect", {})

            if effect.get("type") == "enteloot_rate_delta":
                rate = max(
                    effect.get("min", 1),
                    rate + effect["value"]
                )

        return rate

    def advance_to(self, new_tick):
        """
        Advance the global clock and credit every passive cycle
        crossed during that time.

        This is important:
        passive resources and Enteloot become immediately available
        to later actions.
        """
        if new_tick > TOTAL_TICKS:
            new_tick = TOTAL_TICKS

        if new_tick < self.tick:
            raise ValueError("Cannot move time backwards")

        for town in TOWNS:

            production_rate = TOWNS[town]["production"]["rate"]

            completed_cycles = (
                new_tick // production_rate
            )

            previous_cycles = (
                self.production_cycles[town]
            )

            new_cycles = (
                completed_cycles - previous_cycles
            )

            if new_cycles > 0:
                amounts = self.town_production_amounts(town)

                for resource, amount in amounts.items():
                    self.inventory[resource] += (
                        new_cycles * amount
                    )

                self.production_cycles[town] = (
                    completed_cycles
                )

            enteloot_rate = self.town_enteloot_rate(town)

            completed_cycles = (
                new_tick // enteloot_rate
            )

            previous_cycles = (
                self.enteloot_cycles[town]
            )

            new_cycles = (
                completed_cycles - previous_cycles
            )

            if new_cycles > 0:
                amount = self.town_enteloot_amount(town)

                gained = new_cycles * amount

                self.enteloot += gained

                self.enteloot_cycles[town] = (
                    completed_cycles
                )

        self.tick = new_tick

def invalid_action(state):
    """
    Invalid actions consume one tick unless the run has ended.
    """
    state.invalid_actions += 1

    if state.tick < TOTAL_TICKS:
        state.advance_to(
            min(
                TOTAL_TICKS,
                state.tick + INVALID_ACTION_TICKS
            )
        )

def action_fits(state, ticks_needed):
    return (
        state.tick + ticks_needed <= TOTAL_TICKS
    )

def can_build_upgrade(state, town, upgrade_name):
    if town not in TOWNS:
        return False

    if upgrade_name not in ALL_UPGRADES:
        return False

    if upgrade_name in state.town_upgrades[town]:
        return False

    upgrade = ALL_UPGRADES[upgrade_name]
    prerequisite = upgrade.get("prerequisite")

    if prerequisite is None:
        return True

    prerequisite_type = prerequisite["type"]

    if prerequisite_type == "any_production_upgrades":
        required_count = prerequisite["count"]

        count = sum(
            1
            for built in state.town_upgrades[town]
            if built in PRODUCTION_UPGRADES
        )

        return count >= required_count

    if prerequisite_type == "specific_upgrade":
        return (
            prerequisite["upgrade"]
            in state.town_upgrades[town]
        )

    return False

def simulate(actions, graph, stop_on_invalid=False):
    """
    Execute actions according to the specification.

    Passive systems are credited whenever time advances.
    """
    state = GameState()

    for action in actions:

        if state.tick >= TOTAL_TICKS:
            break

        action_type = action.get("type")

        # ====================================================
        # TRAVEL
        # ====================================================

        if action_type == "travel":

            destination = action.get("destination")

            if (
                destination not in graph.get(
                    state.location,
                    {}
                )
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            travel_time = graph[state.location][destination]

            if not action_fits(state, travel_time):
                state.advance_to(TOTAL_TICKS)
                break

            state.advance_to(
                state.tick + travel_time
            )

            state.location = destination


        # ====================================================
        # GATHER
        # ====================================================

        elif action_type == "gather":

            if state.location not in NODES:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            node = NODES[state.location]
            gather_time = node["gather-time"]

            if not action_fits(state, gather_time):
                state.advance_to(TOTAL_TICKS)
                break

            state.advance_to(
                state.tick + gather_time
            )

            state.inventory[node["resource"]] += (
                node["yield"]
            )


        # ====================================================
        # BUY
        # ====================================================

        elif action_type == "buy":

            item = action.get("item")
            quantity = action.get("quantity")

            if (
                state.location not in TOWNS
                or not isinstance(quantity, int)
                or quantity <= 0
                or item not in RESOURCE_PRICES
                or item not in TOWNS[
                    state.location
                ]["production"]["resources"]
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            buy_price = RESOURCE_PRICES[item]["buy_price"]

            if buy_price is None:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            cost = quantity * buy_price

            if (
                state.enteloot < cost
                or not action_fits(state, 1)
            ):
                if state.tick + 1 > TOTAL_TICKS:
                    state.advance_to(TOTAL_TICKS)
                    break

                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            state.enteloot -= cost

            state.advance_to(state.tick + 1)

            state.inventory[item] += quantity


        # ====================================================
        # CRAFT
        # ====================================================

        elif action_type == "craft":

            item = action.get("item")
            quantity = action.get("quantity")

            if (
                state.location not in TOWNS
                or not isinstance(quantity, int)
                or quantity <= 0
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            recipe = RECIPES.get(item)

            if recipe is None:
                recipe = COMPONENTS.get(item)

            if recipe is None:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            enough_inputs = all(
                state.inventory[resource]
                >= amount * quantity

                for resource, amount
                in recipe["inputs"].items()
            )

            if not enough_inputs:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            has_affinity = (
                "crafting"
                in TOWNS[state.location].get(
                    "affinities",
                    []
                )
            )

            craft_time_per_item = (
                CRAFT_TIME_AFFINITY
                if has_affinity
                else CRAFT_TIME_BASE
            )

            total_craft_time = (
                quantity * craft_time_per_item
            )

            if not action_fits(
                state,
                total_craft_time
            ):
                state.advance_to(TOTAL_TICKS)
                break

            for resource, amount in recipe["inputs"].items():
                state.inventory[resource] -= (
                    amount * quantity
                )

            state.advance_to(
                state.tick + total_craft_time
            )

            state.inventory[item] += quantity


        # ====================================================
        # SELL
        # ====================================================

        elif action_type == "sell":

            item = action.get("item")
            quantity = action.get("quantity")

            if (
                state.location not in TOWNS
                or not isinstance(quantity, int)
                or quantity <= 0
                or state.inventory[item] < quantity
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            if not action_fits(state, 1):
                state.advance_to(TOTAL_TICKS)
                break

            if item in RESOURCE_PRICES:
                sell_price = (
                    RESOURCE_PRICES[item]["sell_price"]
                )
            else:
                sell_price = TOWNS[
                    state.location
                ]["item-rates"].get(item)

            if sell_price is None:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            state.inventory[item] -= quantity

            state.advance_to(state.tick + 1)

            state.enteloot += (
                quantity * sell_price
            )

            state.items_sold += quantity


        # ====================================================
        # BUILD
        # ====================================================

        elif action_type == "build":

            upgrade_name = action.get("upgrade")

            if state.location not in TOWNS:
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            if not can_build_upgrade(
                state,
                state.location,
                upgrade_name
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            upgrade = ALL_UPGRADES[upgrade_name]

            enough_components = all(
                state.inventory[component] >= amount

                for component, amount
                in upgrade["components"].items()
            )

            enough_enteloot = (
                state.enteloot
                >= upgrade["enteloot_cost"]
            )

            build_time = upgrade["build_time"]

            if (
                not enough_components
                or not enough_enteloot
            ):
                invalid_action(state)

                if stop_on_invalid:
                    break

                continue

            if not action_fits(state, build_time):
                state.advance_to(TOTAL_TICKS)
                break

            # Spend everything at the start of the valid build.
            for component, amount in (
                upgrade["components"].items()
            ):
                state.inventory[component] -= amount

            state.enteloot -= (
                upgrade["enteloot_cost"]
            )

            state.invested_enteloot += (
                upgrade["enteloot_cost"]
            )

            # The upgrade becomes active after the build finishes.
            state.advance_to(
                state.tick + build_time
            )

            state.town_upgrades[
                state.location
            ].add(upgrade_name)

            state.infrastructure_score += (
                upgrade["score_value"]
            )


        # ====================================================
        # UNKNOWN ACTION
        # ====================================================

        else:
            invalid_action(state)

            if stop_on_invalid:
                break


    # Finish the clock so the final passive state is correct.
    if state.tick < TOTAL_TICKS:
        state.advance_to(TOTAL_TICKS)

    return state

def best_node_for_resource(resource, graph, start):
    """
    Find the best gathering node for a resource while considering
    travel distance from the current location and yield.
    """
    best = None

    for node_id, node in NODES.items():

        if node["resource"] != resource:
            continue

        _, distance = shortest_path(
            graph,
            start,
            node_id
        )

        if distance == math.inf:
            continue

        # Lower is better.
        # This is travel plus approximate time per unit.
        cost = (
            distance
            + node["gather-time"] / node["yield"]
        )

        candidate = {
            "node": node_id,
            "distance": distance,
            "cost": cost,
            "yield": node["yield"],
            "gather_time": node["gather-time"]
        }

        if (
            best is None
            or candidate["cost"] < best["cost"]
        ):
            best = candidate

    return best

def gather_actions_needed(
    resource,
    quantity,
    graph,
    current_location
):
    """
    Return a plan for gathering at the best currently reachable node.
    """
    node_plan = best_node_for_resource(
        resource,
        graph,
        current_location
    )

    if node_plan is None:
        return None

    node = NODES[node_plan["node"]]

    gathers = math.ceil(
        quantity / node["yield"]
    )

    return {
        "node": node_plan["node"],
        "gathers": gathers,
        "produced": gathers * node["yield"],
        "travel_time": node_plan["distance"],
        "gather_time": (
            gathers * node["gather-time"]
        )
    }

def best_crafting_town(
    graph,
    current_location
):
    """
    Choose the nearest crafting-affinity town.
    """
    affinity_towns = [
        town
        for town in TOWNS
        if "crafting"
        in TOWNS[town].get("affinities", [])
    ]

    if not affinity_towns:
        return current_location

    best_town = None
    best_distance = math.inf

    for town in affinity_towns:
        _, distance = shortest_path(
            graph,
            current_location,
            town
        )

        if distance < best_distance:
            best_distance = distance
            best_town = town

    return best_town

def best_sell_town(item, graph, current_location):
    best = None

    for town in TOWNS:
        price = TOWNS[town]["item-rates"].get(
            item,
            0
        )

        _, distance = shortest_path(
            graph,
            current_location,
            town
        )

        if distance == math.inf:
            continue

        candidate = {
            "town": town,
            "price": price,
            "distance": distance
        }

        if (
            best is None
            or candidate["price"] > best["price"]
            or (
                candidate["price"] == best["price"]
                and candidate["distance"]
                < best["distance"]
            )
        ):
            best = candidate

    return best

def recipe_estimate(
    item,
    graph,
    start_location
):
    """
    Estimate the profitability of EVERY sellable recipe.

    This supports multi-resource recipes and includes:
    - gathering
    - travel
    - crafting
    - travel to selling town
    - selling
    """
    recipe = RECIPES[item]

    current = start_location
    total_ticks = 0

    resource_requirements = recipe["inputs"]

    # Approximate route by collecting each resource in deterministic
    # resource-name order.
    for resource in sorted(resource_requirements):

        quantity = resource_requirements[resource]

        gather_plan = gather_actions_needed(
            resource,
            quantity,
            graph,
            current
        )

        if gather_plan is None:
            return None

        total_ticks += gather_plan["travel_time"]
        total_ticks += gather_plan["gather_time"]

        current = gather_plan["node"]

    craft_town = best_crafting_town(
        graph,
        current
    )

    _, craft_travel = shortest_path(
        graph,
        current,
        craft_town
    )

    total_ticks += craft_travel

    craft_time = (
        CRAFT_TIME_AFFINITY
        if "crafting"
        in TOWNS[craft_town].get(
            "affinities",
            []
        )
        else CRAFT_TIME_BASE
    )

    total_ticks += craft_time

    sell_plan = best_sell_town(
        item,
        graph,
        craft_town
    )

    if sell_plan is None:
        return None

    total_ticks += sell_plan["distance"]
    total_ticks += 1

    if total_ticks <= 0:
        return None

    return {
        "item": item,
        "estimated_ticks": total_ticks,
        "sell_town": sell_plan["town"],
        "sell_price": sell_plan["price"],
        "craft_town": craft_town,
        "value_per_tick": (
            sell_plan["price"] / total_ticks
        )
    }

def rank_recipes(graph):
    plans = []

    for item in RECIPES:

        plan = recipe_estimate(
            item,
            graph,
            STARTING_TOWN
        )

        if plan is not None:
            plans.append(plan)

    plans.sort(
        key=lambda plan: (
            -plan["value_per_tick"],
            -plan["sell_price"],
            plan["estimated_ticks"],
            plan["item"]
        )
    )

    return plans

def expand_component_requirements(
    item,
    quantity,
    requirements
):
    """
    Recursively expand a component into its raw resources.

    Example:
        bricks -> clay + mortar
        mortar -> clay + stone

    becomes:
        bricks(n) => clay(3n) + stone(n)
    """
    if item in RESOURCE_PRICES:
        requirements[item] += quantity
        return

    recipe = COMPONENTS.get(item)

    if recipe is None:
        raise ValueError(
            f"Unknown component/resource: {item}"
        )

    for input_item, amount in recipe["inputs"].items():
        expand_component_requirements(
            input_item,
            amount * quantity,
            requirements
        )

def component_craft_order(item, quantity, result):
    """
    Return component crafts in dependency order.

    Dependencies are placed before the component that consumes them.
    """
    if item in RESOURCE_PRICES:
        return

    recipe = COMPONENTS[item]

    for input_item, amount in recipe["inputs"].items():

        if input_item in COMPONENTS:
            component_craft_order(
                input_item,
                amount * quantity,
                result
            )

    result[item] += quantity

def upgrade_raw_requirements(upgrade_name):
    requirements = defaultdict(int)

    upgrade = ALL_UPGRADES[upgrade_name]

    for component, quantity in (
        upgrade["components"].items()
    ):
        expand_component_requirements(
            component,
            quantity,
            requirements
        )

    return requirements

def upgrade_component_order(upgrade_name):
    result = defaultdict(int)

    upgrade = ALL_UPGRADES[upgrade_name]

    for component, quantity in (
        upgrade["components"].items()
    ):
        component_craft_order(
            component,
            quantity,
            result
        )

    return result

def append_collect_resource(
    actions,
    graph,
    current_location,
    resource,
    quantity
):
    """
    Gather a resource from the best reachable node.
    """
    plan = gather_actions_needed(
        resource,
        quantity,
        graph,
        current_location
    )

    if plan is None:
        raise ValueError(
            f"No gathering node for {resource}"
        )

    current_location = append_travel(
        actions,
        graph,
        current_location,
        plan["node"]
    )

    for _ in range(plan["gathers"]):
        actions.append({
            "type": "gather"
        })

    return current_location

def build_upgrade_plan(
    graph,
    target_town,
    upgrade_sequence
):
    """
    Build a deterministic plan:

    1. Gather all raw resources needed.
    2. Move to the target town.
    3. Craft dependency chains at that town.
    4. Build upgrades in order.

    All component dependencies are respected.
    """
    actions = []
    current_location = STARTING_TOWN

    # Calculate the total raw resources required by the entire
    # upgrade sequence.
    total_raw = defaultdict(int)

    for upgrade_name in upgrade_sequence:
        requirements = upgrade_raw_requirements(
            upgrade_name
        )

        for resource, quantity in requirements.items():
            total_raw[resource] += quantity

    # Gather raw resources.
    for resource in sorted(total_raw):

        current_location = append_collect_resource(
            actions,
            graph,
            current_location,
            resource,
            total_raw[resource]
        )

    # Go to the town where construction will happen.
    current_location = append_travel(
        actions,
        graph,
        current_location,
        target_town
    )

    # Craft only the components needed for the full sequence.
    total_components = defaultdict(int)

    for upgrade_name in upgrade_sequence:

        component_order = upgrade_component_order(
            upgrade_name
        )

        for component, quantity in component_order.items():
            total_components[component] += quantity

    # Craft in dependency order.
    #
    # We recompute the dependency sequence per upgrade to preserve
    # correct ordering.
    for upgrade_name in upgrade_sequence:

        component_order = upgrade_component_order(
            upgrade_name
        )

        for component, quantity in component_order.items():

            if quantity > 0:
                actions.append({
                    "type": "craft",
                    "item": component,
                    "quantity": quantity
                })

    # Build upgrades.
    for upgrade_name in upgrade_sequence:
        actions.append({
            "type": "build",
            "upgrade": upgrade_name
        })

    return actions

def build_trade_plan(
    graph,
    recipe_plan
):
    """
    Generate a repeated gather -> craft -> sell strategy.

    This is used to generate Enteloot for infrastructure.
    """
    item = recipe_plan["item"]
    recipe = RECIPES[item]

    actions = []
    current_location = STARTING_TOWN

    # Produce one reasonably large batch.
    #
    # The simulator later verifies that all actions are valid.
    batch_size = 20

    for resource in sorted(recipe["inputs"]):

        needed = (
            recipe["inputs"][resource]
            * batch_size
        )

        current_location = append_collect_resource(
            actions,
            graph,
            current_location,
            resource,
            needed
        )

    craft_town = recipe_plan["craft_town"]

    current_location = append_travel(
        actions,
        graph,
        current_location,
        craft_town
    )

    actions.append({
        "type": "craft",
        "item": item,
        "quantity": batch_size
    })

    sell_town = recipe_plan["sell_town"]

    current_location = append_travel(
        actions,
        graph,
        current_location,
        sell_town
    )

    actions.append({
        "type": "sell",
        "item": item,
        "quantity": batch_size
    })

    return actions

def valid_upgrade_sequences():
    """
    Level 2 candidate sequences.

    We deliberately include prerequisite chains rather than pretending
    upgrades are independent.
    """

    return [
        ["farmhouse"],
        ["pier"],
        ["fertilised-fields"],
        ["quarry"],
        ["woodlands"],
        ["pottery-house"],

        ["farmhouse", "rec-center"],
        ["pier", "rec-center"],
        ["fertilised-fields", "rec-center"],
        ["quarry", "rec-center"],
        ["woodlands", "rec-center"],
        ["pottery-house", "rec-center"],

        [
            "farmhouse",
            "pier",
            "fire-station"
        ],

        [
            "farmhouse",
            "rec-center",
            "school"
        ],

        [
            "farmhouse",
            "rec-center",
            "school",
            "library"
        ]
    ]

def plan_score(state):
    """
    The exact Level 2 scoring formula is not supplied in the
    specification. Therefore this is an optimisation heuristic.

    Infrastructure receives dominant weight because the specification
    explicitly says infrastructure is the primary driver.

    Development spread is rewarded because the specification says it
    earns a multiplier.
    """
    developed_towns = sum(
        1
        for upgrades in state.town_upgrades.values()
        if upgrades
    )

    total_upgrades = sum(
        len(upgrades)
        for upgrades in state.town_upgrades.values()
    )

    # Heuristic spread multiplier.
    #
    # It is intentionally labelled a heuristic because the official
    # exact equation is not in the provided specification.
    spread_multiplier = (
        1.0
        + 0.15 * max(0, developed_towns - 1)
    )

    infrastructure_value = (
        state.infrastructure_score
        * spread_multiplier
    )

    # Small contribution from final economy.
    inventory_value = 0

    for item, quantity in state.inventory.items():

        if quantity <= 0:
            continue

        if item in RESOURCE_PRICES:
            inventory_value += (
                quantity
                * RESOURCE_PRICES[item]["sell_price"]
            )

        elif item in RECIPES:
            best_price = max(
                town["item-rates"].get(item, 0)
                for town in TOWNS.values()
            )

            inventory_value += (
                quantity * best_price
            )

    return (
        infrastructure_value
        + state.enteloot
        + inventory_value
    )

def generate_candidates(graph):

    candidates = []

    # --------------------------------------------------------
    # PURE TRADE CANDIDATES
    # --------------------------------------------------------

    for recipe_plan in rank_recipes(graph):

        actions = []

        # Repeat the trade batch.
        for _ in range(20):
            actions.extend(
                build_trade_plan(
                    graph,
                    recipe_plan
                )
            )

        result = simulate(
            actions,
            graph
        )

        candidates.append({
            "name": (
                f"trade:{recipe_plan['item']}"
            ),
            "actions": actions,
            "result": result,
            "score": plan_score(result)
        })


    # --------------------------------------------------------
    # INFRASTRUCTURE CANDIDATES
    # --------------------------------------------------------

    for target_town in TOWNS:

        for sequence in valid_upgrade_sequences():

            # Level 2 cannot afford/use police-station.
            if "police-station" in sequence:
                continue

            build_actions = build_upgrade_plan(
                graph,
                target_town,
                sequence
            )

            result = simulate(
                build_actions,
                graph
            )

            # Reject plans containing invalid actions.
            if result.invalid_actions > 0:
                continue

            candidates.append({
                "name": (
                    f"build:{target_town}:"
                    + "->".join(sequence)
                ),
                "actions": build_actions,
                "result": result,
                "score": plan_score(result)
            })

    return candidates

def choose_best_candidate(graph):

    candidates = generate_candidates(graph)

    if not candidates:
        raise RuntimeError(
            "No valid Level 2 candidate plans were generated"
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate["score"],
            -candidate["result"].infrastructure_score,
            -candidate["result"].enteloot,
            candidate["name"]
        )
    )

    return candidates[0], candidates

def main():

    print("=" * 70)
    print("AGE OF ENTELAND - LEVEL 2 OPTIMISER")
    print("=" * 70)

    print(f"Total ticks:       {TOTAL_TICKS}")
    print(f"Starting town:     {STARTING_TOWN}")
    print(f"Starting Enteloot: {STARTING_ENTELOOT}")

    graph = build_graph()

    best, candidates = choose_best_candidate(
        graph
    )

    result = best["result"]
    action_list = best["actions"]

    print("\n" + "=" * 70)
    print("CHOSEN PLAN")
    print("=" * 70)

    print(best["name"])
    print(f"Heuristic score:       {best['score']:.2f}")
    print(f"Infrastructure score:  {result.infrastructure_score}")
    print(f"Final Enteloot:        {result.enteloot}")
    print(f"Final tick:            {result.tick}/{TOTAL_TICKS}")
    print(f"Items sold:            {result.items_sold}")
    print(f"Invalid actions:       {result.invalid_actions}")

    print("\nUpgrades by town:")

    for town, upgrades in result.town_upgrades.items():
        if upgrades:
            print(
                f"  {town}: "
                + ", ".join(sorted(upgrades))
            )

    print("\nRemaining inventory:")

    remaining = {
        item: quantity
        for item, quantity in result.inventory.items()
        if quantity > 0
    }

    print(remaining)

    print(f"\nCandidates evaluated: {len(candidates)}")

    with open(
        "level2_output.txt",
        "w",
        encoding="utf-8"
    ) as output_file:

        json.dump(
            {"actions": action_list},
            output_file,
            indent=2
        )

    print(
        f"\nWrote {len(action_list)} actions "
        "to level2_output.txt"
    )

if __name__ == "__main__":
    main()