#pragma once

namespace hooks {

// Installs a MinHook detour on the boss-hit counter instruction (popcapgame1.exe base +
// 0xA908A — `inc dword ptr [ecx+0xB4]`, fires once per hit landed on the final boss).
// Caches the counter's address (ecx+0xB4) into state::g_boss_hp_addr; the poll loop
// (hooks/level_guard.cpp) reads it each tick and fires GOAL at 20 hits, same threshold
// Client.py used externally.
bool InstallBossHp();

}  // namespace hooks
