#include "level_guard.h"

#include <windows.h>

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
//
// This is also where Client.py's old 100ms external poll loop lives now, consolidated
// and running ~50x tighter (2ms, in-process, no syscall per check): boundary enforcement
// (from Phase 1), ordinary stage/level completion reporting, boss-defeat -> GOAL, and
// lost-life -> DEATH_LINK_SEND. Bonus-level filtering and shuffle slot->content mapping
// stay in Python, same as they already do for the boundary-triggered LEVEL_COMPLETE —
// this loop only ever reports raw slot-level/stage numbers.
namespace hooks {
namespace {

constexpr uintptr_t kLevelInitOffset = 0x9C050;

constexpr int OFFSET_LIVES          = 0x10;
constexpr int OFFSET_SCORE          = 0x14;
constexpr int OFFSET_STAGE          = 0x24;
constexpr int OFFSET_LEVEL_ID       = 0x28;
constexpr int OFFSET_SCORE_SNAPSHOT = 0x30;
constexpr int OFFSET_LIVES_SNAPSHOT = 0x34;
constexpr int OFFSET_PROGRESS       = 0x40;

constexpr auto kPollInterval = std::chrono::milliseconds(2);

// Debounce for stage/level-completion reporting only — boundary enforcement below reacts
// to the raw read every tick, on purpose, since that's the whole point of it. This exists
// so a level_id briefly seen mid-reset (the init hook above zeroes it before the real
// target gets written) can't get mistaken for a real transition and desync last_reported_*
// from what actually happened. 2 consecutive 2ms ticks (~4ms) is already tighter than the
// reset window is ever likely to be; it's cheap insurance, not load-bearing precision.
constexpr int kStableTicks = 2;

constexpr int kBossHpGoal = 20;

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
    int stable_level_id     = -1;
    int stable_count        = 0;
    int last_reported_level = -1;
    int last_reported_stage = -1;
    int last_lives          = -1;
    bool goal_sent          = false;

    for (;;) {
        std::this_thread::sleep_for(kPollInterval);

        const uintptr_t obj = static_cast<uintptr_t>(g_level_obj);
        if (!obj) {
            continue;
        }

        const int raw_level_id  = Read(obj + OFFSET_LEVEL_ID);
        const int current_stage = Read(obj + OFFSET_STAGE);
        const int current_lives = Read(obj + OFFSET_LIVES);

        // ── boundary enforcement (Phase 1 — fast path, no debounce) ────────
        const int allowed = ipc::g_allowed_max.load(std::memory_order_relaxed);
        if (raw_level_id > allowed) {
            // Clamp straight to `allowed` in one write rather than raw_level_id - 1: a
            // level-select click can jump arbitrarily far ahead (not just one level past
            // the boundary), and writing intermediate values one per tick let the game's
            // own content loader latch onto whatever the field read as mid-cascade —
            // visually landing on id 8 every time regardless of how far past the boundary
            // the click was, even once this loop had already walked the tracked id down
            // to the correct value.
            const int score_snapshot = Read(obj + OFFSET_SCORE_SNAPSHOT);
            const int lives_snapshot = Read(obj + OFFSET_LIVES_SNAPSHOT);
            Write(obj + OFFSET_LEVEL_ID, allowed);
            Write(obj + OFFSET_SCORE,    score_snapshot);
            Write(obj + OFFSET_LIVES,    lives_snapshot);
            Write(obj + OFFSET_PROGRESS, 0);
            // Only a genuine single-step advance (finishing `allowed` and continuing)
            // represents a real completion worth reporting — a level-select skip ahead
            // didn't complete anything.
            if (raw_level_id == allowed + 1) {
                ipc::QueueSend("LEVEL_COMPLETE " + std::to_string(allowed));
            }
            continue;  // state was just rewritten under us — resample next tick
        }

        // ── debounced stage/level completion reporting ─────────────────────
        if (raw_level_id == stable_level_id) {
            if (stable_count < kStableTicks) {
                ++stable_count;
            }
        } else {
            stable_level_id = raw_level_id;
            stable_count    = 1;
        }

        if (stable_count >= kStableTicks) {
            const int level_id = stable_level_id;

            if (last_reported_stage != -1 && current_stage != last_reported_stage &&
                (current_stage == 1 || current_stage == 2)) {
                ipc::QueueSend("STAGE_COMPLETE " + std::to_string(level_id) + " " +
                               std::to_string(current_stage));
            }

            if (last_reported_level != -1 && level_id == last_reported_level + 1) {
                ipc::QueueSend("LEVEL_COMPLETE " + std::to_string(last_reported_level));
            }

            last_reported_level = level_id;
            last_reported_stage = current_stage;
        }

        // ── boss defeat -> goal ─────────────────────────────────────────────
        const auto boss_addr = static_cast<uintptr_t>(state::g_boss_hp_addr);
        if (boss_addr && !goal_sent && raw_level_id == 59 && Read(boss_addr) >= kBossHpGoal) {
            ipc::QueueSend("GOAL");
            goal_sent = true;
        }

        // ── DeathLink send ───────────────────────────────────────────────
        if (last_lives != -1 && current_lives == last_lives - 1) {
            if (current_lives == state::g_deathlink_suppress_lives) {
                // This life loss is the one hooks/deathlink.cpp just caused via an
                // incoming DeathLink — don't bounce it back out.
                state::g_deathlink_suppress_lives = state::kNoDeathLinkSuppress;
            } else {
                ipc::QueueSend("DEATH_LINK_SEND " + std::to_string(current_lives));
            }
        }
        last_lives = current_lives;
    }
}

// "APPLY_1UP" — the only remaining on-demand game-state write that isn't the boundary
// gate or DeathLink. Lives here (rather than a dedicated file) since it just reuses the
// Read/Write helpers and g_level_obj already in scope.
void HandleLine(const std::string& line) {
    if (line != "APPLY_1UP") {
        return;
    }
    const uintptr_t obj = static_cast<uintptr_t>(g_level_obj);
    if (!obj) {
        ipc::Log("1-Up -- no level object yet, dropping");
        return;
    }
    const int lives = Read(obj + OFFSET_LIVES) + 1;
    Write(obj + OFFSET_LIVES, lives);
    ipc::Log("1-Up applied -- lives: " + std::to_string(lives));
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
    ipc::RegisterHandler(HandleLine);
    std::thread(PollLoop).detach();
    return true;
}

}  // namespace hooks
