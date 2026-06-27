from typing import Dict, List
from BaseClasses import Item, ItemClassification, Region, Tutorial
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, components, Type, launch_subprocess

from .Items import FF2Item, ITEM_TABLE, item_name_to_id, item_descriptions
from .Locations import (FF2Location, LOCATION_TABLE, ZONE_BOUNDARIES,
                        location_name_to_id, location_descriptions,
                        fish_required_for_zone, zone_for_level_id)
from .Options import FF2Options

GAME_NAME              = "Feeding Frenzy 2"
PROGRESSIVE_FISH_COUNT = 10
EXTRA_FISH             = 2
TOTAL_FISH_ITEMS       = PROGRESSIVE_FISH_COUNT + EXTRA_FISH
DASH_COUNT             = 1
SUCK_COUNT             = 1
TOTAL_LOCATIONS        = len(LOCATION_TABLE)
TOTAL_1UP_ITEMS        = TOTAL_LOCATIONS - TOTAL_FISH_ITEMS - DASH_COUNT - SUCK_COUNT


# ── Launcher registration ─────────────────────────────────────────────────────

def _launch_client(*args: str):
    from .Client import main
    launch_subprocess(main, name="Feeding Frenzy 2 Client", args=args)


components.append(Component(
    "Feeding Frenzy 2 Client",
    func=_launch_client,
    component_type=Type.CLIENT,
    game_name=GAME_NAME,
    description="Connect to the Archipelago server for Feeding Frenzy 2.",
))


# ── Web world ─────────────────────────────────────────────────────────────────

class FF2WebWorld(WebWorld):
    theme = "ocean"
    item_descriptions      = item_descriptions
    location_descriptions  = location_descriptions
    tutorials = [Tutorial(
        tutorial_name="Setup Guide",
        description="A guide to setting up Feeding Frenzy 2 Archipelago.",
        language="English",
        file_name="setup_en.md",
        link="setup/en",
        authors=["archipelago"],
    )]


# ── World ─────────────────────────────────────────────────────────────────────

class FF2World(World):
    """
    Feeding Frenzy 2: Shipwreck Showdown is a casual arcade game where you
    play as a fish eating smaller fish to grow bigger. Collect Progressive Fish
    items to unlock new zones, and reach the final boss to win!
    """

    game              = GAME_NAME
    web               = FF2WebWorld()
    options_dataclass = FF2Options

    item_name_to_id:     Dict[str, int] = item_name_to_id
    location_name_to_id: Dict[str, int] = location_name_to_id

    def generate_early(self) -> None:
        if self.options.level_shuffle:
            indices = list(range(1, 59))
            self.random.shuffle(indices)
            self.level_shuffle: List[int] = [0] + indices + [59]
        else:
            self.level_shuffle: List[int] = list(range(60))

    def create_item(self, name: str) -> FF2Item:
        data = ITEM_TABLE[name]
        return FF2Item(name, data.classification, data.code, self.player)

    def create_items(self) -> None:
        for _ in range(TOTAL_FISH_ITEMS):
            self.multiworld.itempool.append(self.create_item("Progressive Fish"))
        for _ in range(DASH_COUNT):
            self.multiworld.itempool.append(self.create_item("Dash"))
        for _ in range(SUCK_COUNT):
            self.multiworld.itempool.append(self.create_item("Suck"))
        for _ in range(TOTAL_1UP_ITEMS):
            self.multiworld.itempool.append(self.create_item("1-Up"))

    def create_regions(self) -> None:
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        zone_regions: List[Region] = []
        for zone_idx in range(len(ZONE_BOUNDARIES)):
            zone_region = Region(f"Zone {zone_idx}", self.player, self.multiworld)
            self.multiworld.regions.append(zone_region)
            zone_regions.append(zone_region)

        goal_region = Region("Goal", self.player, self.multiworld)
        self.multiworld.regions.append(goal_region)

        # Menu -> Zone 0 (free)
        menu_region.connect(zone_regions[0])

        # Zone N -> Zone N+1 (requires N+1 fish)
        for zone_idx in range(len(ZONE_BOUNDARIES) - 1):
            fish_needed = zone_idx + 1
            zone_regions[zone_idx].connect(
                zone_regions[zone_idx + 1],
                rule=lambda state, n=fish_needed:
                    state.has("Progressive Fish", self.player, n)
            )

        # Final zone -> Goal (requires all 10 fish)
        zone_regions[-1].connect(
            goal_region,
            rule=lambda state:
                state.has("Progressive Fish", self.player, PROGRESSIVE_FISH_COUNT)
        )

        # Place locations into zone regions.
        # With level shuffle the accessibility of each location depends on which
        # map slot holds that content, so we map content -> slot to find its zone.
        content_to_slot: List[int] = [0] * 60
        for slot, content in enumerate(self.level_shuffle):
            content_to_slot[content] = slot

        for loc_name, loc_data in LOCATION_TABLE.items():
            slot        = content_to_slot[loc_data.level_id]
            slot_zone   = zone_for_level_id(slot)
            zone_region = zone_regions[slot_zone]
            location    = FF2Location(
                self.player, loc_name, loc_data.code, zone_region
            )
            zone_region.locations.append(location)
            if loc_data.level_id == 57:
                location.access_rule = lambda state: state.has("Dash", self.player)

        # Victory event
        victory_location = FF2Location(self.player, "Final Boss", None, goal_region)
        victory_location.place_locked_item(
            FF2Item("Victory", ItemClassification.progression, None, self.player)
        )
        goal_region.locations.append(victory_location)

    def set_rules(self) -> None:
        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Victory", self.player)

    def fill_slot_data(self) -> Dict:
        data: Dict = {
            "death_link":      bool(self.options.death_link.value),
            "zone_boundaries": ZONE_BOUNDARIES,
        }
        if self.options.level_shuffle:
            data["level_shuffle"] = self.level_shuffle
        return data
