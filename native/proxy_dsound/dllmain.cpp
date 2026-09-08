// proxy_dsound.dll sits in popcapgame1.exe's install directory as "dsound.dll".
//
// The game statically imports dsound.dll (DirectSoundCreate) via its PE import table,
// so standard DLL search order finds this file (application directory) before the
// system copy. DllMain's only job is to chain-load the real payload, ff2ap_hooks.dll,
// which is what actually installs hooks.
//
// Every genuine export is re-exported here and forwarded, at first call, to the real
// system dsound.dll opened by absolute path via GetSystemDirectoryA(). That call is
// WOW64-redirected for this 32-bit process, so it resolves to SysWOW64 on Windows and
// to syswow64 inside a 64-bit Wine/Proton prefix. Going through an absolute path is
// what keeps us from recursing back into ourselves: the application directory (where
// this file lives) is never consulted.
//
// This replaces the older scheme of PE linker forwarders pointing at a "dsound_real.dll"
// that setup copied out of the system directory. That copy was the one piece of the mod
// that could not work on Linux (there is no %SystemRoot% to copy from), and it also made
// installs sensitive to whatever dsound.dll happened to be on the user's machine. Nothing
// is copied now, on any platform.
//
// Exports are declared in dsound.def so they keep their undecorated names and original
// ordinals (captured via `dumpbin /EXPORTS` against the real system dsound.dll); without
// the .def, __stdcall would decorate them as _Name@N and the game's imports would not
// resolve.

#include <windows.h>

namespace {

// Indices must match the kExportNames order below and the /EXPORT ordinals in dsound.def.
enum Export {
    kDirectSoundCreate = 0,
    kDirectSoundEnumerateA,
    kDirectSoundEnumerateW,
    kDllCanUnloadNow,
    kDllGetClassObject,
    kDirectSoundCaptureCreate,
    kDirectSoundCaptureEnumerateA,
    kDirectSoundCaptureEnumerateW,
    kGetDeviceID,
    kDirectSoundFullDuplexCreate,
    kDirectSoundCreate8,
    kDirectSoundCaptureCreate8,
    kExportCount,
};

const char* const kExportNames[kExportCount] = {
    "DirectSoundCreate",
    "DirectSoundEnumerateA",
    "DirectSoundEnumerateW",
    "DllCanUnloadNow",
    "DllGetClassObject",
    "DirectSoundCaptureCreate",
    "DirectSoundCaptureEnumerateA",
    "DirectSoundCaptureEnumerateW",
    "GetDeviceID",
    "DirectSoundFullDuplexCreate",
    "DirectSoundCreate8",
    "DirectSoundCaptureCreate8",
};

FARPROC g_resolved[kExportCount] = {};
HMODULE g_real = nullptr;

HMODULE RealDsound() {
    if (g_real) {
        return g_real;
    }
    // System directory + "\dsound.dll". GetSystemDirectoryA is WOW64-redirected, so a
    // 32-bit process gets SysWOW64. Loading by absolute path skips the application
    // directory entirely, so this cannot find us again.
    char path[MAX_PATH];
    UINT len = GetSystemDirectoryA(path, MAX_PATH);
    const char* leaf = "\\dsound.dll";
    if (len == 0 || len + strlen(leaf) >= MAX_PATH) {
        return nullptr;
    }
    memcpy(path + len, leaf, strlen(leaf) + 1);
    g_real = LoadLibraryA(path);
    return g_real;
}

}  // namespace

// Called from the naked thunks below. __cdecl so the thunk can clean up its own
// one-argument push. Returns the address to jump to. Kept at file scope so the inline
// asm can name it.
extern "C" FARPROC __cdecl ResolveExport(int index) {
    if (index < 0 || index >= kExportCount) {
        return nullptr;
    }
    if (!g_resolved[index]) {
        HMODULE real = RealDsound();
        if (real) {
            g_resolved[index] = GetProcAddress(real, kExportNames[index]);
        }
    }
    return g_resolved[index];
}

// A lazy tail-call thunk. push/call/add is stack-symmetric, so by the time we jmp the
// callee sees exactly the return address and arguments its caller pushed. Every one of
// these exports is __stdcall, so no arguments live in ecx/edx and clobbering them across
// the ResolveExport call is safe.
//
// __declspec(naked) is x86-only, which is fine: popcapgame1.exe is a 32-bit process, so
// this DLL is only ever built for Win32 (see native/CMakeLists.txt).
//
// One __asm per instruction rather than a single __asm{} block: inside a macro the line
// continuations collapse the body onto one logical line, and a braced block then runs all
// four instructions together into a single unparseable statement.
//
// The thunks are named ff2_* rather than after the exports themselves because the SDK
// headers already declare real prototypes for several of these (DirectSoundCreate in
// dsound.h, DllCanUnloadNow and DllGetClassObject via objbase.h), which a `void name()`
// definition would conflict with. dsound.def maps each export name onto its ff2_ thunk,
// so the DLL still exports exactly the right undecorated names and ordinals.
#define PROXY_THUNK(name, index)                     \
    extern "C" __declspec(naked) void name() {       \
        __asm push index                             \
        __asm call ResolveExport                     \
        __asm add  esp, 4                            \
        __asm jmp  eax                               \
    }

PROXY_THUNK(ff2_DirectSoundCreate,            kDirectSoundCreate)
PROXY_THUNK(ff2_DirectSoundEnumerateA,        kDirectSoundEnumerateA)
PROXY_THUNK(ff2_DirectSoundEnumerateW,        kDirectSoundEnumerateW)
PROXY_THUNK(ff2_DllCanUnloadNow,              kDllCanUnloadNow)
PROXY_THUNK(ff2_DllGetClassObject,            kDllGetClassObject)
PROXY_THUNK(ff2_DirectSoundCaptureCreate,     kDirectSoundCaptureCreate)
PROXY_THUNK(ff2_DirectSoundCaptureEnumerateA, kDirectSoundCaptureEnumerateA)
PROXY_THUNK(ff2_DirectSoundCaptureEnumerateW, kDirectSoundCaptureEnumerateW)
PROXY_THUNK(ff2_GetDeviceID,                  kGetDeviceID)
PROXY_THUNK(ff2_DirectSoundFullDuplexCreate,  kDirectSoundFullDuplexCreate)
PROXY_THUNK(ff2_DirectSoundCreate8,           kDirectSoundCreate8)
PROXY_THUNK(ff2_DirectSoundCaptureCreate8,    kDirectSoundCaptureCreate8)

#undef PROXY_THUNK

namespace {

void LoadPayload(HMODULE self) {
    char path[MAX_PATH];
    DWORD len = GetModuleFileNameA(self, path, MAX_PATH);
    if (len == 0 || len == MAX_PATH) {
        return;
    }

    // Truncate to the directory (strip "dsound.dll"), then append the payload name.
    char* lastSlash = nullptr;
    for (char* p = path; *p; ++p) {
        if (*p == '\\' || *p == '/') {
            lastSlash = p;
        }
    }
    if (!lastSlash) {
        return;
    }
    const char* payloadName = "ff2ap_hooks.dll";
    size_t dirLen = static_cast<size_t>(lastSlash - path) + 1;  // include the slash
    if (dirLen + strlen(payloadName) >= MAX_PATH) {
        return;
    }
    memcpy(lastSlash + 1, payloadName, strlen(payloadName) + 1);

    LoadLibraryA(path);
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        LoadPayload(hModule);
    }
    return TRUE;
}
