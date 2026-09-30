from dataclasses import dataclass
from Options import Toggle, Range, PerGameCommonOptions


class DeathLink(Toggle):
    """When you lose a life, everyone dies. When you receive a death, you lose a life."""
    display_name = "Death Link"

class DeathLinkAmnesty(Range):
    """Set number of deaths to ignore before sending out a deathlink."""
    display_name = "Death Link Amnesty"
    range_start = 0
    range_end = 10
    default = 2

class LevelShuffle(Toggle):
    """Randomize which level content appears at each map slot.
    Bonus levels (which have only a completion check) may appear at any position."""
    display_name = "Level Shuffle"


class Powerupsanity(Toggle):
    """Power-ups (Speed Boost, Frenzy, Fury, Stun, Shield, Lure, Light, Time, Shrink Shroom,
    Starfish, 1-Up) cannot be picked up until their item is received. Locked power-ups are
    passed through untouched."""
    display_name = "Power-up-sanity"


class Frenzsanity(Toggle):
    """Adds 5 Progressive Frenzy items. With none, the Frenzy multiplier never builds; each one
    raises the cap by one tier, up to Mega Frenzy."""
    display_name = "Frenzsanity"


@dataclass
class FF2Options(PerGameCommonOptions):
    death_link:         DeathLink
    death_link_amnesty: DeathLinkAmnesty
    level_shuffle:      LevelShuffle
    powerupsanity:      Powerupsanity
    frenzsanity:        Frenzsanity
