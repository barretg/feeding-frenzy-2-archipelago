#include "frenzy_gate.h"

#include <windows.h>

#include <cstdint>
#include <cstdlib>
#include <string>

#include "../ipc.h"

namespace hooks {
namespace {

// Immediate of `push 23h` at 0x47C56D in AddFrenzy:
//   add [edi+290h], eax / mov eax, [edi+290h] / push 23h / pop ecx / cmp eax, ecx
//   jg -> mov [edi+290h], ecx
// The tier-up effect only fires when the new tier exceeds the old one, so holding the
// counter at a multiple of 7 just pins the meter at that tier. Level resets write 0
// directly and never exceed the clamp.
constexpr uintptr_t kClampImmOffset = 0x7C56E;
constexpr int kCountersPerTier = 7;
constexpr int kMaxLevel = 5;

void SetFrenzyLevel(int level) {
    if (level < 0) level = 0;
    if (level > kMaxLevel) level = kMaxLevel;
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));
    auto* p = reinterpret_cast<unsigned char*>(base + kClampImmOffset);
    DWORD oldProtect;
    VirtualProtect(p, 1, PAGE_EXECUTE_READWRITE, &oldProtect);
    *p = static_cast<unsigned char>(level * kCountersPerTier);
    DWORD unused;
    VirtualProtect(p, 1, oldProtect, &unused);
    ipc::Log("Frenzy level = " + std::to_string(level));
}

void HandleLine(const std::string& line) {
    if (line.rfind("FRENZY_LEVEL ", 0) == 0) {
        SetFrenzyLevel(atoi(line.c_str() + 13));
    }
}

}  // namespace

void InstallFrenzyGate() {
    ipc::RegisterHandler(HandleLine);
}

}  // namespace hooks
