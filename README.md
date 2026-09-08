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
   * The client copies its mod DLLs (`dsound.dll` and `ff2ap_hooks.dll`) into that folder and then starts the game. The Steam release is started through Steam so it can provide `steam.dll`.
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

### Linux, SteamOS and Steam Deck
Everything above works the same on Linux. The client runs natively; only the game runs under Proton, and the two talk over a local connection that crosses that boundary without any special setup. Nothing is written outside your home directory, so read-only distros like SteamOS and Bazzite are fine.

A few Linux-specific notes:

* **Run Archipelago natively, not under Wine or Proton.** Only the game runs under Proton. The client is ordinary Python that talks to the mod over a local connection, and its launch and prefix-setup logic all assumes a native Linux process.
* **Use Desktop Mode**, at least for setup. Picking the install directory needs a file dialog.
* **Steam release:** the client sets the `dsound` DLL override inside the game's Proton prefix for you. That prefix only exists after Proton has created it, so if you've never run the game, the first **Launch Game** will start it unmodded. Close it and press **Launch Game** again.
* **Check that it took.** Type `/status` in the client. `Native hooks connected: True` means the game found the client and the mod is live. If it says `False` while the game is running, the DLL override didn't apply.
  * If the client reports that it couldn't set the override, set it yourself in the game's Steam launch options instead: `WINEDLLOVERRIDES="dsound=n,b" %command%`
* **Disc release:** launched through [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher) if it's installed, otherwise plain `wine`. If you have neither, add the exe to Steam as a non-Steam game with Proton enabled and the launch options above.
* **Don't use `/fullscreen` in Steam Deck Game Mode.** Gamescope already scales the game, and the window and cursor changes the command makes don't behave properly there. It works normally in Desktop Mode.

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

