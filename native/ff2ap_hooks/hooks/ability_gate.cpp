#include "ability_gate.h"

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <string>

#include "../ipc.h"

// Offsets/byte sequences from Client.py's DASH_CALL_OFFSET/SUCK_CALL_OFFSET constants —
// each call site is a 5-byte relative CALL in a WM_LBUTTONDOWN/WM_RBUTTONDOWN handler,
// NOP'd to disable.
namespace hooks {
namespace {

constexpr uintptr_t kDashCallOffset = 0x248AD;
constexpr uintptr_t kSuckCallOffset = 0x24A31;

constexpr unsigned char kNop5[5]          = {0x90, 0x90, 0x90, 0x90, 0x90};
constexpr unsigned char kDashUnblocked[5] = {0xE8, 0xEE, 0xBB, 0xFF, 0xFF};  // call 0x4204A0
constexpr unsigned char kSuckUnblocked[5] = {0xE8, 0xAA, 0x98, 0x06, 0x00};  // call 0x48E2E0

void PatchBytes(uintptr_t addr, const unsigned char* bytes) {
    void* p = reinterpret_cast<void*>(addr);
    DWORD oldProtect;
    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &oldProtect);
    memcpy(p, bytes, 5);
    DWORD unused;
    VirtualProtect(p, 5, oldProtect, &unused);
}

void SetDashEnabled(bool enabled) {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    PatchBytes(base + kDashCallOffset, enabled ? kDashUnblocked : kNop5);
    ipc::Log(enabled ? "Dash unblocked" : "Dash blocked");
}

void SetSuckEnabled(bool enabled) {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    PatchBytes(base + kSuckCallOffset, enabled ? kSuckUnblocked : kNop5);
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
