#include <windows.h>

#include "MinHook.h"
#include "ipc.h"
#include "hooks/boundary_gate.h"
#include "hooks/level_guard.h"
#include "hooks/player_fish.h"

namespace {

DWORD WINAPI WorkerThread(LPVOID) {
    if (MH_Initialize() != MH_OK) {
        return 1;
    }
    hooks::InstallBoundaryGate();
    hooks::InstallLevelGuard();
    hooks::InstallPlayerFish();
    ipc::Init();  // background connect/receive loop; never returns
    return 0;
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        // Hook install touches the game's code section and the IPC connect loop blocks
        // on network I/O — both must happen off the loader-lock-holding thread that's
        // running DllMain.
        CreateThread(nullptr, 0, WorkerThread, nullptr, 0, nullptr);
    }
    return TRUE;
}
