"""
Feeding Frenzy 2 Archipelago Client
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wintypes
import struct
import sys
import threading
import time
from typing import List, Optional

import pymem
import pymem.process

import Utils
from CommonClient import CommonContext, server_loop, gui_enabled, ClientCommandProcessor, logger, get_base_parser

GAME_NAME    = "Feeding Frenzy 2"
PROCESS_NAME = "popcapgame1.exe"

# ── Instruction offsets from exe base ────────────────────────────────────────
LEVEL_STATE_OFFSET = 0x9C064
MAX_STAGE_OFFSET   = 0x9AED3

# ── Struct offsets from captured level object base ────────────────────────────
OFFSET_LIVES          = 0x10
OFFSET_SCORE          = 0x14
OFFSET_STAGE          = 0x24
OFFSET_LEVEL_ID       = 0x28
OFFSET_SCORE_SNAPSHOT = 0x30
OFFSET_LIVES_SNAPSHOT = 0x34
OFFSET_PROGRESS       = 0x40

# ── Player fish struct offsets ────────────────────────────────────────────────
PLAYER_FISH_OFFSET    = 0x38D47
OFFSET_SUB_OBJECT     = 0x8C
OFFSET_ALIVE_PTR      = 0x78
OFFSET_RESPAWN_FLAG   = 0x98
DEATH_FUNC            = 0x00404E10

# ── Max stage offset from ecx ─────────────────────────────────────────────────
OFFSET_MAX_STAGE = 0x58

# ── Boss health counter ───────────────────────────────────────────────────────
BOSS_HP_OFFSET  = 0xA908A   # inc [ecx+0xB4]  — fires each time boss takes a hit
OFFSET_BOSS_HP  = 0xB4      # goal at 20 hits

# ── Zone boundaries (0-indexed level where each new zone starts) ──────────────
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 45, 48, 51, 54, 57]

# ── Location IDs (must match world definition) ────────────────────────────────
BONUS_LEVELS = frozenset({4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60})
TOTAL_LEVELS = 60
LOC_BASE     = 0xFF20000 + 0x1000

ITEM_PROGRESSIVE_FISH = 0xFF20000 + 1
ITEM_1UP              = 0xFF20000 + 2
ITEM_DASH             = 0xFF20000 + 3
ITEM_SUCK             = 0xFF20000 + 4

# ── Dash ability patch ────────────────────────────────────────────────────────
# Patch the call site at 0x004248AD (WM_LBUTTONDOWN handler) to NOP.
# This is the actual dash trigger (call 0x4204A0); 0x0042490B was cursor snap only.
DASH_CALL_OFFSET = 0x248AD
DASH_BLOCKED     = bytes([0x90, 0x90, 0x90, 0x90, 0x90])        # NOP x5
DASH_UNBLOCKED   = bytes([0xE8, 0xEE, 0xBB, 0xFF, 0xFF])        # call 0x4204A0

# ── Suck ability patch ────────────────────────────────────────────────────────
# Patch the call site at 0x00424A31 (WM_RBUTTONDOWN handler) to NOP.
SUCK_CALL_OFFSET = 0x24A31
SUCK_BLOCKED     = bytes([0x90, 0x90, 0x90, 0x90, 0x90])        # NOP x5
SUCK_UNBLOCKED   = bytes([0xE8, 0xAA, 0x98, 0x06, 0x00])        # call 0x48E2E0

# ── Level shuffle hook ────────────────────────────────────────────────────────
# Path 1 (map click): 8 bytes at 0x411621 — mov ecx,[ecx+0xC] + call 0x4980C0
SHUFFLE_CLICK_OFFSET    = 0x11621
SHUFFLE_CLICK_ORIGINAL  = bytes([0x8B, 0x49, 0x0C, 0xE8, 0x97, 0x6A, 0x08, 0x00])
CONTENT_CLICK_TARGET    = 0x004980C0

# Path 2 (auto-advance): 5 bytes at 0x49AFD0 — call 0x4966D0
SHUFFLE_ADVANCE_OFFSET   = 0x9AFD0
SHUFFLE_ADVANCE_ORIGINAL = bytes([0xE8, 0xFB, 0xB6, 0xFF, 0xFF])
CONTENT_ADVANCE_TARGET   = 0x004966D0

# ── Windows debug API setup ───────────────────────────────────────────────────
DBG_CONTINUE      = 0x00010002
TH32CS_SNAPTHREAD = 0x00000004

CONTEXT_DEBUG_REGISTERS = 0x00010010
CONTEXT_INTEGER         = 0x00010002
CONTEXT_CONTROL         = 0x00010001
CONTEXT_CAPTURE         = CONTEXT_DEBUG_REGISTERS | CONTEXT_INTEGER | CONTEXT_CONTROL

THREAD_SUSPEND_RESUME    = 0x0002
THREAD_GET_CONTEXT       = 0x0008
THREAD_SET_CONTEXT       = 0x0010
THREAD_QUERY_INFORMATION = 0x0040
THREAD_ACCESS = (
    THREAD_SUSPEND_RESUME |
    THREAD_GET_CONTEXT    |
    THREAD_SET_CONTEXT    |
    THREAD_QUERY_INFORMATION
)

Wow64GetThreadContext           = ctypes.windll.kernel32.Wow64GetThreadContext
Wow64GetThreadContext.argtypes  = [wintypes.HANDLE, ctypes.c_void_p]
Wow64GetThreadContext.restype   = wintypes.BOOL

Wow64SetThreadContext           = ctypes.windll.kernel32.Wow64SetThreadContext
Wow64SetThreadContext.argtypes  = [wintypes.HANDLE, ctypes.c_void_p]
Wow64SetThreadContext.restype   = wintypes.BOOL


# ── ctypes structures ─────────────────────────────────────────────────────────

class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",             wintypes.DWORD),
        ("cntUsage",           wintypes.DWORD),
        ("th32ThreadID",       wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri",          wintypes.LONG),
        ("tpDeltaPri",         wintypes.LONG),
        ("dwFlags",            wintypes.DWORD),
    ]

class EXCEPTION_RECORD(ctypes.Structure):
    pass

EXCEPTION_RECORD._fields_ = [
    ("ExceptionCode",        wintypes.DWORD),
    ("ExceptionFlags",       wintypes.DWORD),
    ("ExceptionRecord",      ctypes.POINTER(EXCEPTION_RECORD)),
    ("ExceptionAddress",     ctypes.c_void_p),
    ("NumberParameters",     wintypes.DWORD),
    ("ExceptionInformation", ctypes.c_ulong * 15),
]

class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [
        ("ExceptionRecord", EXCEPTION_RECORD),
        ("dwFirstChance",   wintypes.DWORD),
    ]

class DEBUG_EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("Exception", EXCEPTION_DEBUG_INFO),
        ("pad",       ctypes.c_byte * 160),
    ]

class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [
        ("dwDebugEventCode", wintypes.DWORD),
        ("dwProcessId",      wintypes.DWORD),
        ("dwThreadId",       wintypes.DWORD),
        ("u",                DEBUG_EVENT_UNION),
    ]

class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [
        ("ControlWord",   wintypes.DWORD),
        ("StatusWord",    wintypes.DWORD),
        ("TagWord",       wintypes.DWORD),
        ("ErrorOffset",   wintypes.DWORD),
        ("ErrorSelector", wintypes.DWORD),
        ("DataOffset",    wintypes.DWORD),
        ("DataSelector",  wintypes.DWORD),
        ("RegisterArea",  ctypes.c_byte * 80),
        ("Cr0NpxState",   wintypes.DWORD),
    ]

class CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags",      wintypes.DWORD),
        ("Dr0",               wintypes.DWORD),
        ("Dr1",               wintypes.DWORD),
        ("Dr2",               wintypes.DWORD),
        ("Dr3",               wintypes.DWORD),
        ("Dr6",               wintypes.DWORD),
        ("Dr7",               wintypes.DWORD),
        ("FloatSave",         FLOATING_SAVE_AREA),
        ("SegGs",             wintypes.DWORD),
        ("SegFs",             wintypes.DWORD),
        ("SegEs",             wintypes.DWORD),
        ("SegDs",             wintypes.DWORD),
        ("Edi",               wintypes.DWORD),
        ("Esi",               wintypes.DWORD),
        ("Ebx",               wintypes.DWORD),
        ("Edx",               wintypes.DWORD),
        ("Ecx",               wintypes.DWORD),
        ("Eax",               wintypes.DWORD),
        ("Ebp",               wintypes.DWORD),
        ("Eip",               wintypes.DWORD),
        ("SegCs",             wintypes.DWORD),
        ("EFlags",            wintypes.DWORD),
        ("Esp",               wintypes.DWORD),
        ("SegSs",             wintypes.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


# ── Memory helpers ────────────────────────────────────────────────────────────

def read_int(pm: pymem.Pymem, address: int) -> int:
    return int.from_bytes(pm.read_bytes(address, 4), byteorder="little")


_GWL_STYLE        = -16
_WS_THICKFRAME    = 0x00040000
_WS_MAXIMIZEBOX   = 0x00010000
_SWP_NOMOVE       = 0x0002
_SWP_NOSIZE       = 0x0001
_SWP_NOZORDER     = 0x0004
_SWP_FRAMECHANGED = 0x0020

def make_window_resizable() -> None:
    hwnd = ctypes.windll.user32.FindWindowA(b"Gatsu", None)
    if not hwnd:
        logger.warning("[FF2] Could not find game window to make resizable")
        return
    style = ctypes.windll.user32.GetWindowLongA(hwnd, _GWL_STYLE)
    style |= _WS_THICKFRAME | _WS_MAXIMIZEBOX
    ctypes.windll.user32.SetWindowLongA(hwnd, _GWL_STYLE, style)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED)
    logger.info(f"[FF2] Window resizable (hwnd=0x{hwnd:08X})")


def write_bytes(pm: pymem.Pymem, address: int, data: bytes) -> None:
    buf     = (ctypes.c_byte * len(data))(*data)
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf, len(data),
        ctypes.byref(written),
    )


def write_int(pm: pymem.Pymem, address: int, value: int) -> None:
    buf     = value.to_bytes(4, byteorder="little")
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf, 4,
        ctypes.byref(written),
    )


# ── Proxy window (DWM thumbnail) ─────────────────────────────────────────────

_PM_REMOVE               = 0x0001
_DWM_TNP_RECTDESTINATION = 0x1
_DWM_TNP_OPACITY         = 0x4
_DWM_TNP_VISIBLE         = 0x8
_DWM_TNP_SOURCECLIENTONLY= 0x10
_WS_OVERLAPPEDWINDOW     = 0x00CF0000
_WS_VISIBLE              = 0x10000000
_CS_HREDRAW              = 0x0002
_CS_VREDRAW              = 0x0001
_WM_DESTROY              = 0x0002
_WM_SIZE                 = 0x0005
_WM_CLOSE                = 0x0010
_WM_QUIT                 = 0x0012

_PROXY_MOUSE_MSGS = frozenset([0x200,0x201,0x202,0x203,0x204,0x205,0x206,0x207,0x208])
_PROXY_KEY_MSGS   = frozenset([0x100,0x101,0x102])

class _DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("dwFlags",               ctypes.c_uint),
        ("rcDestination",         wintypes.RECT),
        ("rcSource",              wintypes.RECT),
        ("opacity",               ctypes.c_ubyte),
        ("fVisible",              wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]

_WPARAM_T  = ctypes.c_ulonglong
_LPARAM_T  = ctypes.c_longlong
_LRESULT_T = ctypes.c_longlong

_WNDPROCTYPE = ctypes.WINFUNCTYPE(
    _LRESULT_T, wintypes.HWND, ctypes.c_uint, _WPARAM_T, _LPARAM_T
)

class _WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize",        ctypes.c_uint),
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   _WNDPROCTYPE),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wintypes.HANDLE),
        ("hIcon",         wintypes.HANDLE),
        ("hCursor",       wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName",  ctypes.c_char_p),
        ("lpszClassName", ctypes.c_char_p),
        ("hIconSm",       wintypes.HANDLE),
    ]

_proxy_wndproc_ref = None  # keep WNDPROCTYPE alive — GC would silently break it


def _run_proxy_window(game_hwnd: int, game_w: int, game_h: int,
                      stop_event: threading.Event) -> None:
    global _proxy_wndproc_ref
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    dwmapi   = ctypes.windll.dwmapi
    gdi32    = ctypes.windll.gdi32

    _msg_args = [wintypes.HWND, ctypes.c_uint, _WPARAM_T, _LPARAM_T]
    user32.DefWindowProcA.argtypes = _msg_args
    user32.DefWindowProcA.restype  = _LRESULT_T
    user32.PostMessageA.argtypes   = _msg_args
    user32.PostMessageA.restype    = wintypes.BOOL

    hthumbnail = wintypes.HANDLE(0)

    def _update_thumb(cw: int, ch: int) -> None:
        if not hthumbnail:
            return
        props = _DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = (_DWM_TNP_RECTDESTINATION | _DWM_TNP_OPACITY |
                         _DWM_TNP_VISIBLE | _DWM_TNP_SOURCECLIENTONLY)
        props.rcDestination = wintypes.RECT(0, 0, cw, ch)
        props.opacity = 255
        props.fVisible = True
        props.fSourceClientAreaOnly = True
        dwmapi.DwmUpdateThumbnailProperties(hthumbnail, ctypes.byref(props))

    def _fwd_mouse(proxy_hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        rect = wintypes.RECT()
        user32.GetClientRect(proxy_hwnd, ctypes.byref(rect))
        cw, ch = rect.right, rect.bottom
        if cw <= 0 or ch <= 0:
            return
        x = lparam & 0xFFFF
        y = (lparam >> 16) & 0xFFFF
        if x >= 0x8000: x -= 0x10000
        if y >= 0x8000: y -= 0x10000
        sx = max(0, min(int(x * game_w / cw), game_w - 1))
        sy = max(0, min(int(y * game_h / ch), game_h - 1))
        user32.PostMessageA(game_hwnd, msg, wparam, (sy << 16) | (sx & 0xFFFF))

    def wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        nonlocal hthumbnail
        if msg == _WM_SIZE:
            cw, ch = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
            if cw > 0 and ch > 0:
                _update_thumb(cw, ch)
            return 0
        elif msg in _PROXY_MOUSE_MSGS:
            _fwd_mouse(hwnd, msg, wparam, lparam)
            return 0
        elif msg in _PROXY_KEY_MSGS:
            user32.PostMessageA(game_hwnd, msg, wparam, lparam)
            return 0
        elif msg == _WM_CLOSE:
            if hthumbnail:
                dwmapi.DwmUnregisterThumbnail(hthumbnail)
                hthumbnail = None
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == _WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcA(hwnd, msg, wparam, lparam)

    _proxy_wndproc_ref = _WNDPROCTYPE(wndproc)
    hinstance  = kernel32.GetModuleHandleA(None)
    class_name = b"FF2Proxy"

    wc = _WNDCLASSEX()
    wc.cbSize        = ctypes.sizeof(_WNDCLASSEX)
    wc.style         = _CS_HREDRAW | _CS_VREDRAW
    wc.lpfnWndProc   = _proxy_wndproc_ref
    wc.hInstance     = hinstance
    wc.hCursor       = user32.LoadCursorW(0, 32512)
    wc.hbrBackground = gdi32.GetStockObject(4)
    wc.lpszClassName = class_name

    if not user32.RegisterClassExA(ctypes.byref(wc)):
        logger.error(f"[FF2] Proxy RegisterClassExA failed: {kernel32.GetLastError()}")
        return

    cr = wintypes.RECT(0, 0, game_w * 2, game_h * 2)
    user32.AdjustWindowRect(ctypes.byref(cr), _WS_OVERLAPPEDWINDOW, False)

    proxy_hwnd = user32.CreateWindowExA(
        0, class_name, b"Feeding Frenzy 2",
        _WS_OVERLAPPEDWINDOW | _WS_VISIBLE,
        100, 100, cr.right - cr.left, cr.bottom - cr.top,
        None, None, hinstance, None,
    )
    if not proxy_hwnd:
        logger.error(f"[FF2] Proxy CreateWindowExA failed: {kernel32.GetLastError()}")
        user32.UnregisterClassA(class_name, hinstance)
        return

    hr = dwmapi.DwmRegisterThumbnail(proxy_hwnd, game_hwnd, ctypes.byref(hthumbnail))
    if hr != 0:
        logger.error(f"[FF2] DwmRegisterThumbnail failed: 0x{hr & 0xFFFFFFFF:08X}")
    else:
        rect = wintypes.RECT()
        user32.GetClientRect(proxy_hwnd, ctypes.byref(rect))
        _update_thumb(rect.right, rect.bottom)
        logger.info(f"[FF2] Proxy window active (hwnd=0x{proxy_hwnd:08X})")

    wmsg = wintypes.MSG()
    while not stop_event.is_set():
        if user32.PeekMessageA(ctypes.byref(wmsg), None, 0, 0, _PM_REMOVE):
            if wmsg.message == _WM_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(wmsg))
            user32.DispatchMessageA(ctypes.byref(wmsg))
        else:
            time.sleep(0.001)

    if hthumbnail:
        dwmapi.DwmUnregisterThumbnail(hthumbnail)
    user32.UnregisterClassA(class_name, hinstance)
    logger.info("[FF2] Proxy window closed")


def _start_proxy_window(stop_event: threading.Event) -> None:
    user32 = ctypes.windll.user32
    hwnd   = user32.FindWindowA(b"Gatsu", None)
    if not hwnd:
        logger.warning("[FF2] Could not find game window for proxy")
        return
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    game_w = rect.right  or 800
    game_h = rect.bottom or 600
    logger.info(f"[FF2] Starting proxy window ({game_w}x{game_h})")
    threading.Thread(
        target=_run_proxy_window,
        args=(hwnd, game_w, game_h, stop_event),
        daemon=True,
    ).start()


# ── Thread / breakpoint helpers ───────────────────────────────────────────────

def get_process_threads(pid: int):
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    threads  = []
    entry    = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    if ctypes.windll.kernel32.Thread32First(snapshot, ctypes.byref(entry)):
        while True:
            if entry.th32OwnerProcessID == pid:
                threads.append(entry.th32ThreadID)
            if not ctypes.windll.kernel32.Thread32Next(snapshot, ctypes.byref(entry)):
                break
    ctypes.windll.kernel32.CloseHandle(snapshot)
    return threads


def get_thread_handle(tid: int):
    return ctypes.windll.kernel32.OpenThread(THREAD_ACCESS, False, tid)


def set_hardware_breakpoint(thread_handle, address: int, dr_index: int = 0) -> bool:
    if ctypes.windll.kernel32.SuspendThread(thread_handle) == 0xFFFFFFFF:
        return False
    try:
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_CAPTURE
        if not Wow64GetThreadContext(thread_handle, ctypes.byref(ctx)):
            return False
        if dr_index == 0:
            ctx.Dr0 = address
        elif dr_index == 1:
            ctx.Dr1 = address
        ctx.Dr6 = 0
        ctx.Dr7 |= (0x1 << (dr_index * 2))
        ctx.Dr7 &= ~(0xF << (16 + dr_index * 4))
        ctx.ContextFlags = CONTEXT_CAPTURE
        return bool(Wow64SetThreadContext(thread_handle, ctypes.byref(ctx)))
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)


def clear_hardware_breakpoint(thread_handle, dr_index: int = 0) -> None:
    if ctypes.windll.kernel32.SuspendThread(thread_handle) == 0xFFFFFFFF:
        return
    try:
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_CAPTURE
        Wow64GetThreadContext(thread_handle, ctypes.byref(ctx))
        if dr_index == 0:
            ctx.Dr0 = 0
        elif dr_index == 1:
            ctx.Dr1 = 0
        ctx.Dr7 &= ~(0x1 << (dr_index * 2))
        ctx.ContextFlags = CONTEXT_CAPTURE
        Wow64SetThreadContext(thread_handle, ctypes.byref(ctx))
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)


def set_bp_on_thread(tid: int, address: int, dr_index: int = 0) -> bool:
    th = get_thread_handle(tid)
    if th:
        ok = set_hardware_breakpoint(th, address, dr_index)
        ctypes.windll.kernel32.CloseHandle(th)
        return ok
    return False


# ── Capture routines ──────────────────────────────────────────────────────────

def capture_level_object(pm: pymem.Pymem, base: int) -> Optional[int]:
    target = base + LEVEL_STATE_OFFSET
    logger.info(f"[FF2] Waiting for level load to capture game object (0x{target:08X})...")

    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        logger.error(f"[FF2] Failed to attach debugger: {ctypes.windll.kernel32.GetLastError()}")
        return None

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    for tid in get_process_threads(pm.process_id):
        set_bp_on_thread(tid, target, 0)

    level_object = None
    debug_event  = DEBUG_EVENT()

    while level_object is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue

        event_code = debug_event.dwDebugEventCode
        tid        = debug_event.dwThreadId

        if event_code == 2:  # CREATE_THREAD_DEBUG_EVENT
            pass

        elif event_code == 1:  # EXCEPTION_DEBUG_EVENT
            code     = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            if exc_addr == target and code not in (0x80000003,):
                th = get_thread_handle(tid)
                if th:
                    if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                        try:
                            ctx = CONTEXT()
                            ctx.ContextFlags = CONTEXT_CAPTURE
                            if Wow64GetThreadContext(th, ctypes.byref(ctx)) and ctx.Eip == target:
                                level_object = ctx.Eax
                                logger.info(f"[FF2] Level object captured: 0x{level_object:08X}")
                                clear_hardware_breakpoint(th, 0)
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:  # CREATE_PROCESS_DEBUG_EVENT
            set_bp_on_thread(tid, target, 0)

        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )

        if level_object is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break

    return level_object


def capture_max_stage_object(pm: pymem.Pymem, base: int, stop_event: threading.Event) -> Optional[int]:
    target = base + MAX_STAGE_OFFSET
    logger.info(f"[FF2] Waiting for level completion to capture max stage object (0x{target:08X})...")

    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        logger.error(f"[FF2] Failed to attach debugger: {ctypes.windll.kernel32.GetLastError()}")
        return None

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    for tid in get_process_threads(pm.process_id):
        set_bp_on_thread(tid, target, 0)

    max_stage_address = None
    debug_event       = DEBUG_EVENT()

    while not stop_event.is_set() and max_stage_address is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue

        event_code = debug_event.dwDebugEventCode
        tid        = debug_event.dwThreadId

        if event_code == 2:
            pass

        elif event_code == 1:
            code     = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            if exc_addr == target and code not in (0x80000003,):
                th = get_thread_handle(tid)
                if th:
                    if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                        try:
                            ctx = CONTEXT()
                            ctx.ContextFlags = CONTEXT_CAPTURE
                            if Wow64GetThreadContext(th, ctypes.byref(ctx)) and ctx.Eip == target:
                                ecx       = ctx.Ecx
                                candidate = ecx + OFFSET_MAX_STAGE
                                value     = read_int(pm, candidate)
                                if 0 <= value <= 100:
                                    max_stage_address = candidate
                                    logger.info(f"[FF2] Max stage captured: 0x{max_stage_address:08X} = {value}")
                                    clear_hardware_breakpoint(th, 0)
                                else:
                                    logger.warning(f"[FF2] Ignoring bad max stage capture: value={value}")
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:
            set_bp_on_thread(tid, target, 0)

        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )

        if max_stage_address is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break

    return max_stage_address


# ── Game logic helpers ────────────────────────────────────────────────────────

def max_allowed_stage(fish_received: int) -> int:
    next_zone_idx = fish_received + 1
    if next_zone_idx >= len(ZONE_BOUNDARIES):
        return 999
    return ZONE_BOUNDARIES[next_zone_idx] - 1


def location_id_for(level_id: int, slot: int) -> int:
    return LOC_BASE + (level_id * 3) + slot


def reset_to_boundary_level(pm: pymem.Pymem, level_obj: int) -> None:
    score_snapshot = read_int(pm, level_obj + OFFSET_SCORE_SNAPSHOT)
    lives_snapshot = read_int(pm, level_obj + OFFSET_LIVES_SNAPSHOT)
    current_level  = read_int(pm, level_obj + OFFSET_LEVEL_ID)
    write_int(pm, level_obj + OFFSET_LEVEL_ID, current_level - 1)
    write_int(pm, level_obj + OFFSET_SCORE,    score_snapshot)
    write_int(pm, level_obj + OFFSET_LIVES,    lives_snapshot)
    write_int(pm, level_obj + OFFSET_PROGRESS, 0)
    logger.info(f"[FF2] Boundary reached — resetting to level {current_level} replay")


# ── Command processor ─────────────────────────────────────────────────────────

class FF2CommandProcessor(ClientCommandProcessor):
    def _cmd_status(self):
        """Show current game state."""
        ctx: FF2Context = self.ctx
        if not ctx.game_ready:
            logger.info("[FF2] Game not ready yet.")
            return
        pm  = ctx.pm
        obj = ctx.level_obj
        logger.info(f"Lives:    {read_int(pm, obj + OFFSET_LIVES)}")
        logger.info(f"Score:    {read_int(pm, obj + OFFSET_SCORE)}")
        logger.info(f"Stage:    {read_int(pm, obj + OFFSET_STAGE)}")
        logger.info(f"Level ID: {read_int(pm, obj + OFFSET_LEVEL_ID)} (1-indexed: {read_int(pm, obj + OFFSET_LEVEL_ID) + 1})")
        logger.info(f"Progress: {read_int(pm, obj + OFFSET_PROGRESS)}")
        if ctx.max_stage_addr:
            logger.info(f"MaxStage: {read_int(pm, ctx.max_stage_addr)}")
        logger.info(f"Fish received: {ctx.fish_received}")
        logger.info(f"Max allowed stage: {max_allowed_stage(ctx.fish_received)}")


# ── Context ───────────────────────────────────────────────────────────────────

class FF2Context(CommonContext):
    game                   = GAME_NAME
    command_processor      = FF2CommandProcessor
    items_handling         = 0b111  # full remote items

    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)

        # game state
        self.pm:              Optional[pymem.Pymem] = None
        self.level_obj:       Optional[int]         = None
        self.max_stage_addr:  Optional[int]         = None
        self.fish_received:   int                   = 0
        self.game_ready:      bool                  = False

        # watcher state
        self._stop_event                    = threading.Event()
        self._last_level_id:                Optional[int] = None
        self._last_stage:                   Optional[int] = None
        self._last_max_stage:               Optional[int] = None
        self._last_lives:                   Optional[int] = None
        self._stable_level_id:              Optional[int] = None
        self._stable_count:                 int           = 0
        self._completed_levels:             set           = set()
        self._completed_stages:             set           = set()
        self._death_link_enabled:           bool          = False
        self._death_link_written_lives:     Optional[int] = False

        # boss state
        self.boss_hp_addr:       Optional[int] = None
        self._boss_hp_capturing: bool          = False

        # fishy state
        self.player_fish:    Optional[int] = None
        self.sub_object:     Optional[int] = None

        # ability state
        self.base:           Optional[int] = None
        self.dash_received:  bool          = False
        self.suck_received:  bool          = False

        # shuffle state (persists across game restarts — same seed = same shuffle)
        self.level_shuffle:      Optional[List[int]] = None
        self._shuffle_cave_addr: Optional[int]       = None

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            slot_data = args.get("slot_data", {})
            self._death_link_enabled = bool(slot_data.get("death_link", False))
            if self._death_link_enabled:
                Utils.async_start(self.update_death_link(True))
            shuffle = slot_data.get("level_shuffle")
            if shuffle:
                self.level_shuffle = shuffle
                if self.game_ready and self.base and self.pm:
                    self._install_shuffle_hook(shuffle)
            logger.info(f"[FF2] Connected. DeathLink: {self._death_link_enabled}")

        elif cmd == "ReceivedItems":
            is_full_resend = args.get("index", 0) == 0
            if is_full_resend:
                self.fish_received = 0  # full resend — recount from scratch
                self.dash_received = False
                self.suck_received = False
                if self.game_ready and self.base:
                    self._block_dash()
                    self._block_suck()
            for item in args["items"]:
                item_id = item.item
                if item_id == ITEM_PROGRESSIVE_FISH:
                    self.fish_received += 1
                    logger.info(f"[FF2] Received Progressive Fish ({self.fish_received} total)")
                    if self.game_ready and self.max_stage_addr:
                        self._apply_fish_item()
                elif item_id == ITEM_1UP:
                    logger.info("[FF2] Received 1-Up")
                    if not is_full_resend and self.game_ready and self.level_obj:
                        self._apply_1up()
                elif item_id == ITEM_DASH:
                    self.dash_received = True
                    logger.info("[FF2] Received Dash")
                    if self.game_ready and self.base:
                        self._unblock_dash()
                elif item_id == ITEM_SUCK:
                    self.suck_received = True
                    logger.info("[FF2] Received Suck")
                    if self.game_ready and self.base:
                        self._unblock_suck()

        elif cmd == "Bounced":
            if self._death_link_enabled and "DeathLink" in args.get("tags", []):
                source = args.get("data", {}).get("source", "")
                if source == self.player_names.get(self.slot, ""):
                    return
                self._receive_death_link()


    def _block_dash(self):
        try:
            write_bytes(self.pm, self.base + DASH_CALL_OFFSET, DASH_BLOCKED)
            logger.info("[FF2] Dash blocked")
        except Exception as e:
            logger.error(f"[FF2] Failed to block dash: {e}")

    def _unblock_dash(self):
        try:
            write_bytes(self.pm, self.base + DASH_CALL_OFFSET, DASH_UNBLOCKED)
            logger.info("[FF2] Dash unblocked")
        except Exception as e:
            logger.error(f"[FF2] Failed to unblock dash: {e}")

    def _block_suck(self):
        try:
            write_bytes(self.pm, self.base + SUCK_CALL_OFFSET, SUCK_BLOCKED)
            logger.info("[FF2] Suck blocked")
        except Exception as e:
            logger.error(f"[FF2] Failed to block suck: {e}")

    def _unblock_suck(self):
        try:
            write_bytes(self.pm, self.base + SUCK_CALL_OFFSET, SUCK_UNBLOCKED)
            logger.info("[FF2] Suck unblocked")
        except Exception as e:
            logger.error(f"[FF2] Failed to unblock suck: {e}")

    def _content_level(self, slot: int) -> int:
        """Map a map-slot level ID to the content level ID for that slot."""
        if self.level_shuffle and 0 <= slot < len(self.level_shuffle):
            return self.level_shuffle[slot]
        return slot

    def _install_shuffle_hook(self, shuffle: List[int]) -> bool:
        if self._shuffle_cave_addr:
            self._remove_shuffle_hook()

        pm   = self.pm
        base = self.base
        MEM_COMMIT             = 0x1000
        MEM_RESERVE            = 0x2000
        PAGE_EXECUTE_READWRITE = 0x40

        block = ctypes.windll.kernel32.VirtualAllocEx(
            pm.process_handle, None, 60 + 32 + 25,
            MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE,
        )
        if not block:
            logger.error("[FF2] Shuffle hook: alloc failed")
            return False

        table_addr = block
        cave1_addr = block + 60
        cave2_addr = block + 60 + 32

        written = ctypes.c_size_t(0)
        ctypes.windll.kernel32.WriteProcessMemory(
            pm.process_handle, ctypes.c_void_p(table_addr),
            bytes(shuffle[:60]), 60, ctypes.byref(written),
        )

        cave1, cave2 = _build_shuffle_caves(table_addr, cave1_addr, cave2_addr)
        ctypes.windll.kernel32.WriteProcessMemory(
            pm.process_handle, ctypes.c_void_p(cave1_addr),
            cave1, len(cave1), ctypes.byref(written),
        )
        ctypes.windll.kernel32.WriteProcessMemory(
            pm.process_handle, ctypes.c_void_p(cave2_addr),
            cave2, len(cave2), ctypes.byref(written),
        )

        site1 = base + SHUFFLE_CLICK_OFFSET
        rel1  = (cave1_addr - (site1 + 5)) & 0xFFFFFFFF
        write_bytes(pm, site1, b'\xE8' + struct.pack('<I', rel1) + b'\x90\x90\x90')

        site2 = base + SHUFFLE_ADVANCE_OFFSET
        rel2  = (cave2_addr - (site2 + 5)) & 0xFFFFFFFF
        write_bytes(pm, site2, b'\xE8' + struct.pack('<I', rel2))

        self._shuffle_cave_addr = block
        logger.info(f"[FF2] Shuffle hook installed (block: 0x{block:08X})")
        return True

    def _remove_shuffle_hook(self) -> None:
        cave = self._shuffle_cave_addr
        if not cave:
            return
        if self.pm and self.base:
            try:
                write_bytes(self.pm, self.base + SHUFFLE_CLICK_OFFSET,   SHUFFLE_CLICK_ORIGINAL)
            except Exception:
                pass
            try:
                write_bytes(self.pm, self.base + SHUFFLE_ADVANCE_OFFSET, SHUFFLE_ADVANCE_ORIGINAL)
            except Exception:
                pass
        try:
            ctypes.windll.kernel32.VirtualFreeEx(
                self.pm.process_handle, ctypes.c_void_p(cave), 0, 0x8000,
            )
        except Exception:
            pass
        self._shuffle_cave_addr = None
        logger.info("[FF2] Shuffle hook removed")

    def _apply_fish_item(self):
        try:
            allowed = max_allowed_stage(self.fish_received)
            current = read_int(self.pm, self.max_stage_addr)
            if current < allowed:
                # check if the gateway level (last level of previous zone) is already completed
                # if so, set directly to the new boundary so player doesn't have to replay it
                new_zone_start = ZONE_BOUNDARIES[self.fish_received] if self.fish_received < len(ZONE_BOUNDARIES) else 999
                gateway_level_id = new_zone_start - 1  # 0-indexed
                if gateway_level_id in self._completed_levels:
                    write_int(self.pm, self.max_stage_addr, new_zone_start)
                    logger.info(f"[FF2] Fish zone unlocked — mode0MaxStage set to {new_zone_start} (gateway already cleared)")
                # else:
                #     write_int(self.pm, self.max_stage_addr, allowed)
                #     logger.info(f"[FF2] Fish zone unlocked — mode0MaxStage: {allowed}")
        except Exception as e:
            logger.error(f"[FF2] Failed to apply fish item: {e}")

    def _apply_1up(self):
        try:
            current = read_int(self.pm, self.level_obj + OFFSET_LIVES)
            write_int(self.pm, self.level_obj + OFFSET_LIVES, current + 1)
            logger.info(f"[FF2] 1-Up applied — lives: {current + 1}")
        except Exception as e:
            logger.error(f"[FF2] Failed to apply 1-Up: {e}")

    def _send_location(self, location_id: int):
        Utils.async_start(self.send_msgs([{
            "cmd": "LocationChecks",
            "locations": [location_id],
        }]))

    def _send_goal(self):
        Utils.async_start(self.send_msgs([{
            "cmd": "StatusUpdate",
            "status": 30,  # ClientStatus.CLIENT_GOAL
        }]))

    def _send_death_link(self):
        if self._death_link_enabled:
            logger.info(f"[FF2] DeathLink sent (lives: {self._last_lives} -> {self._last_lives - 1})")
            Utils.async_start(self.send_msgs([{
                "cmd": "Bounce",
                "tags": ["DeathLink"],
                "data": {
                    "time":   asyncio.get_event_loop().time(),
                    "cause":  "Lost a life",
                    "source": self.player_names.get(self.slot, "FF2 Player"),
                },
            }]))

    def _receive_death_link(self) -> None:
        if not self.game_ready:
            logger.info("[FF2] DeathLink — game not ready, dropping"); return

        player_fish = self.player_fish
        sub_object  = self.sub_object

        if player_fish is None or sub_object is None:
            logger.info("[FF2] DeathLink — no valid fish pointer, dropping"); return

        if not self.level_obj:
            logger.info("[FF2] DeathLink — no level object, dropping"); return

        try:
            level_id    = read_int(self.pm, self.level_obj + OFFSET_LEVEL_ID)
            content_id  = self._content_level(level_id)
            if (content_id + 1) in BONUS_LEVELS:
                logger.info(f"[FF2] DeathLink — bonus content {content_id + 1} at slot {level_id + 1}, dropping"); return
        except Exception:
            return

        try:
            alive_ptr = read_int(self.pm, sub_object + OFFSET_ALIVE_PTR)
        except Exception as e:
            logger.error(f"[FF2] DeathLink — alive_ptr read failed: {e}"); return

        if alive_ptr == 0:
            logger.info("[FF2] DeathLink — player not spawned, dropping"); return

        try:
            current = read_int(self.pm, self.level_obj + OFFSET_LIVES)
            self._death_link_written_lives = max(0, current - 1)
            trigger_death(self.pm, player_fish, sub_object)
            logger.info("[FF2] DeathLink — death triggered")
        except Exception as e:
            logger.error(f"[FF2] DeathLink apply failed: {e}")

# ── Shuffle cave builder ──────────────────────────────────────────────────────

def _build_shuffle_caves(table_addr: int, cave1_addr: int, cave2_addr: int):
    """
    Build x86 machine code for the two level-shuffle intercept caves.

    Cave 1 (map click, 32 bytes):
      Reads slot N from [ecx+0xC], looks up content M = table[N],
      puts M in ecx, then tail-calls 0x4980C0 (content loader).
      Slots 0 and 59 pass through unchanged.

    Cave 2 (auto-advance, 25 bytes):
      Saves level_object (eax) and slot N+1 (ebx), writes content M
      to [level_obj+0x28] so 0x4966D0 loads the right content,
      calls 0x4966D0, then restores slot N+1 to [level_obj+0x28].
    """
    # ── Cave 1 ────────────────────────────────────────────────────────────────
    c1 = bytearray()
    c1 += b'\x50'                                    # push eax
    c1 += b'\x52'                                    # push edx
    c1 += b'\x8B\x41\x0C'                           # mov eax,[ecx+0xC]  (slot N)
    c1 += b'\x85\xC0'                               # test eax,eax
    c1 += b'\x74\x0E'                               # jz done  (slot 0 → pass through)
    c1 += b'\x83\xF8\x3B'                           # cmp eax,59
    c1 += b'\x74\x09'                               # je done  (slot 59 → pass through)
    c1 += b'\xBA' + struct.pack('<I', table_addr)   # mov edx,table_addr
    c1 += b'\x0F\xB6\x04\x02'                       # movzx eax,byte[edx+eax]
    # done (offset 23):
    c1 += b'\x89\xC1'                               # mov ecx,eax
    c1 += b'\x5A'                                   # pop edx
    c1 += b'\x58'                                   # pop eax
    rel1 = (CONTENT_CLICK_TARGET - (cave1_addr + len(c1) + 5)) & 0xFFFFFFFF
    c1 += b'\xE9' + struct.pack('<I', rel1)         # jmp 0x4980C0
    assert len(c1) == 32, f"Cave 1 size mismatch: {len(c1)}"

    # ── Cave 2 ────────────────────────────────────────────────────────────────
    # Entry: eax = level_object, ebx = next slot N+1, [esp+0] = ret addr
    c2 = bytearray()
    c2 += b'\x50'                                   # push eax  (level_object)
    c2 += b'\x52'                                   # push edx
    c2 += b'\xBA' + struct.pack('<I', table_addr)  # mov edx,table_addr
    c2 += b'\x0F\xB6\x14\x1A'                      # movzx edx,byte[edx+ebx]  (content M)
    c2 += b'\x89\x50\x28'                          # mov [eax+0x28],edx  (write content)
    c2 += b'\x5A'                                  # pop edx
    rel2 = (CONTENT_ADVANCE_TARGET - (cave2_addr + len(c2) + 5)) & 0xFFFFFFFF
    c2 += b'\xE8' + struct.pack('<I', rel2)        # call 0x4966D0
    c2 += b'\x58'                                  # pop eax  (level_object)
    c2 += b'\x89\x58\x28'                         # mov [eax+0x28],ebx  (restore slot)
    c2 += b'\xC3'                                  # ret
    assert len(c2) == 25, f"Cave 2 size mismatch: {len(c2)}"

    return bytes(c1), bytes(c2)


# ── Deathlink routine ───────────────────────────────────────────────────────────────
def trigger_death(pm: pymem.Pymem, player_fish: int, sub_object: int) -> bool:
    MEM_COMMIT             = 0x1000
    MEM_RESERVE            = 0x2000
    PAGE_EXECUTE_READWRITE = 0x40

    cave = ctypes.windll.kernel32.VirtualAllocEx(
        pm.process_handle, None, 64,
        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE
    )
    if not cave:
        return False

    call_site  = cave + 6
    rel_offset = (DEATH_FUNC - (call_site + 5)) & 0xFFFFFFFF

    shellcode = bytearray([
        0x51,
        0xB9, *sub_object.to_bytes(4, 'little'),
        0xE8, *rel_offset.to_bytes(4, 'little'),
        0x59,
        0xC3,
    ])

    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle, ctypes.c_void_p(cave),
        bytes(shellcode), len(shellcode), ctypes.byref(written)
    )

    thread = ctypes.windll.kernel32.CreateRemoteThread(
        pm.process_handle, None, 0,
        ctypes.c_void_p(cave), None, 0, None
    )
    if not thread:
        ctypes.windll.kernel32.VirtualFreeEx(
            pm.process_handle, ctypes.c_void_p(cave), 0, 0x8000
        )
        return False

    ctypes.windll.kernel32.WaitForSingleObject(thread, 3000)
    ctypes.windll.kernel32.CloseHandle(thread)
    ctypes.windll.kernel32.VirtualFreeEx(
        pm.process_handle, ctypes.c_void_p(cave), 0, 0x8000
    )

    write_int(pm, player_fish + OFFSET_RESPAWN_FLAG, 0)
    return True

# ── Game watcher loop ─────────────────────────────────────────────────────────

async def game_watcher(ctx: FF2Context):
    STABLE_THRESHOLD   = 3
    CRASH_ERROR_THRESH = 5
    loop = asyncio.get_event_loop()

    while not ctx.exit_event.is_set():

        # ── wait for / attach to game process ────────────────────────────
        while not ctx.exit_event.is_set():
            try:
                ctx.pm = pymem.Pymem(PROCESS_NAME)
                logger.info(f"[FF2] Attached to {PROCESS_NAME}")
                break
            except Exception:
                logger.info(f"[FF2] Waiting for {PROCESS_NAME}...")
                await asyncio.sleep(3)

        if ctx.exit_event.is_set():
            break

        # reset game-session state (Archipelago state — fish_received, completed_*, etc. — preserved)
        # level_shuffle is also preserved — same seed = same shuffle every session
        ctx._stop_event.set()
        ctx._stop_event      = threading.Event()
        ctx.level_obj         = None
        ctx.max_stage_addr    = None
        ctx.player_fish       = None
        ctx.sub_object        = None
        ctx.game_ready        = False
        ctx.boss_hp_addr      = None
        ctx._boss_hp_capturing  = False
        ctx._last_level_id    = None
        ctx._last_stage       = None
        ctx._last_max_stage   = None
        ctx._last_lives       = None
        ctx._stable_level_id  = None
        ctx._stable_count     = 0
        ctx._shuffle_cave_addr = None   # old process memory is gone; reinstall on next ready

        pm   = ctx.pm
        base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        logger.info(f"[FF2] Base address: 0x{base:08X}")

        ctx.level_obj = await loop.run_in_executor(None, capture_level_object, pm, base)
        if not ctx.level_obj:
            logger.error("[FF2] Failed to capture level object.")
            continue

        ctx.base      = base
        ctx.game_ready = True
        logger.info("[FF2] Game ready. Watching for checks...")
        make_window_resizable()
        _start_proxy_window(ctx._stop_event)

        if ctx.level_shuffle:
            ctx._install_shuffle_hook(ctx.level_shuffle)

        ctx._block_dash()
        if ctx.dash_received:
            ctx._unblock_dash()
        ctx._block_suck()
        if ctx.suck_received:
            ctx._unblock_suck()

        if ctx.fish_received > 0 and ctx.max_stage_addr:
            ctx._apply_fish_item()

        async def _capture_max_stage():
            result = await loop.run_in_executor(
                None, capture_max_stage_object, pm, base, ctx._stop_event
            )
            if result:
                ctx.max_stage_addr = result
                if ctx.fish_received > 0:
                    ctx._apply_fish_item()

        Utils.async_start(_capture_max_stage())

        async def _capture_player_fish():
            target = base + PLAYER_FISH_OFFSET
            result = await loop.run_in_executor(
                None, _do_capture_player_fish, pm, target, ctx._stop_event
            )
            if result:
                ctx.player_fish = result["player_fish"]
                ctx.sub_object  = result["sub_object"]
                logger.info(f"[FF2] Player fish: 0x{ctx.player_fish:08X} sub: 0x{ctx.sub_object:08X}")
            if ctx.level_obj:
                try:
                    if read_int(pm, ctx.level_obj + OFFSET_LEVEL_ID) == 59 and not ctx._boss_hp_capturing:
                        ctx.boss_hp_addr       = None
                        ctx._boss_hp_capturing = True
                        Utils.async_start(_capture_boss_hp())
                except Exception:
                    pass

        Utils.async_start(_capture_player_fish())

        async def _capture_boss_hp():
            target = base + BOSS_HP_OFFSET
            result = await loop.run_in_executor(
                None, _do_capture_boss_hp, pm, target, ctx._stop_event
            )
            if result:
                ctx.boss_hp_addr = result
                logger.info(f"[FF2] Boss HP counter: 0x{result:08X}")
            ctx._boss_hp_capturing = False

        # ── main poll loop ───────────────────────────────────────────────
        consecutive_errors = 0
        while not ctx.exit_event.is_set():
            try:
                current_level = read_int(pm, ctx.level_obj + OFFSET_LEVEL_ID)
                current_stage = read_int(pm, ctx.level_obj + OFFSET_STAGE)
                current_lives = read_int(pm, ctx.level_obj + OFFSET_LIVES)
                consecutive_errors = 0

                # ── debounce level_id ─────────────────────────────────────
                if current_level == ctx._stable_level_id:
                    ctx._stable_count += 1
                else:
                    ctx._stable_level_id = current_level
                    ctx._stable_count    = 1

                if ctx._stable_count >= STABLE_THRESHOLD:
                    current_level = ctx._stable_level_id

                    # ── stage checks (stages 1 and 2 only) ───────────────
                    if ctx._last_stage is not None and current_stage != ctx._last_stage:
                        if current_stage in (1, 2):
                            check_key = (current_level, current_stage)
                            if check_key not in ctx._completed_stages:
                                ctx._completed_stages.add(check_key)
                                content_lvl = ctx._content_level(current_level)
                                is_bonus    = (content_lvl + 1) in BONUS_LEVELS
                                if not is_bonus:
                                    loc_id = location_id_for(content_lvl, current_stage - 1)
                                    ctx._send_location(loc_id)
                                    logger.info(f"[FF2] Check: Slot {current_level + 1} → Content {content_lvl + 1} Stage {current_stage}")

                    # ── level completion ──────────────────────────────────
                    if ctx._last_level_id is not None and current_level == ctx._last_level_id + 1:
                        completed_id = ctx._last_level_id
                        if completed_id not in ctx._completed_levels:
                            ctx._completed_levels.add(completed_id)
                            content_lvl = ctx._content_level(completed_id)
                            loc_id      = location_id_for(content_lvl, 2)
                            ctx._send_location(loc_id)
                            logger.info(f"[FF2] Check: Slot {completed_id + 1} → Content {content_lvl + 1} Complete")

                        ctx.player_fish = None
                        ctx.sub_object  = None
                        logger.info("[FF2] Player pointers cleared — re-capturing for new level")
                        Utils.async_start(_capture_player_fish())

                    ctx._last_level_id = current_level
                    ctx._last_stage    = current_stage

                # ── boss defeat check ─────────────────────────────────────
                if ctx.boss_hp_addr is not None and current_level == 59:
                    try:
                        if read_int(pm, ctx.boss_hp_addr) >= 20:
                            ctx._send_goal()
                            logger.info("[FF2] Boss defeated (20 hits) — goal sent!")
                            ctx.boss_hp_addr = None  # prevent re-triggering
                    except Exception:
                        pass

                # ── DeathLink send ────────────────────────────────────────
                if ctx._last_lives is not None and current_lives == ctx._last_lives - 1:
                    if ctx._death_link_written_lives == current_lives:
                        ctx._death_link_written_lives = None
                    else:
                        ctx._send_death_link()
                ctx._last_lives = current_lives

                # ── clamp mode0MaxStage ───────────────────────────────────
                if ctx.max_stage_addr is not None:
                    current_max = read_int(pm, ctx.max_stage_addr)
                    allowed = max_allowed_stage(ctx.fish_received)
                    if current_max > allowed:
                        write_int(pm, ctx.max_stage_addr, allowed)
                        logger.info(f"[FF2] MaxStage clamped {current_max} -> {allowed}")
                        reset_to_boundary_level(pm, ctx.level_obj)
                    ctx._last_max_stage = current_max

            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= CRASH_ERROR_THRESH:
                    logger.warning("[FF2] Game process lost — resetting and waiting to re-attach")
                    ctx._stop_event.set()
                    ctx.game_ready = False
                    break
                logger.debug(f"[FF2] Watcher error: {e}")

            await asyncio.sleep(0.1)

    ctx._stop_event.set()

def _do_capture_boss_hp(pm, target, stop_event):
    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        return None
    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)
    for tid in get_process_threads(pm.process_id):
        set_bp_on_thread(tid, target, 0)

    result      = None
    debug_event = DEBUG_EVENT()
    while not stop_event.is_set() and result is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue
        event_code = debug_event.dwDebugEventCode
        tid        = debug_event.dwThreadId
        if event_code == 1:
            code     = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            if exc_addr == target and code not in (0x80000003,):
                th = get_thread_handle(tid)
                if th:
                    if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                        try:
                            ctx_ = CONTEXT()
                            ctx_.ContextFlags = CONTEXT_CAPTURE
                            if Wow64GetThreadContext(th, ctypes.byref(ctx_)) and ctx_.Eip == target:
                                ecx = ctx_.Ecx
                                if ecx:
                                    result = ecx + OFFSET_BOSS_HP
                                    clear_hardware_breakpoint(th, 0)
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)
        elif event_code == 3:
            set_bp_on_thread(tid, target, 0)
        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )
        if result is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break
    return result


def _do_capture_player_fish(pm, target, stop_event):
    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        return None
    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)
    for tid in get_process_threads(pm.process_id):
        set_bp_on_thread(tid, target, 0)

    result      = None
    debug_event = DEBUG_EVENT()
    while not stop_event.is_set() and result is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue
        event_code = debug_event.dwDebugEventCode
        tid        = debug_event.dwThreadId
        if event_code == 1:
            code     = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            if exc_addr == target and code not in (0x80000003,):
                th = get_thread_handle(tid)
                if th:
                    if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                        try:
                            ctx_ = CONTEXT()
                            ctx_.ContextFlags = CONTEXT_CAPTURE
                            if Wow64GetThreadContext(th, ctypes.byref(ctx_)) and ctx_.Eip == target:
                                ecx = ctx_.Ecx
                                if ecx:
                                    try:
                                        sub = read_int(pm, ecx + OFFSET_SUB_OBJECT)
                                        if sub:
                                            result = {"player_fish": ecx, "sub_object": sub}
                                            clear_hardware_breakpoint(th, 0)
                                    except Exception:
                                        pass
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)
        elif event_code == 3:
            set_bp_on_thread(tid, target, 0)
        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )
        if result is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break
    return result

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    Utils.init_logging("FF2Client", exception_logger="Client")

    async def _main():
        parser = get_base_parser(description="Feeding Frenzy 2 Archipelago Client")
        args   = parser.parse_args()

        ctx = FF2Context(args.connect, args.password)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        watcher = asyncio.create_task(game_watcher(ctx), name="game watcher")

        await ctx.exit_event.wait()
        ctx._stop_event.set()
        watcher.cancel()
        await ctx.shutdown()

    import colorama
    colorama.init()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
