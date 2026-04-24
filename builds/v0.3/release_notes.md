# Release v0.3
Deathlink now properly gated to only trigger while a level is in progress, and properly reference the current level's player object instead of the stale one, preventing most crashes.

One known crash remains: exiting to menu mid-level may result in a crash if you receive a deathlink before entering another level due to use after free.