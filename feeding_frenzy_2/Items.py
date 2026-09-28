from typing import Dict, NamedTuple, Optional
from BaseClasses import Item, ItemClassification


class FF2Item(Item):
    game = "Feeding Frenzy 2"


class FF2ItemData(NamedTuple):
    code: Optional[int]
    classification: ItemClassification


# Base ID — "FF2" as a mnemonic
BASE_ID = 0xFF20000

ITEM_TABLE: Dict[str, FF2ItemData] = {
    "Progressive Fish": FF2ItemData(
        code=BASE_ID + 1,
        classification=ItemClassification.progression,
    ),
    "1-Up": FF2ItemData(
        code=BASE_ID + 2,
        classification=ItemClassification.filler,
    ),
    "Dash": FF2ItemData(
        code=BASE_ID + 3,
        classification=ItemClassification.progression,
    ),
    "Suck": FF2ItemData(
        code=BASE_ID + 4,
        classification=ItemClassification.progression,
    ),
    "Progressive Frenzy": FF2ItemData(
        code=BASE_ID + 5,
        classification=ItemClassification.useful,
    ),
}

# Power-up unlocks. Order defines the POWERUPS_UNLOCKED bit index, which must match
# kGatedClasses in native/ff2ap_hooks/hooks/powerup_gate.cpp.
_P = ItemClassification.progression
_U = ItemClassification.useful
POWERUP_ITEM_DATA = (
    ("Power-up: Speed Boost",   _U),
    ("Power-up: Frenzy",        _P),
    ("Power-up: Fury",          _U),
    ("Power-up: Stun",          _U),
    ("Power-up: Shield",        _U),
    ("Power-up: Lure",          _U),
    ("Power-up: Light",         _P),
    ("Power-up: Time",          _P),
    ("Power-up: Shrink Shroom", _U),
    ("Power-up: Starfish",      _U),  # both the plain star bubble and the mermaid's star
    ("Power-up: 1-Up",          _U),  # the in-level 1-Up bubble
)
POWERUP_ITEMS = tuple(name for name, _ in POWERUP_ITEM_DATA)

for _i, (_name, _cls) in enumerate(POWERUP_ITEM_DATA):
    ITEM_TABLE[_name] = FF2ItemData(code=BASE_ID + 0x10 + _i, classification=_cls)

item_name_to_id: Dict[str, int] = {
    name: data.code
    for name, data in ITEM_TABLE.items()
    if data.code is not None
}

item_descriptions: Dict[str, str] = {
    "Progressive Fish": "Unlocks access to the next fish zone, allowing you to progress further.",
    "1-Up":             "Grants one extra life.",
    "Dash":             "Enables the ability to dash by clicking.",
    "Suck":             "Enables the ability to suck in nearby fish by right-clicking.",
    "Progressive Frenzy": "Raises how high the Frenzy multiplier can climb. With none, Frenzy never "
                          "builds; five reach Mega Frenzy.",
    **{name: f"Allows picking up the {name.removeprefix('Power-up: ')} power-up." for name in POWERUP_ITEMS},
}
