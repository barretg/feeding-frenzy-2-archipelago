#include "boss_hp.h"

#include <windows.h>

#include <cstdint>

#include "MinHook.h"
#include "../state.h"

// The hooked instruction (`inc dword ptr [ecx+0xB4]`) has real gameplay side effects —
// it's the game's own hit counter, not a passive capture point — so the trampoline must
// still run it for real. MinHook's relocated-original-bytes trampoline (reached via the
// tail jmp below) does exactly that; our detour only observes ecx before falling through.
namespace hooks {
namespace {

constexpr uintptr_t kBossHpOffset = 0xA908A;

void* g_original = nullptr;
using state::g_boss_hp_addr;

// Naked: only reads ecx (base register of the instruction we're hooking) into a global —
// doesn't touch any register the surrounding code depends on. eax saved/restored anyway.
__declspec(naked) void Detour_BossHp() {
    __asm {
        push eax
        lea eax, [ecx + 0B4h]
        mov dword ptr [g_boss_hp_addr], eax
        pop eax
        jmp dword ptr [g_original]
    }
}

}  // namespace

bool InstallBossHp() {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    void* target = reinterpret_cast<void*>(base + kBossHpOffset);

    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_BossHp), &g_original) != MH_OK) {
        return false;
    }
    return MH_EnableHook(target) == MH_OK;
}

}  // namespace hooks
