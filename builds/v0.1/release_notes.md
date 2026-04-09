# Release v0.1

First working apworld! 
Note: Only windows is supported at present.

## Items
* Progressive Fish (allows  access to next area)
* 1-up

## Locations
* Level completion
* Growth stages (2 per non-bonus level)

## Setup
Just install as you would any other apworld (put in custom_worlds, or double click to install automatically), generate template yamls to get the yaml file if needed, have your host generate/host the game, and then do the following:

1. Open FF2 to the title screen
2. Create a new user. **This is very important:** The game will write over your save if you do not do this!
3. Launch the feeding frenzy 2 client via the archipelago launcher (DO NOT start playing the game until you have connected. If you ever get disconnected, return to the title screen to reconnect, as important data is captured on initial loading).
4. Connect to the server, and begin playing!

Contact xLander on discord (see: #future-game-design Feeding Frenzy 2 thread) if you run into any issues, and feel free to open an issue or submit pull requests.

## Current next steps:
At present, the game is playable. However, I have several things in mind already for the next update. For one, I want receiving a deathlink to trigger the routine that runs when you're eaten, rather than just decrementing the amount of lives you have as it does now. This will require tracing back the execution flow at runtime and mapping memory addresses, which is a process I'm currently in the middle of doing. 
