#include "boundary_gate.h"

#include <windows.h>

#include <cstdint>
#include <string>

#include "MinHook.h"
#include "../ipc.h"

// UpdateMaxStage(ecx=profileObj, eax=modeIndex, [esp+4]=newVal) — array[modeIndex*32] =
// max(array[modeIndex*32], newVal). Confirmed live via x64dbg this session: watched it
// fire with eax=0 (the campaign-mode slot) right as the game committed to a level-8
// transition after clearing level 7. Function entry offset validated the same way —
// 3 bytes before the mid-function offset Client.py's old capture breakpoint used.
namespace hooks {
namespace {

constexpr uintptr_t kUpdateMaxStageOffset = 0x9AED0;

// Filled by MH_CreateHook with the trampoline that runs the original (relocated)
// instructions — calling through it is exactly equivalent to calling the untouched
// original function with the same register/stack contract.
void* g_original = nullptr;

// cdecl helper called from the naked detour only on the eax==0 (campaign mode) path.
// Returns newVal unchanged if within bounds, or the clamped value (and reports the
// boundary-crossing attempt over IPC) if not.
extern "C" int __cdecl HandleBoundaryCheck(int newVal) {
    const int allowed = ipc::g_allowed_max.load(std::memory_order_relaxed);
    if (newVal <= allowed) {
        return newVal;
    }
    // Boundary-crossing attempt: `newVal` is the level index the game just tried to
    // mark reached, which only happens because the player finished `newVal - 1` — that's
    // the gateway level to send the completion check for, before clamping to `allowed`.
    ipc::QueueSend("LEVEL_COMPLETE " + std::to_string(newVal - 1));
    return allowed;
}

// Naked trampoline: MinHook's actual detour target. No compiler-generated prologue/
// epilogue, so we have exact control over the entry register/stack state, which is
// required here because UpdateMaxStage does NOT use a standard __cdecl/__stdcall
// convention (ecx=profileObj, eax=modeIndex, stack=newVal — MinHook only requires a raw
// address for the detour, it doesn't care about calling convention).
//
// On entry: [esp+0]=return addr, [esp+4]=newVal, eax=modeIndex, ecx=profileObj,
// edx=caller-owned (the outer caller depends on edx surviving this call — confirmed live
// this session by tracing its use before/after the call site, and the hard way: an
// earlier version of this detour that didn't save/restore edx around the
// HandleBoundaryCheck call crashed the game with a null-pointer access violation at the
// caller's `mov eax,[edx+14]` the instant the boundary hook actually fired. cdecl treats
// edx as caller-saved/volatile, so any non-trivial C++ call — HandleBoundaryCheck
// included — is free to clobber it.
//
// Fast path (eax != 0): not the campaign-mode slot, tail-jump straight into the original
// trampoline untouched.
//
// eax == 0 path: save eax/ecx/edx, call HandleBoundaryCheck(newVal) which returns the
// (possibly clamped) value, write it back into the stack slot the original function
// expects, restore eax/ecx/edx, then tail-jump into the original trampoline — which now
// sees exactly the same entry state it would have without this hook, except newVal may
// have been clamped.
__declspec(naked) void Detour_UpdateMaxStage() {
    __asm {
        cmp eax, 0
        jne pass_through

        push edx                   ; save caller's edx — see comment above
        push ecx                   ; save profileObj
        push eax                   ; save modeIndex (== 0)
        mov  eax, [esp + 16]       ; eax = newVal (stack: [0]=eax_saved,[4]=ecx_saved,[8]=edx_saved,[12]=retAddr,[16]=newVal)
        push eax                   ; cdecl arg: newVal
        call HandleBoundaryCheck
        add  esp, 4                ; cdecl caller cleans the one pushed arg
        mov  [esp + 16], eax       ; write back the (possibly clamped) newVal
        pop  eax                   ; restore modeIndex
        pop  ecx                   ; restore profileObj
        pop  edx                   ; restore caller's edx

    pass_through:
        jmp  dword ptr [g_original]
    }
}

}  // namespace

bool InstallBoundaryGate() {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    void* target = reinterpret_cast<void*>(base + kUpdateMaxStageOffset);

    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_UpdateMaxStage), &g_original) != MH_OK) {
        return false;
    }
    return MH_EnableHook(target) == MH_OK;
}

}  // namespace hooks
