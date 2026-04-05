from typing import Dict, List, Optional
from BaseClasses import Item, ItemClassification, Location, Region, Tutorial
from worlds.AutoWorld import WebWorld, World
from Options import Toggle


# ── Constants ────────────────────────────────────────────────────────────────

GAME_NAME = "Feeding Frenzy 2"

# 1-indexed bonus levels (no growth stage checks)
BONUS_LEVELS = {4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60}

# Total levels: 1–60 (level 60 is the goal, not a location)
TOTAL_LEVELS = 60

# Zone boundaries: 0-indexed level ID where each new zone starts.
# Player needs N Progressive Fish to access zone N (zone 0 is free).
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 49, 52, 55, 58, 61]
# Zone N covers levels [ZONE_BOUNDARIES[N], ZONE_BOUNDARIES[N+1] - 1] (0-indexed)
# Zone 0: levels 0–7   (levels 1–8  in 1-indexed)
# Zone 1: levels 8–15  (levels 9–16)
# ...etc

PROGRESSIVE_FISH_COUNT = 11   # number actually needed
EXTRA_FISH             = 2    # extra copies as filler
TOTAL_FISH_ITEMS       = PROGRESSIVE_FISH_COUNT + EXTRA_FISH  # 13

# Item IDs
BASE_ID          = 0xFF2_0000  # 0xFF20000 — "FF2" as a mnemonic
ITEM_PROGRESSIVE_FISH = BASE_ID + 1
ITEM_1UP              = BASE_ID + 2

# Location IDs
# Layout per normal level: BASE + (level_id * 3) + 0 = stage 1
#                           BASE + (level_id * 3) + 1 = stage 2
#                           BASE + (level_id * 3) + 2 = completion
# Layout per bonus level:  BASE + (level_id * 3) + 2 = completion only
# level 60 (id 59) is goal only — no location
LOC_BASE = BASE_ID + 0x1000


# ── Helpers ──────────────────────────────────────────────────────────────────

def level_1indexed_to_id(level_1indexed: int) -> int:
    """Convert 1-indexed level number to 0-indexed level ID."""
    return level_1indexed - 1


def zone_for_level_id(level_id: int) -> int:
    """Return which zone (0-indexed) a level belongs to."""
    for i in range(len(ZONE_BOUNDARIES) - 1, -1, -1):
        if level_id >= ZONE_BOUNDARIES[i]:
            return i
    return 0


def fish_required_for_level_id(level_id: int) -> int:
    """Number of Progressive Fish items needed to access this level."""
    return zone_for_level_id(level_id)


def location_id_for(level_id: int, slot: int) -> int:
    """
    slot 0 = stage 1 growth check
    slot 1 = stage 2 growth check
    slot 2 = level completion check
    """
    return LOC_BASE + (level_id * 3) + slot


def location_name_for(level_1indexed: int, slot: int) -> str:
    if slot == 0:
        return f"Level {level_1indexed} - Stage 1"
    elif slot == 1:
        return f"Level {level_1indexed} - Stage 2"
    else:
        return f"Level {level_1indexed} - Complete"


def build_location_table() -> Dict[str, int]:
    """Build the full location name → id table."""
    table: Dict[str, int] = {}
    for level_1 in range(1, TOTAL_LEVELS):   # 1 to 59 inclusive (60 is goal)
        level_id = level_1indexed_to_id(level_1)
        is_bonus = level_1 in BONUS_LEVELS
        if not is_bonus:
            table[location_name_for(level_1, 0)] = location_id_for(level_id, 0)
            table[location_name_for(level_1, 1)] = location_id_for(level_id, 1)
        table[location_name_for(level_1, 2)] = location_id_for(level_id, 2)
    return table


LOCATION_TABLE: Dict[str, int] = build_location_table()
TOTAL_LOCATIONS = len(LOCATION_TABLE)  # should be 150
TOTAL_1UP_ITEMS = TOTAL_LOCATIONS - TOTAL_FISH_ITEMS  # 137


# ── Item / Location classes ───────────────────────────────────────────────────

class FF2Item(Item):
    game = GAME_NAME


class FF2Location(Location):
    game = GAME_NAME


# ── Options ──────────────────────────────────────────────────────────────────

