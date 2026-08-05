#pragma once

namespace hooks {

// Installs the MinHook detour on UpdateMaxStage (popcapgame1.exe base + 0x9AED0).
// Must be called after MH_Initialize(). Returns false on failure (logged by the caller).
bool InstallBoundaryGate();

// Installs the MinHook detour on the level_obj->level_id write site shared by both the
// map-select confirm path and the natural continue-advance path (popcapgame1.exe base +
// 0x11641: `mov [ecx+28],eax`). Clamps the value synchronously before the store commits.
// Must be called after MH_Initialize(). Returns false on failure (logged by the caller).
bool InstallLevelSelectGate();

}  // namespace hooks
