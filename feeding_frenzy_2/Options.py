from dataclasses import dataclass
from Options import Toggle, PerGameCommonOptions


class DeathLink(Toggle):
    """When you lose a life, everyone loses a life. When you receive a death, you lose a life."""
    display_name = "Death Link"


@dataclass
class FF2Options(PerGameCommonOptions):
    death_link: DeathLink