class DeathLink(Toggle):
    """When you lose a life, everyone loses a life. When you receive a death, you lose a life."""
    display_name = "Death Link"


FF2Options = {
    "death_link": DeathLink,
}


# ── Web world ────────────────────────────────────────────────────────────────

class FF2WebWorld(WebWorld):
    theme = "ocean"
    tutorials = [Tutorial(
        tutorial_name="Setup Guide",
        description="A guide to setting up Feeding Frenzy 2 Archipelago.",
        language="English",
        file_name="setup_en.md",
        link="setup/en",
        authors=["archipelago"]
    )]


# ── World ────────────────────────────────────────────────────────────────────

class FF2World(World):
    """
    Feeding Frenzy 2: Shipwreck Showdown is a casual arcade game where you
    play as a fish eating smaller fish to grow bigger. Collect Progressive Fish
    items to unlock new zones, and reach the final boss to win!
    """

    game             = GAME_NAME
    web              = FF2WebWorld()
    option_definitions = FF2Options

    item_name_to_id: Dict[str, int] = {
        "Progressive Fish": ITEM_PROGRESSIVE_FISH,
        "1-Up":             ITEM_1UP,
    }

    location_name_to_id: Dict[str, int] = LOCATION_TABLE

    def create_item(self, name: str) -> FF2Item:
        if name == "Progressive Fish":
            classification = ItemClassification.progression
        else:
            classification = ItemClassification.filler
        return FF2Item(name, classification, self.item_name_to_id[name], self.player)

    def create_items(self) -> None:
        for _ in range(TOTAL_FISH_ITEMS):
            self.multiworld.itempool.append(self.create_item("Progressive Fish"))
        for _ in range(TOTAL_1UP_ITEMS):
            self.multiworld.itempool.append(self.create_item("1-Up"))

    def create_regions(self) -> None:
        # One region per zone plus Menu and Goal
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        # Zone regions: Zone 0 through Zone 10
        zone_regions: List[Region] = []
        for zone_idx in range(len(ZONE_BOUNDARIES)):
            zone_region = Region(f"Zone {zone_idx}", self.player, self.multiworld)
            self.multiworld.regions.append(zone_region)
            zone_regions.append(zone_region)

        # Goal region
        goal_region = Region("Goal", self.player, self.multiworld)
        self.multiworld.regions.append(goal_region)

        # Connect Menu → Zone 0 (free, no fish required)
        menu_region.connect(zone_regions[0])

        # Connect Zone N → Zone N+1 (requires N+1 Progressive Fish)
        for zone_idx in range(len(ZONE_BOUNDARIES) - 1):
            fish_needed = zone_idx + 1
            source = zone_regions[zone_idx]
            target = zone_regions[zone_idx + 1]
            source.connect(
                target,
                rule=lambda state, n=fish_needed:
                    state.has("Progressive Fish", self.player, n)
            )

        # Connect final zone → Goal (requires all 11 fish)
        zone_regions[-1].connect(
            goal_region,
            rule=lambda state:
                state.has("Progressive Fish", self.player, PROGRESSIVE_FISH_COUNT)
        )

        # Place locations into their zone regions
        for loc_name, loc_id in LOCATION_TABLE.items():
            # Parse level number from name e.g. "Level 5 - Stage 1"
            level_1 = int(loc_name.split(" ")[1])
            level_id = level_1indexed_to_id(level_1)
            zone_idx = zone_for_level_id(level_id)

            location = FF2Location(self.player, loc_name, loc_id, zone_regions[zone_idx])
            zone_regions[zone_idx].locations.append(location)

        # Victory event at goal region
        victory_location = FF2Location(self.player, "Final Boss", None, goal_region)
        victory_location.place_locked_item(
            FF2Item("Victory", ItemClassification.progression, None, self.player)
        )
        goal_region.locations.append(victory_location)

    def set_rules(self) -> None:
        # Zone access rules are set via region connections in create_regions.
        # Individual location rules: growth stage checks require being in the
        # right zone which is already enforced by the region they live in.
        # Level completion checks within a zone have no additional rules.
        # The goal requires Victory event.
        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Victory", self.player)

    def fill_slot_data(self) -> Dict:
        return {
            "death_link": bool(self.multiworld.death_link[self.player].value),
            "zone_boundaries": ZONE_BOUNDARIES,
        }
