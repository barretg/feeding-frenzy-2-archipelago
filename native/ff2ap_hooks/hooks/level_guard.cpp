#include "level_guard.h"

#include <windows.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <string>
#include <thread>

#include "MinHook.h"
#include "../ipc.h"
#include "../state.h"

// Struct offsets from Client.py (OFFSET_* constants) — level_obj is the same persistent
// object across the whole session, reused in place on every level (re)load, not
// reallocated (confirmed live this session: repeated hits at the init function returned
// the same pointer across many level transitions within one process run).
namespace hooks {
namespace {

constexpr uintptr_t kLevelInitOffset = 0x9C050;

constexpr int OFFSET_LIVES          = 0x10;
constexpr int OFFSET_SCORE          = 0x14;
constexpr int OFFSET_LEVEL_ID       = 0x28;
constexpr int OFFSET_SCORE_SNAPSHOT = 0x30;
constexpr int OFFSET_LIVES_SNAPSHOT = 0x34;
constexpr int OFFSET_PROGRESS       = 0x40;

constexpr auto kPollInterval = std::chrono::milliseconds(2);

void* g_original = nullptr;
// Plain-identifier alias so the inline __asm block below can reference it directly —
// MSVC's inline assembler doesn't reliably parse qualified names like state::g_level_obj.
using state::g_level_obj;

inline int32_t Read(uintptr_t addr) {
    return *reinterpret_cast<volatile int32_t*>(addr);
}

inline void Write(uintptr_t addr, int32_t value) {
    *reinterpret_cast<volatile int32_t*>(addr) = value;
}

// Naked: no register save/restore needed here (unlike boundary_gate) since we only read
// eax into a global and pass every register/stack byte through to the original
// untouched — `mov` doesn't affect any register other than its own operands or flags.
__declspec(naked) void Detour_LevelInit() {
    __asm {
        mov dword ptr [g_level_obj], eax
        jmp dword ptr [g_original]
    }
}

void PollLoop() {
    // TODO(Phase 2 step 2 verification): remove once player_fish/sub_object are wired
    // into something with its own live confirmation (DeathLink) — this only exists to
    // prove the capture hook fires without flooding the log on every call.
    intptr_t last_logged_fish = 0;

    for (;;) {
        std::this_thread::sleep_for(kPollInterval);

        const intptr_t fish = state::g_player_fish;
        if (fish != last_logged_fish) {
            last_logged_fish = fish;
            char buf[128];
            wsprintfA(buf, "player_fish captured: 0x%08X sub_object: 0x%08X",
                      static_cast<unsigned int>(fish), static_cast<unsigned int>(state::g_sub_object));
            ipc::Log(buf);
        }

        const uintptr_t obj = static_cast<uintptr_t>(g_level_obj);
        if (!obj) {
            continue;
        }
        const int allowed  = ipc::g_allowed_max.load(std::memory_order_relaxed);
        const int level_id = Read(obj + OFFSET_LEVEL_ID);
        if (level_id <= allowed) {
            continue;
        }

        const int gateway        = level_id - 1;
        const int score_snapshot = Read(obj + OFFSET_SCORE_SNAPSHOT);
        const int lives_snapshot = Read(obj + OFFSET_LIVES_SNAPSHOT);
        Write(obj + OFFSET_LEVEL_ID, gateway);
        Write(obj + OFFSET_SCORE,    score_snapshot);
        Write(obj + OFFSET_LIVES,    lives_snapshot);
        Write(obj + OFFSET_PROGRESS, 0);

        ipc::QueueSend("LEVEL_COMPLETE " + std::to_string(gateway));
    }
}

}  // namespace

bool InstallLevelGuard() {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    void* target = reinterpret_cast<void*>(base + kLevelInitOffset);

    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_LevelInit), &g_original) != MH_OK) {
        return false;
    }
    if (MH_EnableHook(target) != MH_OK) {
        return false;
    }
    std::thread(PollLoop).detach();
    return true;
}

}  // namespace hooks
