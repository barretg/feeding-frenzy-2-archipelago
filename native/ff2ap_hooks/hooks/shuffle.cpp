#include "shuffle.h"

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <sstream>
#include <string>

#include "../ipc.h"
#include "../state.h"

// Level shuffle read-side remap — three patch sites, ported byte-for-byte from
// Client.py's _build_shuffle_caves/_install_shuffle_hook (see that docstring for the
// per-site register/stack contract). The only real difference from the external
// WriteProcessMemory version: the shuffle table lives in state::g_shuffle_table (a
// normal process-lifetime global) instead of a separately VirtualAllocEx'd remote block,
// since we're already inside the process — its address never changes, so only the three
// small trampoline caves need VirtualAlloc, and only once.
namespace hooks {
namespace {

constexpr uintptr_t kSite1Offset = 0x9AB70;  // mov ecx,[eax+28]; test ecx,ecx (map-click)
constexpr uintptr_t kSite2Offset = 0x510A;   // mov eax,[edi]; mov ecx,[eax+28] (continue)
constexpr uintptr_t kSite3Offset = 0x3468;   // push esi; push [eax+28]; lea esi,[eax+50]

void* g_cave_block = nullptr;  // cave1 @ +0, cave2 @ +30, cave3 @ +60 (91 bytes total)
bool g_sites_patched = false;

void PatchBytes(uintptr_t addr, const unsigned char* bytes, size_t len) {
    DWORD oldProtect;
    VirtualProtect(reinterpret_cast<void*>(addr), len, PAGE_EXECUTE_READWRITE, &oldProtect);
    memcpy(reinterpret_cast<void*>(addr), bytes, len);
    DWORD unused;
    VirtualProtect(reinterpret_cast<void*>(addr), len, oldProtect, &unused);
}

// Cave 1 (30 bytes) — patches site1. Entry: EAX=level_obj. Exit: ECX=shuffle[slot],
// flags set by `test ecx,ecx` for the caller's `jl` right after. Table address
// (4 bytes) goes at index 17.
void BuildCave1(uintptr_t table_addr, unsigned char out[30]) {
    static const unsigned char kTemplate[30] = {
        0x52,                          // push edx
        0x8B, 0x50, 0x28,              // mov edx,[eax+28]
        0x8B, 0xCA,                    // mov ecx,edx
        0x85, 0xD2,                    // test edx,edx
        0x78, 0x10,                    // js .done (+16)
        0x83, 0xFA, 0x3B,              // cmp edx,59
        0x77, 0x0B,                    // ja .done (+11)
        0x50,                          // push eax
        0xB8, 0x00, 0x00, 0x00, 0x00,  // mov eax,table_addr  (placeholder @17)
        0x0F, 0xB6, 0x0C, 0x10,        // movzx ecx,byte[eax+edx]
        0x58,                          // pop eax
        0x5A,                          // pop edx (.done)
        0x85, 0xC9,                    // test ecx,ecx
        0xC3,                          // ret
    };
    memcpy(out, kTemplate, 30);
    memcpy(out + 17, &table_addr, 4);
}

// Cave 2 (30 bytes) — patches site2. Entry: EDI=&level_obj. Exit: EAX=level_obj,
// ECX=shuffle[slot]. Table address at index 19.
void BuildCave2(uintptr_t table_addr, unsigned char out[30]) {
    static const unsigned char kTemplate[30] = {
        0x8B, 0x07,                    // mov eax,[edi]  (restore original 1st instr)
        0x52,                          // push edx
        0x8B, 0x50, 0x28,              // mov edx,[eax+28]
        0x8B, 0xCA,                    // mov ecx,edx
        0x85, 0xD2,                    // test edx,edx
        0x78, 0x10,                    // js .done (+16)
        0x83, 0xFA, 0x3B,              // cmp edx,59
        0x77, 0x0B,                    // ja .done (+11)
        0x50,                          // push eax
        0xB8, 0x00, 0x00, 0x00, 0x00,  // mov eax,table_addr  (placeholder @19)
        0x0F, 0xB6, 0x0C, 0x10,        // movzx ecx,byte[eax+edx]
        0x58,                          // pop eax
        0x5A,                          // pop edx (.done)
        0xC3,                          // ret
    };
    memcpy(out, kTemplate, 30);
    memcpy(out + 19, &table_addr, 4);
}

// Cave 3 (31 bytes) — patches site3 (7-byte patch: call + nop + nop). Entry:
// EAX=level_obj, stack top = return addr (0x40346D). Sets up the stack/ESI exactly as
// the stolen instructions would, but pushes shuffle[slot] as the content-id arg. Table
// address at index 16.
void BuildCave3(uintptr_t table_addr, unsigned char out[31]) {
    static const unsigned char kTemplate[31] = {
        0x59,                          // pop ecx  (save ret addr)
        0x56,                          // push esi (old esi, frame expects it at ebp-8)
        0x8B, 0x50, 0x28,              // mov edx,[eax+28]  (slot)
        0x85, 0xD2,                    // test edx,edx
        0x78, 0x10,                    // js .pass (+16)
        0x83, 0xFA, 0x3B,              // cmp edx,59
        0x77, 0x0B,                    // ja .pass (+11)
        0x50,                          // push eax
        0xB8, 0x00, 0x00, 0x00, 0x00,  // mov eax,table_addr  (placeholder @16)
        0x0F, 0xB6, 0x14, 0x10,        // movzx edx,byte[eax+edx]
        0x58,                          // pop eax
        0x52,                          // push edx  (.pass — content_id arg)
        0x8D, 0x70, 0x50,              // lea esi,[eax+50]  (array ptr)
        0x51,                          // push ecx  (re-push ret addr)
        0xC3,                          // ret
    };
    memcpy(out, kTemplate, 31);
    memcpy(out + 16, &table_addr, 4);
}

void InstallSitesIfNeeded() {
    if (g_sites_patched) {
        return;
    }

    constexpr size_t kTotal = 30 + 30 + 31;
    g_cave_block = VirtualAlloc(nullptr, kTotal, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!g_cave_block) {
        ipc::Log("shuffle: VirtualAlloc failed");
        return;
    }

    auto cave1_addr = reinterpret_cast<uintptr_t>(g_cave_block);
    auto cave2_addr = cave1_addr + 30;
    auto cave3_addr = cave2_addr + 30;
    auto table_addr = reinterpret_cast<uintptr_t>(const_cast<unsigned char*>(state::g_shuffle_table));

    unsigned char cave1[30], cave2[30], cave3[31];
    BuildCave1(table_addr, cave1);
    BuildCave2(table_addr, cave2);
    BuildCave3(table_addr, cave3);
    memcpy(reinterpret_cast<void*>(cave1_addr), cave1, 30);
    memcpy(reinterpret_cast<void*>(cave2_addr), cave2, 30);
    memcpy(reinterpret_cast<void*>(cave3_addr), cave3, 31);

    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));

