# Feeding Frenzy 2 AP - Release v0.8

## What's new:
* Power-up randomization
* Progressive Frenzy unlocks
* Deathlink Amnesty

## Planned Features
* Score-based checks
* Separate jump/dash/cure poison

## Setup
Install as you would any other apworld (put it in `custom_worlds`, or double click to install automatically), generate template yamls to get the yaml file if needed, have your host generate/host the game, and then do the following:

1. Launch the **Feeding Frenzy 2 Client** from the Archipelago Launcher. Do **not** start the game yourself: the client has to start it (see below).
2. Click **Launch Game** in the client.
   * The first time, you'll be asked to pick your Feeding Frenzy 2 install directory (the folder containing `FeedingFrenzy2.exe` for the original release, or `FeedingFrenzyTwo.exe` for the Steam "Deluxe" release). It's remembered after that.
   * The client copies its mod DLLs (`dsound.dll`, `ff2ap_hooks.dll`, plus a copy of the system `dsound.dll` as `dsound_real.dll`) into that folder and then starts the game. The Steam release is started through Steam so it can provide `steam.dll`.
3. At the title screen, create a **new user**. **This is very important:** the randomizer writes level-progress data into whichever profile you use, so use a fresh one rather than your normal save.
4. Connect to the server in the client.
5. (Optional) Type `/fullscreen` in the client for borderless fullscreen with scaled mouse input.
6. Play!

