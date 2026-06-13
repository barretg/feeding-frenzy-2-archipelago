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
        classification=ItemClassification.useful,
    ),
    "Suck": FF2ItemData(
        code=BASE_ID + 4,
        classification=ItemClassification.useful,
    ),
}

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
}
