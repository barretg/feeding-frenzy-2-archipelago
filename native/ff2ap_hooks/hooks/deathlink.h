#pragma once

namespace hooks {

// Registers the "DEATH_LINK_TRIGGER" IPC handler — calls DEATH_FUNC directly (in-process,
// no more VirtualAllocEx/shellcode/CreateRemoteThread) after the same alive/bonus-level
// checks Client.py used to do externally. The lost-life -> "DEATH_LINK_SEND <lives>"
// direction lives in the poll loop (hooks/level_guard.cpp), alongside the rest of the
// per-tick state watching.
void InstallDeathLink();

}  // namespace hooks
