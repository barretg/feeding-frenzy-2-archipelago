#pragma once

namespace hooks {

// Installs a MinHook detour on the level-object init routine (popcapgame1.exe base +
// 0x9C050 — the same function Client.py's old one-shot capture breakpoint targets at
// its mid-function offset 0x9C064) to cache the level object pointer on every level
// (re)load, then starts a tight in-process poll loop that reverts level_id/score/lives/
// progress the instant level_id exceeds the allowed max.
//
// This exists because the boundary_gate hook alone (clamping mode0MaxStage) does not
// stop the actual playable level from advancing — confirmed live: the "continue to next
// level" flow does not consult mode0MaxStage at all. A 2ms in-process poll is ~50x
// tighter than Client.py's old 100ms external poll and has no IPC/syscall overhead per
// check, so it closes the race in practice without needing to locate the exact
// instruction that commits the new level_id (which proved hard to isolate live).
bool InstallLevelGuard();

}  // namespace hooks
