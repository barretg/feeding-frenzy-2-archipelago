from dataclasses import dataclass
from Options import DefaultOnToggle, Toggle, PerGameCommonOptions


class DeathLink(Toggle):
    """When you lose a life, everyone loses a life. When you receive a death, you lose a life."""
    display_name = "Death Link"


class LevelShuffle(Toggle):
    """Randomize which level content appears at each map slot.
    Bonus levels (which have only a completion check) may appear at any position."""
    display_name = "Level Shuffle"


class Powerupsanity(DefaultOnToggle):
    """Power-ups (Speed Boost, Frenzy, Fury, Stun, Shield, Lure, Light, Time, Shrink Shroom,
    Starfish, 1-Up) cannot be picked up until their item is received. Locked power-ups are
    passed through untouched."""
    display_name = "Power-up-sanity"


class Frenzsanity(DefaultOnToggle):
    """Adds 5 Progressive Frenzy items. With none, the Frenzy multiplier never builds; each one
    raises the cap by one tier, up to Mega Frenzy."""
    display_name = "Frenzsanity"


@dataclass
class FF2Options(PerGameCommonOptions):
    death_link:         DeathLink
    level_shuffle:      LevelShuffle
    powerupsanity:      Powerupsanity
    frenzsanity:        Frenzsanity
