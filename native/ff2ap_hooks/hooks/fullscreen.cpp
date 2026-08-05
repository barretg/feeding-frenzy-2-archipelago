#include "fullscreen.h"

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "../ipc.h"

// Port of Client.py's fullscreen/scalemouse/centerfix trio. See that file's docstrings
// for the full rationale (native canvas is 800x600, borderless fullscreen stretch-blits
// it, so mouse coordinates need rescaling; the cursor-park-to-center call also needs
// redirecting to the true screen center once the window isn't at its native size).
namespace hooks {
namespace {

constexpr uintptr_t kWndProcOffset  = 0x24780;
constexpr uintptr_t kWndProcRetOff  = 0x24786;
constexpr unsigned char kWndProcOriginal[6] = {0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF8};
constexpr uintptr_t kIatSetCursorPos = 0x146280;

bool g_active = false;
LONG g_saved_style = 0;
RECT g_saved_rect{};

void* g_mouse_cave = nullptr;
void* g_centerfix_cave = nullptr;
uintptr_t g_setcursorpos_real = 0;

HWND GameHwnd() {
    return FindWindowA("Gatsu", nullptr);
}

void ClientSize(HWND hwnd, int* w, int* h) {
    RECT r;
    GetClientRect(hwnd, &r);
    *w = r.right;
    *h = r.bottom;
}

void ClientCenterScreen(HWND hwnd, int* x, int* y) {
    RECT r;
    GetClientRect(hwnd, &r);
    POINT pt{r.right / 2, r.bottom / 2};
    ClientToScreen(hwnd, &pt);
    *x = pt.x;
    *y = pt.y;
}

void AppendU32(std::vector<unsigned char>& v, uint32_t value) {
    unsigned char b[4];
    memcpy(b, &value, 4);
    v.insert(v.end(), b, b + 4);
}

std::vector<unsigned char> BuildMouseCave(uintptr_t block, uintptr_t base) {
    const uintptr_t sx_addr = block + 0;
    const uintptr_t sy_addr = block + 4;

    std::vector<unsigned char> work;
    work.insert(work.end(), {0x0F, 0xBF, 0x45, 0x14});                 // movsx eax,word [ebp+14]  ; X
    work.insert(work.end(), {0x0F, 0xAF, 0x05}); AppendU32(work, static_cast<uint32_t>(sx_addr));
    work.insert(work.end(), {0xC1, 0xF8, 0x10});                       // sar eax,16
    work.insert(work.end(), {0x0F, 0xB7, 0xD0});                       // movzx edx,ax
    work.insert(work.end(), {0x52});                                   // push edx
    work.insert(work.end(), {0x8B, 0x45, 0x14});                       // mov eax,[ebp+14]
    work.insert(work.end(), {0xC1, 0xF8, 0x10});                       // sar eax,16               ; Y
    work.insert(work.end(), {0x0F, 0xAF, 0x05}); AppendU32(work, static_cast<uint32_t>(sy_addr));
    work.insert(work.end(), {0xC1, 0xF8, 0x10});
    work.insert(work.end(), {0xC1, 0xE0, 0x10});                       // shl eax,16
    work.insert(work.end(), {0x5A});                                   // pop edx
    work.insert(work.end(), {0x0F, 0xB7, 0xD2});                       // movzx edx,dx
    work.insert(work.end(), {0x09, 0xD0});                             // or eax,edx
    work.insert(work.end(), {0x89, 0x45, 0x14});                       // mov [ebp+14],eax

    std::vector<unsigned char> code;
    code.insert(code.end(), {0x55});                                   // push ebp
    code.insert(code.end(), {0x8B, 0xEC});                             // mov ebp,esp
    code.insert(code.end(), {0x50});                                   // push eax
    code.insert(code.end(), {0x52});                                   // push edx
    code.insert(code.end(), {0x8B, 0x45, 0x0C});                       // mov eax,[ebp+0C]  ; msg
    code.insert(code.end(), {0x2D, 0x00, 0x02, 0x00, 0x00});           // sub eax,0x200
    code.insert(code.end(), {0x83, 0xF8, 0x09});                       // cmp eax,9
    code.insert(code.end(), {0x77, static_cast<unsigned char>(work.size())});  // ja .restore
    code.insert(code.end(), work.begin(), work.end());
    code.insert(code.end(), {0x5A});                                   // pop edx  (.restore)
    code.insert(code.end(), {0x58});                                   // pop eax
    code.insert(code.end(), {0x5D});                                   // pop ebp
    code.insert(code.end(), {0x55});                                   // push ebp  (stolen)
    code.insert(code.end(), {0x8B, 0xEC});                             // mov ebp,esp (stolen)
    code.insert(code.end(), {0x83, 0xE4, 0xF8});                       // and esp,-8  (stolen)

    const uintptr_t jmp_pos  = block + 8 + code.size();
    const uintptr_t ret_addr = base + kWndProcRetOff;
    const uint32_t rel = static_cast<uint32_t>(ret_addr - (jmp_pos + 5));
    code.insert(code.end(), {0xE9});
    AppendU32(code, rel);
    return code;
}

// Cave layout: [+0]=screenX [+4]=screenY [+8]=real ptr [+12]=enable
//              [+20]=last_orig_x [+24]=last_orig_y  code@+28
std::vector<unsigned char> BuildCenterfixCave(uintptr_t cave) {
    std::vector<unsigned char> code;
    code.insert(code.end(), {0x8B, 0x44, 0x24, 0x04});                 // mov eax,[esp+4]  (orig x)
    code.insert(code.end(), {0xA3}); AppendU32(code, static_cast<uint32_t>(cave + 20));
    code.insert(code.end(), {0x8B, 0x44, 0x24, 0x08});                 // mov eax,[esp+8]  (orig y)
    code.insert(code.end(), {0xA3}); AppendU32(code, static_cast<uint32_t>(cave + 24));
    code.insert(code.end(), {0x83, 0x3D}); AppendU32(code, static_cast<uint32_t>(cave + 12));
    code.push_back(0x00);                                              // cmp [enable],0
    code.insert(code.end(), {0x74, 18});                               // je .pass
    code.insert(code.end(), {0xA1}); AppendU32(code, static_cast<uint32_t>(cave + 0));
    code.insert(code.end(), {0x89, 0x44, 0x24, 0x04});
    code.insert(code.end(), {0xA1}); AppendU32(code, static_cast<uint32_t>(cave + 4));
    code.insert(code.end(), {0x89, 0x44, 0x24, 0x08});
    code.insert(code.end(), {0xFF, 0x25}); AppendU32(code, static_cast<uint32_t>(cave + 8));  // jmp [real]
    return code;
}

void PatchBytes(uintptr_t addr, const unsigned char* bytes, size_t len) {
    DWORD oldProtect;
    VirtualProtect(reinterpret_cast<void*>(addr), len, PAGE_EXECUTE_READWRITE, &oldProtect);
    memcpy(reinterpret_cast<void*>(addr), bytes, len);
    DWORD unused;
    VirtualProtect(reinterpret_cast<void*>(addr), len, oldProtect, &unused);
}

inline void WriteU32(uintptr_t addr, uint32_t value) {
    *reinterpret_cast<volatile uint32_t*>(addr) = value;
}

inline uint32_t ReadU32(uintptr_t addr) {
    return *reinterpret_cast<volatile uint32_t*>(addr);
}

bool ApplyBorderless(HWND hwnd) {
    const LONG style = GetWindowLongA(hwnd, GWL_STYLE);
    GetWindowRect(hwnd, &g_saved_rect);
    g_saved_style = style;

    HMONITOR mon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi{};
    mi.cbSize = sizeof(mi);
    GetMonitorInfoA(mon, &mi);
    const RECT r = mi.rcMonitor;

    const LONG new_style = (style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)) | WS_POPUP;
    SetWindowLongA(hwnd, GWL_STYLE, new_style);
    SetWindowPos(hwnd, nullptr, r.left, r.top, r.right - r.left, r.bottom - r.top,
                 SWP_NOZORDER | SWP_FRAMECHANGED);
    ClipCursor(nullptr);
    ipc::Log("Borderless fullscreen applied");
    return true;
}

void RemoveBorderless(HWND hwnd) {
    SetWindowLongA(hwnd, GWL_STYLE, g_saved_style);
    SetWindowPos(hwnd, nullptr, g_saved_rect.left, g_saved_rect.top,
                 g_saved_rect.right - g_saved_rect.left, g_saved_rect.bottom - g_saved_rect.top,
                 SWP_NOZORDER | SWP_FRAMECHANGED);
    ipc::Log("Restored windowed mode");
}

void InstallMouseScale(HWND hwnd, uintptr_t base) {
    void* block = VirtualAlloc(nullptr, 128, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!block) {
        ipc::Log("scalemouse: VirtualAlloc failed");
        return;
    }
    const auto block_addr = reinterpret_cast<uintptr_t>(block);
    const auto cave_code = BuildMouseCave(block_addr, base);
    memcpy(reinterpret_cast<void*>(block_addr + 8), cave_code.data(), cave_code.size());

    const uintptr_t site = base + kWndProcOffset;
    const uint32_t rel = static_cast<uint32_t>((block_addr + 8) - (site + 5));
    unsigned char patch[6] = {0xE9, 0, 0, 0, 0, 0x90};
    memcpy(patch + 1, &rel, 4);
    PatchBytes(site, patch, 6);

    g_mouse_cave = block;

    int cw = 0, ch = 0;
    ClientSize(hwnd, &cw, &ch);
    if (cw > 0 && ch > 0) {
        int sx = static_cast<int>(800.0 * 65536 / cw + 0.5);
        int sy = static_cast<int>(600.0 * 65536 / ch + 0.5);
        if (sx < 1) sx = 1;
        if (sy < 1) sy = 1;
        WriteU32(block_addr + 0, static_cast<uint32_t>(sx));
        WriteU32(block_addr + 4, static_cast<uint32_t>(sy));
    }
    ipc::Log("scalemouse: hook installed");
}

void RemoveMouseScale(uintptr_t base) {
    if (!g_mouse_cave) {
        return;
    }
    PatchBytes(base + kWndProcOffset, kWndProcOriginal, 6);
    VirtualFree(g_mouse_cave, 0, MEM_RELEASE);
    g_mouse_cave = nullptr;
    ipc::Log("scalemouse: hook removed");
}

void InstallCenterfix(HWND hwnd, uintptr_t base) {
    const uintptr_t slot = base + kIatSetCursorPos;
    if (g_setcursorpos_real == 0) {
        g_setcursorpos_real = ReadU32(slot);
    }
    void* cave = VirtualAlloc(nullptr, 128, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!cave) {
        ipc::Log("centerfix: VirtualAlloc failed");
        return;
    }
    const auto cave_addr = reinterpret_cast<uintptr_t>(cave);
    WriteU32(cave_addr + 8, static_cast<uint32_t>(g_setcursorpos_real));
    WriteU32(cave_addr + 12, 1);
    const auto cave_code = BuildCenterfixCave(cave_addr);
    memcpy(reinterpret_cast<void*>(cave_addr + 28), cave_code.data(), cave_code.size());

    DWORD oldProtect;
    VirtualProtect(reinterpret_cast<void*>(slot), 4, PAGE_EXECUTE_READWRITE, &oldProtect);
    WriteU32(slot, static_cast<uint32_t>(cave_addr + 28));
    DWORD unused;
    VirtualProtect(reinterpret_cast<void*>(slot), 4, oldProtect, &unused);

    g_centerfix_cave = cave;

    int cx = 0, cy = 0;
    ClientCenterScreen(hwnd, &cx, &cy);
    WriteU32(cave_addr + 0, static_cast<uint32_t>(cx));
    WriteU32(cave_addr + 4, static_cast<uint32_t>(cy));
    ipc::Log("centerfix: installed");
}

void RemoveCenterfix(uintptr_t base) {
    if (!g_centerfix_cave) {
        return;
    }
    const uintptr_t slot = base + kIatSetCursorPos;
    DWORD oldProtect;
    VirtualProtect(reinterpret_cast<void*>(slot), 4, PAGE_EXECUTE_READWRITE, &oldProtect);
    WriteU32(slot, static_cast<uint32_t>(g_setcursorpos_real));
    DWORD unused;
    VirtualProtect(reinterpret_cast<void*>(slot), 4, oldProtect, &unused);
    VirtualFree(g_centerfix_cave, 0, MEM_RELEASE);
    g_centerfix_cave = nullptr;
    ipc::Log("centerfix: restored");
}

void ToggleFullscreen() {
    HWND hwnd = GameHwnd();
    if (!hwnd) {
        ipc::Log("fullscreen: game window not found");
        return;
    }
    const auto base = reinterpret_cast<uintptr_t>(GetModuleHandleA(nullptr));

    if (!g_active) {
        if (!ApplyBorderless(hwnd)) {
            return;
        }
        InstallMouseScale(hwnd, base);
        InstallCenterfix(hwnd, base);
        g_active = true;
    } else {
        RemoveCenterfix(base);
        RemoveMouseScale(base);
        RemoveBorderless(hwnd);
        g_active = false;
    }
}

void HandleLine(const std::string& line) {
    if (line == "TOGGLE_FULLSCREEN") {
        ToggleFullscreen();
    }
}

}  // namespace

void InstallFullscreen() {
    ipc::RegisterHandler(HandleLine);
}

}  // namespace hooks
