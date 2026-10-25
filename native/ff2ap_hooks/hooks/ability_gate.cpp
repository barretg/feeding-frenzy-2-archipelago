#include "ability_gate.h"

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <string>

#include "../ipc.h"

// 0x4204A0 is the shared mouse-event dispatcher, and its call at 0x4248AD is also the
// tail of WM_LBUTTONUP and WM_RBUTTONUP (the suck release). So Dash is gated on the
// WM_LBUTTONDOWN-only "push 0" at 0x424914 (replaced by "jmp 0x4248B2", which skips
// to the handler's return), never on the shared call. Suck's call at 0x424A31 is
// WM_RBUTTONDOWN-only and is NOP'd to disable.
namespace hooks {
namespace {

constexpr uintptr_t kDashPushOffset = 0x24914;
constexpr uintptr_t kSuckCallOffset = 0x24A31;

constexpr unsigned char kDashBlocked[2]   = {0xEB, 0x9C};  // jmp 0x4248B2
constexpr unsigned char kDashUnblocked[2] = {0x6A, 0x00};  // push 0
constexpr unsigned char kNop5[5]          = {0x90, 0x90, 0x90, 0x90, 0x90};
constexpr unsigned char kSuckUnblocked[5] = {0xE8, 0xAA, 0x98, 0x06, 0x00};  // call 0x48E2E0

void PatchBytes(uintptr_t addr, const unsigned char* bytes, size_t len) {
    void* p = reinterpret_cast<void*>(addr);
    DWORD oldProtect;
    VirtualProtect(p, len, PAGE_EXECUTE_READWRITE, &oldProtect);
    memcpy(p, bytes, len);
    DWORD unused;
    VirtualProtect(p, len, oldProtect, &unused);
    FlushInstructionCache(GetCurrentProcess(), p, len);
}

void SetDashEnabled(bool enabled) {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    PatchBytes(base + kDashPushOffset, enabled ? kDashUnblocked : kDashBlocked, 2);
    ipc::Log(enabled ? "Dash unblocked" : "Dash blocked");
}

void SetSuckEnabled(bool enabled) {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    PatchBytes(base + kSuckCallOffset, enabled ? kSuckUnblocked : kNop5, 5);
    ipc::Log(enabled ? "Suck unblocked" : "Suck blocked");
}

void HandleLine(const std::string& line) {
    if (line.rfind("DASH_ENABLED ", 0) == 0) {
        SetDashEnabled(line[13] != '0');
    } else if (line.rfind("SUCK_ENABLED ", 0) == 0) {
        SetSuckEnabled(line[13] != '0');
    }
}

}  // namespace

void InstallAbilityGate() {
    SetDashEnabled(false);
    SetSuckEnabled(false);
    ipc::RegisterHandler(HandleLine);
}

}  // namespace hooks
