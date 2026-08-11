# Feeding Frenzy 2 Archipelago!

## Items
* Progressive Fish (allows  access to next area)
* Dash (includes jump)
* Suck
* 1-up

## Locations
* Level completion
* Growth stages (2 per non-bonus level)

## Options
* `death_link` — When you lose a life, everyone loses a life (and vice versa).
* `level_shuffle` — Randomize which level's content appears at each map slot.

## Setup
Install as you would any other apworld (put it in `custom_worlds`, or double click to install automatically), generate template yamls to get the yaml file if needed, have your host generate/host the game, and then do the following:

1. Launch the **Feeding Frenzy 2 Client** from the Archipelago Launcher. Do **not** start the game yourself -- the client has to start it (see below).
2. Click **Launch Game** in the client.
   * The first time, you'll be asked to pick your Feeding Frenzy 2 install directory (the folder containing `FeedingFrenzy2.exe` for the original release, or `FeedingFrenzyTwo.exe` for the Steam "Deluxe" release). It's remembered after that.
   * The client copies its mod DLLs (`dsound.dll`, `ff2ap_hooks.dll`, plus a copy of the system `dsound.dll` as `dsound_real.dll`) into that folder and then starts the game. The Steam release is started through Steam so it can provide `steam.dll`.
3. At the title screen, create a **new user**. **This is very important:** the randomizer writes level-progress data into whichever profile you use, so use a fresh one rather than your normal save.
4. Connect to the server in the client.
5. (Optional) Type `/fullscreen` in the client for borderless fullscreen with scaled mouse input.
6. Play!

The game and the client link up over a local connection as soon as both are running, and it reconnects on its own — order doesn't matter much, and you no longer have to return to the title screen after a disconnect. Item and progression state is re-sent every time the link comes back.

### Client commands
* `/fullscreen` — Toggle borderless windowed fullscreen.
* `/directory "<path>"` — Set the install directory manually instead of using the file picker.
* `/status` — Show the last known level/stage, fish received, and whether the game is connected.
* `/uninstall` — Remove the mod DLLs from the install directory so the game launches unmodified again (close the game first).

### Launching the game outside Archipelago
Once the DLLs are installed, the mod loads on **every** launch of the game, including launches from Steam or the desktop shortcut. Without the client running it just sits idle retrying the connection, but if you want the game fully vanilla again, run `/uninstall` in the client.

If for whatever reason things don't work, close both the game and the client, then start over from step 1.

Contact xLander or littleko52 on discord (see: #future-game-design Feeding Frenzy 2 thread) if you run into any issues, and feel free to open an issue or submit pull requests.

# Future:
At present, the game is playable, but there's much still to do. Below you'll find the plans.

## Planned Locations
* Score checks (10k, 50k, 100k, etc.)
* Fish-sanity (Eat every type of fish you can)
* Maybe some checks for eating golden fish?
* Black Pearls

## Planned Progression Items
* Movement: Dash, Jumping, Tail bites, Suck, Plankton (the stuff that increases angler's brightness)
* Progressive Frenzy (lets you increase your frenzy multiplier, starts unable to increase)
* Progressive checkpoint? (maybe 2 of these per fish or total, lets you not restart from the smallest growth size on death, but checkpoint at growth in levels)
* Power-up access

## Planned Filler Items
* 1-ups, and other power-ups
* Score bonuses, etc.

## Other Planned Features
* Sprite randomizer
* Music randomizer

