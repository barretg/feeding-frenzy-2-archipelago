// proxy_dsound.dll — sits in popcapgame1.exe's install directory as "dsound.dll".
//
// The game statically imports dsound.dll (DirectSoundCreate) via its PE import table,
// so standard DLL search order finds this file (application directory) before
// C:\Windows\SysWOW64\dsound.dll. Every real export is forwarded to "dsound_real.dll" —
// a plain copy of the genuine system dsound.dll that setup places alongside this file —
// so audio behaves identically to vanilla. DllMain's only job is to chain-load the real
// payload, ff2ap_hooks.dll, which is what actually installs hooks.
//
// Forwarded exports resolved entirely by the OS loader (no code needed) — ordinals
// captured via `dumpbin /EXPORTS` against the real system dsound.dll.
#pragma comment(linker, "/export:DirectSoundCreate=dsound_real.DirectSoundCreate,@1")
#pragma comment(linker, "/export:DirectSoundEnumerateA=dsound_real.DirectSoundEnumerateA,@2")
#pragma comment(linker, "/export:DirectSoundEnumerateW=dsound_real.DirectSoundEnumerateW,@3")
#pragma comment(linker, "/export:DllCanUnloadNow=dsound_real.DllCanUnloadNow,@4")
#pragma comment(linker, "/export:DllGetClassObject=dsound_real.DllGetClassObject,@5")
#pragma comment(linker, "/export:DirectSoundCaptureCreate=dsound_real.DirectSoundCaptureCreate,@6")
#pragma comment(linker, "/export:DirectSoundCaptureEnumerateA=dsound_real.DirectSoundCaptureEnumerateA,@7")
#pragma comment(linker, "/export:DirectSoundCaptureEnumerateW=dsound_real.DirectSoundCaptureEnumerateW,@8")
#pragma comment(linker, "/export:GetDeviceID=dsound_real.GetDeviceID,@9")
#pragma comment(linker, "/export:DirectSoundFullDuplexCreate=dsound_real.DirectSoundFullDuplexCreate,@10")
#pragma comment(linker, "/export:DirectSoundCreate8=dsound_real.DirectSoundCreate8,@11")
#pragma comment(linker, "/export:DirectSoundCaptureCreate8=dsound_real.DirectSoundCaptureCreate8,@12")

#include <windows.h>

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
