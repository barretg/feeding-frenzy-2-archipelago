#pragma once

namespace hooks {

// Installs the MinHook detour on UpdateMaxStage (popcapgame1.exe base + 0x9AED0).
// Must be called after MH_Initialize(). Returns false on failure (logged by the caller).
bool InstallBoundaryGate();

}  // namespace hooks
