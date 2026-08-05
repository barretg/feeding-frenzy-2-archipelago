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

namespace {

// mov ecx,[ebx+0Ch] ; mov ecx,[ecx+3Ch] ; mov [ecx+28],eax  -- the last of these three is
// the actual write; the two `mov ecx,...` before it resolve ecx to level_obj. Confirmed
// live via x64dbg this session: this single site fires for BOTH the map-select confirm
// path (eax = whatever level the player clicked, unclamped) and the natural
// continue-advance path (eax = current level + 1) — one clamp here covers both instead of
// racing the level_guard.cpp poll loop against the game's own async level-load thread,
// which is what caused the earlier intermittent wrong-content-on-clamp bug: writing the
// clamp value up to 2ms *after* the game's own write let the loader thread sometimes read
// the raw unclamped value first.
constexpr uintptr_t kLevelSelectWriteOffset = 0x11641;

void* g_levelselect_original = nullptr;

extern "C" int __cdecl ClampLevelSelect(int requested) {
    const int allowed = ipc::g_allowed_max.load(std::memory_order_relaxed);
    return requested > allowed ? allowed : requested;
}

// Naked: entry state is ecx = level_obj (already resolved by the two stolen `mov ecx,...`
// MinHook relocates into the trampoline), eax = requested level id. We only need to
// replace eax with the clamped value before falling through to the (relocated) store —
// ecx must survive untouched since the original instruction still needs it, and edx is
// caller-owned/cdecl-volatile same as the UpdateMaxStage detour above, so it gets saved
// and restored around the call too.
__declspec(naked) void Detour_LevelSelectWrite() {
    __asm {
        push edx                            ; save caller's edx
        push ecx                            ; save level_obj ptr, needed by the original store
        push eax                            ; cdecl arg: requested level id
        call ClampLevelSelect
        add  esp, 4                         ; cdecl caller cleans the one pushed arg
                                             ; eax now holds the clamped return value — left as-is
        pop  ecx                            ; restore level_obj ptr
        pop  edx                            ; restore caller's edx
        jmp  dword ptr [g_levelselect_original]
    }
}

}  // namespace

bool InstallLevelSelectGate() {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    void* target = reinterpret_cast<void*>(base + kLevelSelectWriteOffset);

    if (MH_CreateHook(target, reinterpret_cast<void*>(&Detour_LevelSelectWrite), &g_levelselect_original) != MH_OK) {
        return false;
    }
    return MH_EnableHook(target) == MH_OK;
}

}  // namespace hooks
