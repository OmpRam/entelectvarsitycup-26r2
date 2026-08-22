import json
import math
from typing import Dict, List, Tuple


class GameState:
    def __init__(self, level_data: dict):
        self.towns = level_data["towns"]
        self.nodes = level_data["nodes"]
        self.routes = level_data["routes"]
        self.total_ticks = level_data["run"]["total_ticks"]
        self.starting_town = level_data["run"]["starting_town"]
        self.starting_enteloot = level_data["run"]["starting_enteloot"]

        # Player state
        self.current_location = self.starting_town
        self.enteloot = self.starting_enteloot
        self.inventory = {}
        self.tick = 0

        # Track accumulated town production
        self.town_production = {town: {} for town in self.towns}
        for town_name, town_data in self.towns.items():
            for resource, amount in town_data["production"]["resources"].items():
                self.town_production[town_name][resource] = 0

        # Track town enteloot
        self.town_enteloot = {town: 0 for town in self.towns}

        # Build graph for pathfinding
        self.graph = self._build_graph()

        # Cache shortest paths
        self.shortest_paths = {}
        self._compute_shortest_paths()

    def _build_graph(self) -> dict:
        """Build adjacency graph from routes"""
        graph = {}
        for route in self.routes:
            v1, v2 = route["between"][0], route["between"][1]
            weight = route["weight"]
            toll = route.get("toll", 0)

            if v1 not in graph:
                graph[v1] = {}
            if v2 not in graph:
                graph[v2] = {}

            graph[v1][v2] = {"weight": weight, "toll": toll}
            graph[v2][v1] = {"weight": weight, "toll": toll}

        return graph

    def _compute_shortest_paths(self):
        """Compute shortest paths between all vertices using Dijkstra"""
        all_vertices = set(self.graph.keys())
        for start in all_vertices:
            self.shortest_paths[start] = self._dijkstra(start)

    def _dijkstra(self, start: str) -> dict:
        """Dijkstra's algorithm for shortest paths (no tolls in Level 1)"""
        import heapq
        distances = {v: float('inf') for v in self.graph}
        distances[start] = 0
        paths = {v: [] for v in self.graph}
        paths[start] = [start]

        pq = [(0, start, [start])]
        visited = set()

        while pq:
            dist, current, path = heapq.heappop(pq)
            if current in visited:
                continue
            visited.add(current)

            for neighbor, edge in self.graph[current].items():
                new_dist = dist + edge["weight"]
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    paths[neighbor] = path + [neighbor]
                    heapq.heappush(pq, (new_dist, neighbor, paths[neighbor]))

        return {"distances": distances, "paths": paths}

    def get_travel_path(self, start: str, dest: str) -> List[str]:
        """Get shortest path between two vertices"""
        return self.shortest_paths[start]["paths"][dest]

    def get_travel_cost(self, start: str, dest: str) -> int:
        """Get travel time between two vertices"""
        return self.shortest_paths[start]["distances"][dest]

    def can_afford_action(self, cost: int) -> bool:
        """Check if player can afford an action"""
        return self.enteloot >= cost

    def perform_travel(self, dest: str, fast: bool = False) -> Tuple[bool, str]:
        """Travel to destination along shortest path"""
        if dest not in self.graph:
            return False, f"Destination {dest} not found"

        path = self.get_travel_path(self.current_location, dest)
        total_ticks = 0
        total_toll = 0

        # Calculate total travel time and tolls
        for i in range(len(path) - 1):
            v1, v2 = path[i], path[i + 1]
            edge = self.graph[v1][v2]
            if fast and edge.get("toll", 0) > 0:
                total_ticks += 1  # Fast route weight
                total_toll += edge["toll"]
            else:
                total_ticks += edge["weight"]

        # Check if we can afford toll
        if not self.can_afford_action(total_toll):
            return False, f"Cannot afford toll of {total_toll}"

        # Check if we have enough ticks
        if self.tick + total_ticks > self.total_ticks:
            return False, f"Not enough ticks remaining (need {total_ticks}, have {self.total_ticks - self.tick})"

        # Execute travel
        self.tick += total_ticks
        self.enteloot -= total_toll
        self.current_location = dest

        # Accumulate passive production during travel
        self._accumulate_passive(total_ticks)

        return True, f"Traveled to {dest} in {total_ticks} ticks"

    def perform_gather(self) -> Tuple[bool, str]:
        """Gather resources at current node"""
        if self.current_location not in self.nodes:
            return False, f"Cannot gather at {self.current_location}"

        node = self.nodes[self.current_location]
        gather_time = node["gather-time"]

        if self.tick + gather_time > self.total_ticks:
            return False, f"Not enough ticks remaining (need {gather_time}, have {self.total_ticks - self.tick})"

        resource = node["resource"]
        yield_amount = node["yield"]

        # Execute gather
        self.tick += gather_time
        self.inventory[resource] = self.inventory.get(
            resource, 0) + yield_amount

        # Accumulate passive production during gathering
        self._accumulate_passive(gather_time)

        return True, f"Gathered {yield_amount} {resource}"

    def perform_sell(self, item: str, quantity: int) -> Tuple[bool, str]:
        """Sell items at current town"""
        if self.current_location not in self.towns:
            return False, f"Cannot sell at {self.current_location}"

        if item not in self.inventory or self.inventory[item] < quantity:
            return False, f"Not enough {item} (have {self.inventory.get(item, 0)}, need {quantity})"

        # Get sell price (global for raw resources in Level 1)
        sell_prices = {
            "wheat": 2, "wood": 3, "stone": 3,
            "clay": 4, "fish": 4, "sheep": 5, "ore": 6
        }
        price = sell_prices.get(item, 0)
        if price == 0:
            return False, f"Unknown item: {item}"

        # Execute sell
        self.tick += 1
        self.inventory[item] -= quantity
        self.enteloot += price * quantity

        # Accumulate passive production during selling
        self._accumulate_passive(1)

        return True, f"Sold {quantity} {item} for {price * quantity} Enteloot"

    def _accumulate_passive(self, ticks: int):
        """Accumulate passive production from all towns"""
        # Accumulate resources
        for town_name, town_data in self.towns.items():
            rate = town_data["production"]["rate"]
            for resource, amount in town_data["production"]["resources"].items():
                cycles = ticks // rate
                if cycles > 0:
                    self.town_production[town_name][resource] += cycles * amount

        # Accumulate Enteloot
        for town_name, town_data in self.towns.items():
            rate = town_data["enteloot"]["rate"]
            amount = town_data["enteloot"]["amount"]
            cycles = ticks // rate
            if cycles > 0:
                self.town_enteloot[town_name] += cycles * amount

    def flush_inventory(self) -> int:
        """Sell all passively accumulated resources"""
        items_sold = {}
        total_revenue = 0
        sell_prices = {"wheat": 2, "wood": 3, "stone": 3,
                       "clay": 4, "fish": 4, "sheep": 5, "ore": 6}

        # Collect all accumulated resources from all towns
        for town_name, resources in self.town_production.items():
            for resource, amount in resources.items():
                if amount > 0:
                    # Move to inventory
                    self.inventory[resource] = self.inventory.get(
                        resource, 0) + amount
                    # Clear town production
                    self.town_production[town_name][resource] = 0

        # Sell all inventory
        for item, quantity in list(self.inventory.items()):
            if quantity > 0:
                price = sell_prices.get(item, 0)
                if price > 0:
                    # Need to travel to a town to sell
                    if self.current_location not in self.towns:
                        # Travel to nearest town
                        nearest_town = self._find_nearest_town()
                        if nearest_town:
                            self.perform_travel(nearest_town)

                    revenue = price * quantity
                    self.enteloot += revenue
                    total_revenue += revenue
                    items_sold[item] = quantity
                    self.inventory[item] = 0

        return total_revenue

    def _find_nearest_town(self) -> str:
        """Find nearest town from current location"""
        nearest = None
        min_dist = float('inf')
        for town in self.towns:
            try:
                dist = self.get_travel_cost(self.current_location, town)
                if dist < min_dist:
                    min_dist = dist
                    nearest = town
            except:
                pass
        return nearest

    def get_final_enteloot(self) -> int:
        """Get total Enteloot including passive town Enteloot"""
        total = self.enteloot
        for town, amount in self.town_enteloot.items():
            total += amount
        return total

    def get_total_items_sold(self) -> int:
        """Count total items sold from inventory flush"""
        total = 0
        sell_prices = {"wheat": 2, "wood": 3, "stone": 3,
                       "clay": 4, "fish": 4, "sheep": 5, "ore": 6}

        for town_name, resources in self.town_production.items():
            for resource, amount in resources.items():
                if resource in sell_prices and amount > 0:
                    total += amount

        # Add sheep from gathering
        if "sheep" in self.inventory:
            total += self.inventory.get("sheep", 0)

        return total


