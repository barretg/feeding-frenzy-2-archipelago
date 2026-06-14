from dataclasses import dataclass
from Options import Toggle, PerGameCommonOptions


class DeathLink(Toggle):
    """When you lose a life, everyone loses a life. When you receive a death, you lose a life."""
    display_name = "Death Link"


class LevelShuffle(Toggle):
    """Randomize which level content appears at each map slot.
    Bonus levels (which have only a completion check) may appear at any position."""
    display_name = "Level Shuffle"


@dataclass
class FF2Options(PerGameCommonOptions):
    death_link:    DeathLink
    level_shuffle: LevelShuffle
