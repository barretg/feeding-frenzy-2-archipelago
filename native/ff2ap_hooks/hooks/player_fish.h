#pragma once

namespace hooks {

// Installs a MinHook detour on the player-fish object's entry method (popcapgame1.exe
// base + 0x38D40 — a thiscall, ecx = player_fish; Client.py's old one-shot hardware
// breakpoint targeted the mid-function offset 0x38D47, right after `mov ebx,ecx`).
// Caches player_fish and sub_object ([player_fish+0x8C]) into state:: on every call —
// fires naturally on every level entry, no explicit re-arm needed from Python.
bool InstallPlayerFish();

}  // namespace hooks