    const uintptr_t site1 = base + kSite1Offset;
    const uint32_t rel1 = static_cast<uint32_t>(cave1_addr - (site1 + 5));
    unsigned char patch1[5] = {0xE8, 0, 0, 0, 0};
    memcpy(patch1 + 1, &rel1, 4);
    PatchBytes(site1, patch1, 5);

    const uintptr_t site2 = base + kSite2Offset;
    const uint32_t rel2 = static_cast<uint32_t>(cave2_addr - (site2 + 5));
    unsigned char patch2[5] = {0xE8, 0, 0, 0, 0};
    memcpy(patch2 + 1, &rel2, 4);
    PatchBytes(site2, patch2, 5);

    const uintptr_t site3 = base + kSite3Offset;
    const uint32_t rel3 = static_cast<uint32_t>(cave3_addr - (site3 + 5));
    unsigned char patch3[7] = {0xE8, 0, 0, 0, 0, 0x90, 0x90};
    memcpy(patch3 + 1, &rel3, 4);
    PatchBytes(site3, patch3, 7);

    g_sites_patched = true;
    ipc::Log("shuffle: hook installed");
}

void HandleLine(const std::string& line) {
    if (line.rfind("SHUFFLE ", 0) != 0) {
        return;
    }
    std::istringstream stream(line.substr(8));
    std::string token;
    int index = 0;
    unsigned char parsed[60];
    while (index < 60 && std::getline(stream, token, ',')) {
        try {
            parsed[index++] = static_cast<unsigned char>(std::stoi(token) & 0xFF);
        } catch (...) {
            ipc::Log("shuffle: malformed SHUFFLE line, ignoring");
            return;
        }
    }
    if (index != 60) {
        ipc::Log("shuffle: SHUFFLE line had wrong element count, ignoring");
        return;
    }

    for (int i = 0; i < 60; ++i) {
        state::g_shuffle_table[i] = parsed[i];
    }
    state::g_shuffle_active = true;

    InstallSitesIfNeeded();
    ipc::Log("shuffle: table updated");
}

}  // namespace

void InstallShuffle() {
    ipc::RegisterHandler(HandleLine);
}

}  // namespace hooks
