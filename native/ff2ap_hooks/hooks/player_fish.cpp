#include "player_fish.h"

#include <windows.h>

#include <cstdint>

#include "MinHook.h"
#include "../state.h"

namespace hooks {
namespace {

constexpr uintptr_t kPlayerFishFnOffset = 0x38D40;
// NOT referenced from inside the __asm block below as a named constant — confirmed live
// this session that MSVC's inline assembler resolves a constexpr/const int used in a
// `[reg + name]` memory operand to the *address of the constant's own storage*, not its
// value (unlike a #define, which is a textual substitution). That produced
// `[ecx + 0x100072E0]` — a wild read into our own DLL's data section — instead of
// `[ecx + 0x8C]`, and crashed the game the instant this hook fired. The offset is
// inlined as a literal in the asm instead; this constant exists only for the doc comment.
constexpr int kSubObjectOffset = 0x8C;

void* g_original = nullptr;
using state::g_player_fish;
using state::g_sub_object;

// Naked: entry is a thiscall (ecx = player_fish), not a convention MinHook's normal
// C-function detours understand. eax is scratch by every x86 convention here (thiscall
// only gives ecx meaning), so clobbering it briefly is safe, but it's saved/restored
// anyway — cheap insurance after the edx lesson from boundary_gate.
__declspec(naked) void Detour_PlayerFishEntry() {
    __asm {
        push eax
        mov dword ptr [g_player_fish], ecx
        mov eax, dword ptr [ecx + 08Ch]   // kSubObjectOffset — must be a literal, see above
        mov dword ptr [g_sub_object], eax
        pop eax
        jmp dword ptr [g_original]
    }
}

}  // namespace

bool InstallPlayerFish() {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    void* target = reinterpret_cast<void*>(base + kPlayerFishFnOffset);

    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_PlayerFishEntry), &g_original) != MH_OK) {
        return false;
    }
    return MH_EnableHook(target) == MH_OK;
}

}  // namespace hooks
