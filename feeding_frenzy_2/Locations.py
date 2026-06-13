from typing import Dict, NamedTuple, Optional
from BaseClasses import Location


class FF2Location(Location):
    game = "Feeding Frenzy 2"


class FF2LocationData(NamedTuple):
    code: Optional[int]
    level_id: int    # 0-indexed
    zone: int        # which zone this location belongs to


# 1-indexed bonus levels — these have no growth stage checks, only completion
BONUS_LEVELS = frozenset({4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60})

# Total levels 1–60. Level 60 is the goal — no location entry.
TOTAL_LEVELS = 60

# Zone boundaries: 0-indexed level ID where each new zone starts.
# Zone N requires N Progressive Fish items to access.
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 45, 48, 51, 54, 57]

# Location ID base
LOC_BASE = 0xFF20000 + 0x1000


def zone_for_level_id(level_id: int) -> int:
    for i in range(len(ZONE_BOUNDARIES) - 1, -1, -1):
        if level_id >= ZONE_BOUNDARIES[i]:
            return i
    return 0


def fish_required_for_zone(zone: int) -> int:
    """Number of Progressive Fish needed to access a zone."""
    return zone


def _build_location_table() -> Dict[str, FF2LocationData]:
    table: Dict[str, FF2LocationData] = {}
    for level_1 in range(1, TOTAL_LEVELS):   # 1–59 inclusive; 60 is goal only
        level_id = level_1 - 1
        zone     = zone_for_level_id(level_id)
        is_bonus = level_1 in BONUS_LEVELS

        if not is_bonus:
            table[f"Level {level_1} - Stage 1"] = FF2LocationData(
                code=LOC_BASE + level_id * 3 + 0,
                level_id=level_id,
                zone=zone,
            )
            table[f"Level {level_1} - Stage 2"] = FF2LocationData(
                code=LOC_BASE + level_id * 3 + 1,
                level_id=level_id,
                zone=zone,
            )
        table[f"Level {level_1} - Complete"] = FF2LocationData(
            code=LOC_BASE + level_id * 3 + 2,
            level_id=level_id,
            zone=zone,
        )
    return table


LOCATION_TABLE: Dict[str, FF2LocationData] = _build_location_table()

location_name_to_id: Dict[str, int] = {
    name: data.code
    for name, data in LOCATION_TABLE.items()
    if data.code is not None
}

location_descriptions: Dict[str, str] = {
    f"Level {level_1} - Stage 1": f"Reach the first growth stage in level {level_1}."
    for level_1 in range(1, TOTAL_LEVELS)
    if level_1 not in BONUS_LEVELS
} | {
    f"Level {level_1} - Stage 2": f"Reach the second growth stage in level {level_1}."
    for level_1 in range(1, TOTAL_LEVELS)
    if level_1 not in BONUS_LEVELS
} | {
    f"Level {level_1} - Complete": f"Complete level {level_1}."
    for level_1 in range(1, TOTAL_LEVELS)
}