class Level1Solver:
    def __init__(self, level_data: dict):
        self.data = level_data
        self.game = GameState(level_data)
        self.actions = []

    def solve(self) -> dict:
        """Solve Level 1 with optimal strategy"""
        print(f"Starting Level 1 optimization")
        print(f"Total ticks: {self.game.total_ticks}")
        print(f"Starting Enteloot: {self.game.starting_enteloot}")

        # Strategy: Gather sheep at N1 (best profit per tick)
        # Path: Demacia -> N3 -> N6 -> N1
        path_to_n1 = ["N3", "N6", "N1"]

        # Travel to N1
        for dest in path_to_n1:
            success, msg = self.game.perform_travel(dest)
            if not success:
                print(f"Travel failed: {msg}")
                break
            self.actions.append({"type": "travel", "destination": dest})
            print(f"Tick {self.game.tick}: {msg}")

        # Gather sheep as many times as possible
        gather_count = 0
        while self.game.tick + 2 <= self.game.total_ticks:
            success, msg = self.game.perform_gather()
            if not success:
                break
            self.actions.append({"type": "gather"})
            gather_count += 1
            if gather_count % 50 == 0:
                print(f"Tick {self.game.tick}: Gathered {gather_count} times")

        print(f"Gathered sheep {gather_count} times")

        # Travel back to Demacia to sell
        path_back = ["N6", "N3", "Demacia"]
        for dest in path_back:
            if self.game.tick < self.game.total_ticks:
                success, msg = self.game.perform_travel(dest)
                if not success:
                    print(f"Travel back failed: {msg}")
                    break
                self.actions.append({"type": "travel", "destination": dest})
                print(f"Tick {self.game.tick}: {msg}")

        # Sell sheep
        if "sheep" in self.game.inventory:
            sheep_count = self.game.inventory["sheep"]
            success, msg = self.game.perform_sell("sheep", sheep_count)
            if success:
                self.actions.append(
                    {"type": "sell", "item": "sheep", "quantity": sheep_count})
                print(f"Tick {self.game.tick}: {msg}")
            else:
                print(f"Sell failed: {msg}")

        # Sell all passively accumulated resources
        print(f"Flushing passive inventory...")
        passive_revenue = self.game.flush_inventory()
        print(f"Passive resource revenue: {passive_revenue}")

        # Add passive sell actions
        for item, quantity in self.game.inventory.items():
            if quantity > 0:
                self.actions.append(
                    {"type": "sell", "item": item, "quantity": quantity})

        # Generate final JSON
        result = {
            "actions": self.actions
        }

        # Calculate final score
        final_enteloot = self.game.get_final_enteloot()
        items_sold = self.game.get_total_items_sold()

        print(f"\nFinal Results:")
        print(f"Final Enteloot: {final_enteloot}")
        print(f"Items sold: {items_sold}")
        print(f"Ticks used: {self.game.tick}")
        print(f"Actions: {len(self.actions)}")

        return result


def main():
    # Load the level data
    with open("1 (1).txt", "r") as f:
        level_data = json.load(f)

    # Solve Level 1
    solver = Level1Solver(level_data)
    solution = solver.solve()

    # Save solution
    with open("solution_level1.txt", "w") as f:
        json.dump(solution, f, indent=2)

    print(f"\nSolution saved to solution_level1.txt")
    print(f"Total actions: {len(solution['actions'])}")


if __name__ == "__main__":
    main()
