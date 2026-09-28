#include "powerup_gate.h"

#include <windows.h>

#include <cstdint>
#include <cstdlib>
#include <string>

#include "MinHook.h"
#include "../ipc.h"

namespace hooks {
namespace {

// Eater::OnCollide(Actor* victim). Runs victim->vt[0xA8]/[0x78]/[0xC0] checks, then
// eater->vt[0x10] (Eat, 0x47A250) which queues the victim into player+0xFC; the queue
// is drained at 0x42A98C, which calls victim->vt[0x90] (OnEaten, the power-up effect).
// Confirmed live that fish, stars and power-ups all pass through here.
constexpr uintptr_t kOnCollideOffset = 0x3DEE0;

// Actor vtables (RTTI-confirmed, image base 0x400000) and the POWERUPS_UNLOCKED bit that
// gates each. Bit order must match Client.py's POWERUP_ITEMS.
struct GatedClass {
    uintptr_t vtable_offset;
    int bit;
};
constexpr GatedClass kGatedClasses[] = {
    {0x154FE4, 0},  // BonusSpeed
    {0x154544, 1},  // Bonus2X
    {0x154674, 2},  // BonusFury
    {0x155244, 3},  // BonusStun
    {0x154D5C, 4},  // BonusShield
    {0x154C24, 5},  // BonusLure
    {0x154AFC, 6},  // BonusLight
    {0x155384, 7},  // BonusTime
    {0x154E8C, 8},  // BonusShrinkShroom
    {0x155114, 9},  // BonusStar
    {0x15560C, 9},  // MermaidStar (dropped by the mermaid)
    {0x1543F4, 10}, // Bonus1Up
};
constexpr int kPowerupCount = 11;
constexpr uint32_t kAllUnlocked = (1u << kPowerupCount) - 1;

using OnCollideFn = void(__thiscall*)(void* self, void* victim);
OnCollideFn g_original = nullptr;
uintptr_t g_base = 0;
volatile uint32_t g_unlocked = kAllUnlocked;

bool IsLocked(void* victim) {
    if (!victim) {
        return false;
    }
    uintptr_t vt = *reinterpret_cast<uintptr_t*>(victim) - g_base;
    for (const GatedClass& c : kGatedClasses) {
        if (vt == c.vtable_offset) {
            return (g_unlocked & (1u << c.bit)) == 0;
        }
    }
    return false;
}

// __fastcall stands in for __thiscall on a detour: ecx = self, edx = unused, stack arg
// = victim, callee cleans 4 bytes, matching the original's `ret 4`.
void __fastcall Detour_OnCollide(void* self, void* /*edx*/, void* victim) {
    if (IsLocked(victim)) {
        return;
    }
    g_original(self, victim);
}

void HandleLine(const std::string& line) {
    if (line.rfind("POWERUPS_UNLOCKED ", 0) == 0) {
        g_unlocked = static_cast<uint32_t>(strtoul(line.c_str() + 18, nullptr, 10)) & kAllUnlocked;
        ipc::Log("Power-ups unlocked mask = " + std::to_string(g_unlocked));
    }
}

}  // namespace

bool InstallPowerupGate() {
    g_base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    ipc::RegisterHandler(HandleLine);

    void* target = reinterpret_cast<void*>(g_base + kOnCollideOffset);
    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_OnCollide),
                      reinterpret_cast<void**>(&g_original)) != MH_OK) {
        return false;
    }
    return MH_EnableHook(target) == MH_OK;
}

}  // namespace hooks
