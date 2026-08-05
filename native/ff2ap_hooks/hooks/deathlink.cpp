#include "deathlink.h"

#include <windows.h>

#include <cstdint>
#include <string>

#include "../ipc.h"
#include "../state.h"

namespace hooks {
namespace {

constexpr uintptr_t kDeathFuncOffset = 0x4E10;  // DEATH_FUNC = base + this
constexpr int kAliveOffset       = 0x78;  // OFFSET_ALIVE_PTR, from sub_object
constexpr int kRespawnFlagOffset = 0x98;  // OFFSET_RESPAWN_FLAG, from player_fish
constexpr int kLevelIdOffset     = 0x28;  // OFFSET_LEVEL_ID, from level_obj
constexpr int kLivesOffset       = 0x10;  // OFFSET_LIVES, from level_obj

using DeathFn = void(__thiscall*)(void*);

inline int32_t Read(uintptr_t addr) {
    return *reinterpret_cast<volatile int32_t*>(addr);
}

inline void Write(uintptr_t addr, int32_t value) {
    *reinterpret_cast<volatile int32_t*>(addr) = value;
}

void TriggerDeathLink() {
    const auto player_fish = static_cast<uintptr_t>(state::g_player_fish);
    const auto sub_object  = static_cast<uintptr_t>(state::g_sub_object);
    if (!player_fish || !sub_object) {
        ipc::Log("DeathLink -- no valid fish pointer, dropping");
        return;
    }

    const auto level_obj = static_cast<uintptr_t>(state::g_level_obj);
    if (level_obj) {
        const int slot       = Read(level_obj + kLevelIdOffset);
        const int content_id = state::ContentLevel(slot);
        if (state::IsBonusContentLevel(content_id)) {
            ipc::Log("DeathLink -- bonus content, dropping");
            return;
        }
    }

    if (Read(sub_object + kAliveOffset) == 0) {
        ipc::Log("DeathLink -- player not spawned, dropping");
        return;
    }

    // Arm echo suppression before triggering — see state.h's g_deathlink_suppress_lives
    // comment. Must happen before the death actually lands so the poll loop can never
    // observe the life decrease before the suppression is armed.
    if (level_obj) {
        const int lives_after = Read(level_obj + kLivesOffset) - 1;
        state::g_deathlink_suppress_lives = lives_after;
    }

    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    auto fn   = reinterpret_cast<DeathFn>(base + kDeathFuncOffset);
    fn(reinterpret_cast<void*>(sub_object));

    Write(player_fish + kRespawnFlagOffset, 0);
    ipc::Log("DeathLink -- death triggered");
}

void HandleLine(const std::string& line) {
    if (line == "DEATH_LINK_TRIGGER") {
        TriggerDeathLink();
    }
}

}  // namespace

void InstallDeathLink() {
    ipc::RegisterHandler(HandleLine);
}

}  // namespace hooks
