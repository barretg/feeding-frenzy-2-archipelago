import pymem
import pymem.process
import ctypes
import ctypes.wintypes as wintypes
import sys
import random as _random
import struct
import threading
import time

PROCESS_NAME = "popcapgame1.exe"

# breakpoint offsets
LEVEL_STATE_OFFSET        = 0x9C064
MAX_STAGE_OFFSET          = 0x9AED3
PLAYER_FISH_OFFSET        = 0x38D47
COMPLETION_CLEAR_OFFSET   = 0xF1F19   # mov byte ptr [edi+0x391],01  (stageClear)
COMPLETION_PERFECT_OFFSET = 0xF218F   # mov byte ptr [ebx+0x391],01  (stagePerfect)

# confirmed offsets from captured eax value (level object)
OFFSET_LIVES          = 0x10
OFFSET_SCORE          = 0x14
OFFSET_STAGE          = 0x24
OFFSET_LEVEL_ID       = 0x28
OFFSET_SCORE_SNAPSHOT = 0x30
OFFSET_LIVES_SNAPSHOT = 0x34
OFFSET_PROGRESS       = 0x40

# max stage offset from ecx
OFFSET_MAX_STAGE = 0x58

# player fish offsets
OFFSET_SUB_OBJECT = 0x8C
OFFSET_ALIVE_PTR  = 0x78
OFFSET_DASH_FLAG  = 0xD2

# zone boundaries (0-indexed level where each new zone starts)
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 45, 48, 51, 54, 57]

# dash ability patch — actual dash call site at 0x004248AD (WM_LBUTTONDOWN handler)
# 0x0042490B was cursor snap only; real dash trigger is call 0x4204A0 at 0x004248AD
DASH_CALL_OFFSET = 0x248AD
DASH_BLOCKED     = bytes([0x90, 0x90, 0x90, 0x90, 0x90])   # NOP x5
DASH_UNBLOCKED   = bytes([0xE8, 0xEE, 0xBB, 0xFF, 0xFF])   # call 0x4204A0

# suck ability patch — call site at 0x00424A31 (WM_RBUTTONDOWN handler)
SUCK_CALL_OFFSET = 0x24A31
SUCK_BLOCKED     = bytes([0x90, 0x90, 0x90, 0x90, 0x90])   # NOP x5
SUCK_UNBLOCKED   = bytes([0xE8, 0xAA, 0x98, 0x06, 0x00])   # call 0x48E2E0

# focus-pause patch — forces WM_ACTIVATE handler to always call with active=1
# WndProc: 00424780, WM_ACTIVATE handler: 0042497C
# at 0042497F: setne al (0F 95 C0) -> mov al,1 + nop (B0 01 90)
# game always enters the "activated" path, never pauses on focus loss
FOCUS_PAUSE_OFFSET   = 0x2497F
FOCUS_PAUSE_ORIGINAL = bytes([0x0F, 0x95, 0xC0])
FOCUS_PAUSE_NOP      = bytes([0xB0, 0x01, 0x90])
BONUS_LEVELS    = frozenset({4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60})

# level-shuffle hook — read-side remap (3 patch sites, never alters level_id writes)
# Site 1: 0x49AB70 — mov ecx,[eax+28]; test ecx,ecx  (map-click level data getter)
SHUFFLE_SITE1_OFFSET   = 0x9AB70
SHUFFLE_SITE1_ORIGINAL = bytes([0x8B, 0x48, 0x28, 0x85, 0xC9])
# Site 2: 0x40510A — mov eax,[edi]; mov ecx,[eax+28]  (continue-button level data getter)
SHUFFLE_SITE2_OFFSET   = 0x510A
SHUFFLE_SITE2_ORIGINAL = bytes([0x8B, 0x07, 0x8B, 0x48, 0x28])
# Site 3: 0x403468 — push esi; push [eax+28]; lea esi,[eax+50]  (level data lookup helper)
SHUFFLE_SITE3_OFFSET   = 0x3468
SHUFFLE_SITE3_ORIGINAL = bytes([0x56, 0xFF, 0x70, 0x28, 0x8D, 0x70, 0x50])

MEM_COMMIT             = 0x1000
MEM_RESERVE            = 0x2000
MEM_RELEASE            = 0x8000
PAGE_EXECUTE_READWRITE = 0x40

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

Wow64GetThreadContext          = ctypes.windll.kernel32.Wow64GetThreadContext
Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Wow64GetThreadContext.restype  = wintypes.BOOL

Wow64SetThreadContext          = ctypes.windll.kernel32.Wow64SetThreadContext
Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Wow64SetThreadContext.restype  = wintypes.BOOL

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

def max_allowed_stage(fish_received):
    next_zone_idx = fish_received + 1
    if next_zone_idx >= len(ZONE_BOUNDARIES):
        return 999
    return ZONE_BOUNDARIES[next_zone_idx] - 1

def get_process_threads(pid):
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

def get_thread_handle(tid):
    return ctypes.windll.kernel32.OpenThread(THREAD_ACCESS, False, tid)

def set_hardware_breakpoint(thread_handle, address, dr_index=0, bp_type=0, bp_len=3):
    """
    bp_type: 0=execute, 1=write, 3=read/write
    bp_len:  0=1B, 1=2B, 3=4B (ignored for execute BPs)
    """
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
        ctx.Dr7 &= ~(0xF << (16 + dr_index * 4))
        if bp_type:
            nibble = (bp_type & 3) | ((bp_len & 3) << 2)
            ctx.Dr7 |= (nibble << (16 + dr_index * 4))
        ctx.Dr7 |= (0x1 << (dr_index * 2))
        ctx.ContextFlags = CONTEXT_CAPTURE
        return bool(Wow64SetThreadContext(thread_handle, ctypes.byref(ctx)))
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)

def clear_hardware_breakpoint(thread_handle, dr_index=0):
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

def set_bp_on_thread(tid, address, dr_index=0, bp_type=0, bp_len=3):
    th = get_thread_handle(tid)
    if th:
        ok = set_hardware_breakpoint(th, address, dr_index, bp_type, bp_len)
        ctypes.windll.kernel32.CloseHandle(th)
        return ok
    return False

class DebugSession:
    """Single persistent debugger attachment. Dispatches hardware BP events to registered callbacks.

    DR index assignments:
      DR0 — level object capture (one-shot), then reused for probe / watchlevelid
      DR1 — player fish capture (persistent; re-fires on every level entry)
      DR2 — max stage capture (one-shot)
      DR3 — spare

    Callbacks receive (ctx) and return True to keep the BP or False to remove it.
    """

    def __init__(self, pm):
        self.pm    = pm
        self._lock = threading.Lock()
        self._bps  = {}   # dr_index -> (address, bp_type, bp_len, callback)

    def start(self):
        # WaitForDebugEvent is thread-affine: must be called from the same thread
        # that called DebugActiveProcess. So we do both inside the loop thread and
        # signal back when the attach succeeds (or fails).
        ready = threading.Event()
        err   = [None]

        def _thread():
            if not ctypes.windll.kernel32.DebugActiveProcess(self.pm.process_id):
                err[0] = ctypes.windll.kernel32.GetLastError()
                ready.set()
                return
            ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)
            ready.set()
            self._loop()

        threading.Thread(target=_thread, name="DebugSession", daemon=True).start()
        ready.wait()
        if err[0]:
            raise RuntimeError(f"DebugActiveProcess failed: error {err[0]}")

    def stop(self):
        ctypes.windll.kernel32.DebugActiveProcessStop(self.pm.process_id)

    def register(self, dr_index, address, callback, bp_type=0, bp_len=3):
        with self._lock:
            self._bps[dr_index] = (address, bp_type, bp_len, callback)
        for tid in get_process_threads(self.pm.process_id):
            set_bp_on_thread(tid, address, dr_index, bp_type, bp_len)

    def unregister(self, dr_index):
        with self._lock:
            self._bps.pop(dr_index, None)
        for tid in get_process_threads(self.pm.process_id):
            th = get_thread_handle(tid)
            if th:
                clear_hardware_breakpoint(th, dr_index)
                ctypes.windll.kernel32.CloseHandle(th)

    def _loop(self):
        debug_event = DEBUG_EVENT()
        while True:
            if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
                continue
            event_code = debug_event.dwDebugEventCode
            tid        = debug_event.dwThreadId

            if event_code == 1:   # EXCEPTION_DEBUG_EVENT
                code     = debug_event.u.Exception.ExceptionRecord.ExceptionCode
                exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress

                with self._lock:
                    bps = dict(self._bps)

                if bps:
                    bp_addrs = {addr for addr, _, _, _ in bps.values()}
                    is_hw = (code == 0x80000004 or
                             (code not in (0x80000003,) and exc_addr in bp_addrs))
                    if is_hw:
                        th = get_thread_handle(tid)
                        if th:
                            if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                                try:
                                    ctx = CONTEXT()
                                    ctx.ContextFlags = CONTEXT_CAPTURE
                                    if Wow64GetThreadContext(th, ctypes.byref(ctx)):
                                        to_remove = []
                                        for dr_idx, (addr, bp_type, bp_len, cb) in bps.items():
                                            if bp_type == 0:
                                                fired = (ctx.Eip == addr)
                                            else:
                                                fired = bool(ctx.Dr6 & (1 << dr_idx))
                                            if fired:
                                                ctx.Dr6 = 0
                                                ctx.ContextFlags = CONTEXT_CAPTURE
                                                Wow64SetThreadContext(th, ctypes.byref(ctx))
                                                keep = cb(ctx)
                                                if not keep:
                                                    to_remove.append(dr_idx)
                                        for dr_idx in to_remove:
                                            with self._lock:
                                                self._bps.pop(dr_idx, None)
                                            clear_hardware_breakpoint(th, dr_idx)
                                finally:
                                    ctypes.windll.kernel32.ResumeThread(th)
                            ctypes.windll.kernel32.CloseHandle(th)

            elif event_code == 3:   # CREATE_THREAD_DEBUG_EVENT
                with self._lock:
                    bps = dict(self._bps)
                for dr_idx, (addr, bp_type, bp_len, cb) in bps.items():
                    set_bp_on_thread(tid, addr, dr_idx, bp_type, bp_len)

            ctypes.windll.kernel32.ContinueDebugEvent(debug_event.dwProcessId, tid, DBG_CONTINUE)


def capture_level_object(session, pm, base):
    target = base + LEVEL_STATE_OFFSET
    done   = threading.Event()
    result = [None]

    def on_hit(ctx):
        eax = ctx.Eax
        if eax:
            print(f"  Level object: 0x{eax:08X}")
            print(f"  lives    @ 0x{eax+OFFSET_LIVES:08X}")
            print(f"  score    @ 0x{eax+OFFSET_SCORE:08X}")
            print(f"  stage    @ 0x{eax+OFFSET_STAGE:08X}")
            print(f"  level_id @ 0x{eax+OFFSET_LEVEL_ID:08X}")
            print(f"  progress @ 0x{eax+OFFSET_PROGRESS:08X}")
            result[0] = eax
            done.set()
            return False   # remove BP (DR0 freed for probe/watchlevelid)
        return True

    print(f"Watching 0x{target:08X} — press Start Game to capture level object...")
    session.register(0, target, on_hit)
    done.wait()
    return result[0]


def register_player_fish_bp(session, pm, base, player_info):
    """Register a one-shot DR1 BP. Removes itself after the first valid capture.
    Re-called by level_watcher after each level completion."""
    target = base + PLAYER_FISH_OFFSET

    def on_hit(ctx):
        ecx = ctx.Ecx
        if not ecx:
            return True
        try:
            sub_object = read_int(pm, ecx + OFFSET_SUB_OBJECT)
            if not sub_object:
                return True
            info = {
                "player_fish": ecx,
                "sub_object":  sub_object,
                "dash_addr":   sub_object + OFFSET_DASH_FLAG,
                "alive_addr":  sub_object + OFFSET_ALIVE_PTR,
            }
            print(f"\n  [player] Player fish:  0x{ecx:08X}")
            print(f"  [player] Sub-object:   0x{sub_object:08X}")
            print(f"  [player] Dash flag  @  0x{info['dash_addr']:08X}")
            print(f"  [player] Alive ptr  @  0x{info['alive_addr']:08X}")
            print("> ", end="", flush=True)
            player_info[0] = info
            return False   # one-shot; level_watcher re-registers after level change
        except Exception:
            return True

    print(f"  [player] Watching 0x{target:08X} — enter a level to capture player fish...")
    session.register(1, target, on_hit)


def start_max_stage_capture(session, pm, base, max_stage_addr):
    """Register a one-shot DR2 BP that captures mode0MaxStage address on first valid hit."""
    target = base + MAX_STAGE_OFFSET
    print(f"  [maxstage] Watching 0x{target:08X} — complete a level to capture max stage...")

    def on_hit(ctx):
        ecx       = ctx.Ecx
        candidate = ecx + OFFSET_MAX_STAGE
        try:
            value = read_int(pm, candidate)
            if 0 <= value <= 100:
                print(f"\n  [maxstage] Captured ecx=0x{ecx:08X}")
                print(f"  [maxstage] mode0MaxStage @ 0x{candidate:08X} = {value}")
                print("> ", end="", flush=True)
                max_stage_addr[0] = candidate
                return False   # remove BP
            else:
                print(f"\n  [maxstage] Ignoring bad capture: value={value}")
                print("> ", end="", flush=True)
                return True
        except Exception:
            return True

    session.register(2, target, on_hit)

def read_int(pm, address):
    buf = pm.read_bytes(address, 4)
    return int.from_bytes(buf, byteorder="little")

def write_int(pm, address, value):
    buf     = value.to_bytes(4, byteorder="little")
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf, 4,
        ctypes.byref(written),
    )

def write_bytes(pm, address, data):
    buf     = (ctypes.c_byte * len(data))(*data)
    written = ctypes.c_size_t(0)
    ok = ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf, len(data),
        ctypes.byref(written),
    )
    return ok and written.value == len(data)

GWL_STYLE        = -16
WS_THICKFRAME    = 0x00040000
WS_MAXIMIZEBOX   = 0x00010000
WS_MINIMIZEBOX   = 0x00020000
WS_CAPTION       = 0x00C00000
WS_SYSMENU       = 0x00080000
WS_POPUP         = 0x80000000
SWP_NOMOVE       = 0x0002
SWP_NOSIZE       = 0x0001
SWP_NOZORDER     = 0x0004
SWP_FRAMECHANGED = 0x0020
MONITOR_DEFAULTTONEAREST = 0x0002

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork",    wintypes.RECT),
        ("dwFlags",   wintypes.DWORD),
    ]

# saved window state for borderless toggle: hwnd -> (style, RECT)
_borderless_saved = {}

# ── Mouse-coordinate rescale hook ─────────────────────────────────────────────
# The PopCap framework stretch-blits its native canvas to the full window client
# rect, but hit-tests mouse messages in raw client-pixel space against native
# layout rects. Borderless fullscreen therefore renders icons scaled up while
# their click boxes stay at native positions. This hook rewrites lParam of every
# mouse message (0x200-0x209) at WndProc entry, mapping client px -> native px in
# 16.16 fixed point. Scale factors live in the cave (block+0, block+4) and are
# updated from Python whenever the window size changes — self-correcting.
WNDPROC_OFFSET   = 0x24780
WNDPROC_RET_OFF  = 0x24786                       # resume after stolen prologue
WNDPROC_ORIGINAL = bytes([0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF8])  # push ebp; mov ebp,esp; and esp,-8

_logical_wh = [None]   # (w, h) native canvas, captured while windowed
_mouse_cave = [None]   # base of allocated cave block, or None

# ── Relative-input center fix (SetCursorPos IAT redirect) ─────────────────────
# Gameplay recenters the cursor every frame to the native canvas center
# (~400,300) via SetCursorPos. With scalemouse active, that parked position is
# scaled back to ~(167,125), so the resting delta from the canvas center is a
# constant negative and the fish runs to a corner. Fix: repoint the SetCursorPos
# IAT slot to a cave that forces the target to the TRUE client center (in screen
# coords). Then the parked cursor scales back exactly to the canvas center ->
# delta 0. Must be used together with scalemouse + borderless.
IAT_SETCURSORPOS = 0x146280                      # 0x546280 - image base

# cave layout: [+0]=screenX  [+4]=screenY  [+8]=real SetCursorPos  [+12]=enable  code@+16
_centerfix_cave = [None]      # (cave_base, real_addr) or None
_setcursorpos_real = [None]   # cached genuine SetCursorPos addr (survives toggles)


def _client_center_screen(hwnd):
    user32 = ctypes.windll.user32
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(r.right // 2, r.bottom // 2)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y

def make_window_resizable():
    hwnd = ctypes.windll.user32.FindWindowA(b"Gatsu", None)
    if not hwnd:
        print("  [window] Game window not found (is it running?)")
        return False
    style = ctypes.windll.user32.GetWindowLongA(hwnd, GWL_STYLE)
    style |= WS_THICKFRAME | WS_MAXIMIZEBOX
    ctypes.windll.user32.SetWindowLongA(hwnd, GWL_STYLE, style)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
    ctypes.windll.user32.ClipCursor(None)
    print(f"  [window] Resizable, cursor unclipped (hwnd=0x{hwnd:08X})")
    return True


def toggle_borderless():
    """Borderless windowed fullscreen on the game window — covers the monitor,
    strips the frame, does NOT change the monitor resolution. Toggles back to
    the previous windowed style/position on second call."""
    user32 = ctypes.windll.user32
    hwnd   = user32.FindWindowA(b"Gatsu", None)
    if not hwnd:
        print("  [window] Game window not found (is it running?)")
        return False

    if hwnd in _borderless_saved:
        style, rect = _borderless_saved.pop(hwnd)
        user32.SetWindowLongA(hwnd, GWL_STYLE, style)
        user32.SetWindowPos(hwnd, 0, rect.left, rect.top,
            rect.right - rect.left, rect.bottom - rect.top,
            SWP_NOZORDER | SWP_FRAMECHANGED)
        print(f"  [window] Restored windowed (hwnd=0x{hwnd:08X})")
        return True

    style = user32.GetWindowLongA(hwnd, GWL_STYLE)
    rect  = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    _borderless_saved[hwnd] = (style, rect)

    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi  = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoA(mon, ctypes.byref(mi))
    r = mi.rcMonitor

    new_style = (style & ~(WS_CAPTION | WS_THICKFRAME |
                           WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)) | WS_POPUP
    user32.SetWindowLongA(hwnd, GWL_STYLE, new_style)
    user32.SetWindowPos(hwnd, 0, r.left, r.top,
        r.right - r.left, r.bottom - r.top,
        SWP_NOZORDER | SWP_FRAMECHANGED)
    user32.ClipCursor(None)
    print(f"  [window] Borderless fullscreen {r.right - r.left}x{r.bottom - r.top} "
          f"(hwnd=0x{hwnd:08X})")
    return True


def _game_hwnd():
    return ctypes.windll.user32.FindWindowA(b"Gatsu", None)


def _client_size(hwnd):
    r = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def _build_mouse_cave(block, base):
    """Assemble the mouse-rescale cave. Layout: [block+0]=sx (16.16), [block+4]=sy,
    code at block+8. Hooked from WndProc entry; runs the stolen prologue and jumps
    back to WNDPROC_RET_OFF."""
    sx_addr = block + 0
    sy_addr = block + 4

    work = bytearray()
    work += bytes([0x0F, 0xBF, 0x45, 0x14])               # movsx eax,word [ebp+14]   ; X
    work += bytes([0x0F, 0xAF, 0x05]) + struct.pack('<I', sx_addr)  # imul eax,[sx]
    work += bytes([0xC1, 0xF8, 0x10])                     # sar eax,16
    work += bytes([0x0F, 0xB7, 0xD0])                     # movzx edx,ax              ; X'
    work += bytes([0x52])                                 # push edx
    work += bytes([0x8B, 0x45, 0x14])                     # mov eax,[ebp+14]
    work += bytes([0xC1, 0xF8, 0x10])                     # sar eax,16                ; Y
    work += bytes([0x0F, 0xAF, 0x05]) + struct.pack('<I', sy_addr)  # imul eax,[sy]
    work += bytes([0xC1, 0xF8, 0x10])                     # sar eax,16                ; Y'
    work += bytes([0xC1, 0xE0, 0x10])                     # shl eax,16
    work += bytes([0x5A])                                 # pop edx                   ; X'
    work += bytes([0x0F, 0xB7, 0xD2])                     # movzx edx,dx
    work += bytes([0x09, 0xD0])                           # or eax,edx
    work += bytes([0x89, 0x45, 0x14])                     # mov [ebp+14],eax          ; lParam'

    code = bytearray()
    code += bytes([0x55])                                 # push ebp
    code += bytes([0x8B, 0xEC])                           # mov ebp,esp
    code += bytes([0x50])                                 # push eax
    code += bytes([0x52])                                 # push edx
    code += bytes([0x8B, 0x45, 0x0C])                     # mov eax,[ebp+0C]          ; msg
    code += bytes([0x2D, 0x00, 0x02, 0x00, 0x00])         # sub eax,200
    code += bytes([0x83, 0xF8, 0x09])                     # cmp eax,9
    code += bytes([0x77, len(work)])                      # ja .restore  (skip if not 200..209)
    code += work
    code += bytes([0x5A])                                 # pop edx        (.restore)
    code += bytes([0x58])                                 # pop eax
    code += bytes([0x5D])                                 # pop ebp
    code += bytes([0x55])                                 # push ebp           (stolen)
    code += bytes([0x8B, 0xEC])                           # mov ebp,esp        (stolen)
    code += bytes([0x83, 0xE4, 0xF8])                     # and esp,FFFFFFF8   (stolen)
    jmp_pos  = block + 8 + len(code)
    ret_addr = base + WNDPROC_RET_OFF
    rel      = (ret_addr - (jmp_pos + 5)) & 0xFFFFFFFF
    code += bytes([0xE9]) + struct.pack('<I', rel)        # jmp WNDPROC_RET_OFF
    return bytes(code)


def install_mouse_scale(pm, base):
    hwnd = _game_hwnd()
    if not hwnd:
        print("  [mscale] game window not found"); return
    if _logical_wh[0] is None:
        _logical_wh[0] = _client_size(hwnd)
        print(f"  [mscale] logical canvas captured = {_logical_wh[0][0]}x{_logical_wh[0][1]}")
    if _mouse_cave[0] is None:
        block = ctypes.windll.kernel32.VirtualAllocEx(
            pm.process_handle, None, 128,
            MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE,
        )
        if not block:
            print(f"  [mscale] VirtualAllocEx failed: {ctypes.windll.kernel32.GetLastError()}")
            return
        write_bytes(pm, block + 8, _build_mouse_cave(block, base))
        site = base + WNDPROC_OFFSET
        rel  = (block + 8 - (site + 5)) & 0xFFFFFFFF
        write_bytes(pm, site, bytes([0xE9]) + struct.pack('<I', rel) + bytes([0x90]))
        _mouse_cave[0] = block
        print(f"  [mscale] hook installed (cave=0x{block:08X}  site=0x{site:08X})")
    update_mouse_scale(pm)


def update_mouse_scale(pm):
    if _mouse_cave[0] is None or _logical_wh[0] is None:
        return
    hwnd = _game_hwnd()
    if not hwnd:
        return
    cw, ch = _client_size(hwnd)
    lw, lh = _logical_wh[0]
    if cw <= 0 or ch <= 0:
        return
    sx = max(1, round(lw * 65536 / cw))
    sy = max(1, round(lh * 65536 / ch))
    write_int(pm, _mouse_cave[0] + 0, sx)
    write_int(pm, _mouse_cave[0] + 4, sy)
    print(f"  [mscale] client {cw}x{ch} -> canvas {lw}x{lh}  (sx={sx} sy={sy}, "
          f"{'1:1' if sx == 65536 and sy == 65536 else 'scaled'})")


def remove_mouse_scale(pm, base):
    if _mouse_cave[0] is None:
        print("  [mscale] not installed"); return
    write_bytes(pm, base + WNDPROC_OFFSET, WNDPROC_ORIGINAL)
    ctypes.windll.kernel32.VirtualFreeEx(
        pm.process_handle, ctypes.c_void_p(_mouse_cave[0]), 0, MEM_RELEASE,
    )
    _mouse_cave[0] = None
    print("  [mscale] hook removed, WndProc restored")


def _build_centerfix_cave(cave):
    """SetCursorPos replacement. stdcall(x,y): [esp]=ret [esp+4]=x [esp+8]=y.
    If enabled, overwrite the args with the stored true client center, then tail-
    jump to the real SetCursorPos (which does the ret 8 back to the caller)."""
    code = bytearray()
    code += bytes([0x83, 0x3D]) + struct.pack('<I', cave + 12) + bytes([0x00])  # cmp [enable],0
    code += bytes([0x74, 18])                       # je .pass  (skip 18 bytes)
    code += bytes([0xA1]) + struct.pack('<I', cave + 0)        # mov eax,[screenX]
    code += bytes([0x89, 0x44, 0x24, 0x04])         # mov [esp+4],eax
    code += bytes([0xA1]) + struct.pack('<I', cave + 4)        # mov eax,[screenY]
    code += bytes([0x89, 0x44, 0x24, 0x08])         # mov [esp+8],eax
    code += bytes([0xFF, 0x25]) + struct.pack('<I', cave + 8)  # .pass: jmp [real]
    return bytes(code)


def install_centerfix(pm, base):
    if _centerfix_cave[0] is not None:
        print("  [centerfix] already installed"); return
    slot = base + IAT_SETCURSORPOS
    # cache the genuine address on first (clean) install; reuse it forever after,
    # so a previously-corrupted slot can never poison the tail-jump target.
    if _setcursorpos_real[0] is None:
        _setcursorpos_real[0] = read_int(pm, slot)
    real = _setcursorpos_real[0]
    cave = ctypes.windll.kernel32.VirtualAllocEx(
        pm.process_handle, None, 64,
        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE,
    )
    if not cave:
        print(f"  [centerfix] VirtualAllocEx failed: {ctypes.windll.kernel32.GetLastError()}")
        return
    write_int(pm, cave + 8, real)        # real SetCursorPos
    write_int(pm, cave + 12, 1)          # enable
    write_bytes(pm, cave + 16, _build_centerfix_cave(cave))

    # IAT may be a read-only section — force the page writable before repointing
    old = wintypes.DWORD(0)
    ctypes.windll.kernel32.VirtualProtectEx(
        pm.process_handle, ctypes.c_void_p(slot), 4,
        PAGE_EXECUTE_READWRITE, ctypes.byref(old),
    )
    write_int(pm, slot, cave + 16)       # repoint IAT -> cave code
    ctypes.windll.kernel32.VirtualProtectEx(
        pm.process_handle, ctypes.c_void_p(slot), 4, old.value, ctypes.byref(old),
    )

    got = read_int(pm, slot)
    if got != (cave + 16) & 0xFFFFFFFF:
        print(f"  [centerfix] !! IAT write FAILED — slot=0x{got:08X} expected 0x{cave + 16:08X}")
    else:
        print(f"  [centerfix] IAT repointed OK (slot 0x{slot:08X} -> 0x{cave + 16:08X}, real=0x{real:08X})")
    _centerfix_cave[0] = (cave, real)
    update_centerfix(pm)


def update_centerfix(pm):
    if _centerfix_cave[0] is None:
        return
    hwnd = _game_hwnd()
    if not hwnd:
        return
    cx, cy = _client_center_screen(hwnd)
    cave   = _centerfix_cave[0][0]
    write_int(pm, cave + 0, cx)
    write_int(pm, cave + 4, cy)
    print(f"  [centerfix] true client center = screen ({cx},{cy})")


def remove_centerfix(pm, base):
    if _centerfix_cave[0] is None:
        print("  [centerfix] not installed"); return
    cave, real = _centerfix_cave[0]
    slot = base + IAT_SETCURSORPOS
    old  = wintypes.DWORD(0)
    ctypes.windll.kernel32.VirtualProtectEx(
        pm.process_handle, ctypes.c_void_p(slot), 4,
        PAGE_EXECUTE_READWRITE, ctypes.byref(old),
    )
    write_int(pm, slot, real)                       # restore IAT
    ctypes.windll.kernel32.VirtualProtectEx(
        pm.process_handle, ctypes.c_void_p(slot), 4, old.value, ctypes.byref(old),
    )
    got = read_int(pm, slot)
    if got != real & 0xFFFFFFFF:
        print(f"  [centerfix] !! restore FAILED — slot=0x{got:08X} expected 0x{real:08X}")
    # free the cave only after the slot no longer points into it
    if got == real & 0xFFFFFFFF:
        ctypes.windll.kernel32.VirtualFreeEx(
            pm.process_handle, ctypes.c_void_p(cave), 0, MEM_RELEASE,
        )
    _centerfix_cave[0] = None
    print(f"  [centerfix] SetCursorPos restored (slot 0x{slot:08X} -> 0x{got:08X})")


def patch_dash_block(pm, base):
    addr = base + DASH_CALL_OFFSET
    if write_bytes(pm, addr, DASH_BLOCKED):
        print(f"  [patch] Dash blocked at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to block dash at 0x{addr:08X}")
    return False

def patch_dash_unblock(pm, base):
    addr = base + DASH_CALL_OFFSET
    if write_bytes(pm, addr, DASH_UNBLOCKED):
        print(f"  [patch] Dash unblocked at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to unblock dash at 0x{addr:08X}")
    return False

def patch_suck_block(pm, base):
    addr = base + SUCK_CALL_OFFSET
    if write_bytes(pm, addr, SUCK_BLOCKED):
        print(f"  [patch] Suck blocked at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to block suck at 0x{addr:08X}")
    return False

def patch_suck_unblock(pm, base):
    addr = base + SUCK_CALL_OFFSET
    if write_bytes(pm, addr, SUCK_UNBLOCKED):
        print(f"  [patch] Suck unblocked at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to unblock suck at 0x{addr:08X}")
    return False

def patch_focus_pause(pm, base):
    addr = base + FOCUS_PAUSE_OFFSET
    if write_bytes(pm, addr, FOCUS_PAUSE_NOP):
        print(f"  [patch] Focus-pause NOPed at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to NOP focus-pause at 0x{addr:08X}")
    return False

def unpatch_focus_pause(pm, base):
    addr = base + FOCUS_PAUSE_OFFSET
    if write_bytes(pm, addr, FOCUS_PAUSE_ORIGINAL):
        print(f"  [patch] Focus-pause restored at 0x{addr:08X}")
        return True
    print(f"  [patch] Failed to restore focus-pause at 0x{addr:08X}")
    return False

def read_byte(pm, address):
    return pm.read_bytes(address, 1)[0]

def dump_region(pm, base, count=128):
    data = pm.read_bytes(base, count)
    print(f"Dump from 0x{base:08X} ({count} bytes):")
    for i in range(0, len(data), 16):
        row      = data[i:i+16]
        hex_str  = ' '.join(f'{b:02X}' for b in row)
        int_vals = ' | '.join(
            f'{int.from_bytes(row[j:j+4], "little"):10d}'
            for j in range(0, min(16, len(row)), 4)
        )
        print(f"  +0x{i:03X}  {hex_str:<48}  {int_vals}")

def print_status(pm, level_obj, max_stage_addr, fish_received, player_info):
    print(f"--- Level State (base 0x{level_obj:08X}) ---")
    print(f"  lives         : {read_int(pm, level_obj + OFFSET_LIVES)}")
    print(f"  score         : {read_int(pm, level_obj + OFFSET_SCORE)}")
    print(f"  stage         : {read_int(pm, level_obj + OFFSET_STAGE)}")
    print(f"  level_id      : {read_int(pm, level_obj + OFFSET_LEVEL_ID)}")
    print(f"  score_snapshot: {read_int(pm, level_obj + OFFSET_SCORE_SNAPSHOT)}")
    print(f"  lives_snapshot: {read_int(pm, level_obj + OFFSET_LIVES_SNAPSHOT)}")
    print(f"  progress      : {read_int(pm, level_obj + OFFSET_PROGRESS)}")
    if max_stage_addr[0]:
        print(f"--- Max Stage (0x{max_stage_addr[0]:08X}) ---")
        print(f"  mode0MaxStage : {read_int(pm, max_stage_addr[0])}")
        print(f"  fish_received : {fish_received[0]}")
        print(f"  max_allowed   : {max_allowed_stage(fish_received[0])}")
    else:
        print(f"--- Max Stage: not yet captured (complete a level) ---")
    if player_info[0]:
        info = player_info[0]
        print(f"--- Player Fish (0x{info['player_fish']:08X}) ---")
        print(f"  sub-object  : 0x{info['sub_object']:08X}")
        try:
            print(f"  dash flag   : 0x{read_byte(pm, info['dash_addr']):02X}")
            alive = read_int(pm, info['alive_addr'])
            print(f"  alive ptr   : 0x{alive:08X} ({'alive' if alive else 'dead'})")
        except Exception as e:
            print(f"  (read error: {e})")
    else:
        print(f"--- Player Fish: not yet captured (enter a level) ---")

def reset_to_boundary_level(pm, level_obj):
    score_snapshot = read_int(pm, level_obj + OFFSET_SCORE_SNAPSHOT)
    lives_snapshot = read_int(pm, level_obj + OFFSET_LIVES_SNAPSHOT)
    current_level  = read_int(pm, level_obj + OFFSET_LEVEL_ID)
    write_int(pm, level_obj + OFFSET_LEVEL_ID, current_level - 1)
    write_int(pm, level_obj + OFFSET_SCORE,    score_snapshot)
    write_int(pm, level_obj + OFFSET_LIVES,    lives_snapshot)
    write_int(pm, level_obj + OFFSET_PROGRESS, 0)
    print(f"\n  [watcher] Boundary reached — resetting to level {current_level} replay")

def level_watcher(session, pm, base, level_obj, max_stage_addr, fish_received, player_info, stop_event):
    completed_levels = set()
    completed_stages = set()
    last_level_id    = None
    last_stage       = None
    last_max_stage   = None
    last_lives       = None
    stable_level_id  = None
    stable_count     = 0
    STABLE_THRESHOLD = 3

    while not stop_event.is_set():
        try:
            current_level = read_int(pm, level_obj + OFFSET_LEVEL_ID)
            current_stage = read_int(pm, level_obj + OFFSET_STAGE)
            current_lives = read_int(pm, level_obj + OFFSET_LIVES)

            # debounce level_id
            if current_level == stable_level_id:
                stable_count += 1
            else:
                stable_level_id = current_level
                stable_count    = 1

            if stable_count >= STABLE_THRESHOLD:
                current_level = stable_level_id

                # stage checks (only stages 1 and 2)
                if last_stage is not None and current_stage != last_stage:
                    if current_stage in (1, 2):
                        check_key = (current_level, current_stage)
                        if check_key in completed_stages:
                            print(f"\n  [watcher] Level {current_level + 1} Stage {current_stage} COMPLETE (already seen)")
                        else:
                            completed_stages.add(check_key)
                            print(f"\n  [watcher] Level {current_level + 1} Stage {current_stage} COMPLETE (new!)")
                        print("> ", end="", flush=True)

                # level completion check
                if last_level_id is not None and current_level == last_level_id + 1:
                    completed_id = last_level_id
                    if completed_id in completed_levels:
                        print(f"\n  [watcher] Level {completed_id + 1} COMPLETE (already seen)")
                    else:
                        completed_levels.add(completed_id)
                        print(f"\n  [watcher] Level {completed_id + 1} COMPLETE (new!)")
                    print("> ", end="", flush=True)
                    # clear stale pointer and re-register one-shot BP for new level
                    player_info[0] = None
                    register_player_fish_bp(session, pm, base, player_info)

                last_level_id = current_level
                last_stage    = current_stage

            # observe mode0MaxStage (no clamping — game manages it naturally here)
            if max_stage_addr[0] is not None:
                current_max = read_int(pm, max_stage_addr[0])
                if current_max != last_max_stage:
                    last_max_stage = current_max

            # death link detection (lives dropped by exactly 1)
            if last_lives is not None and current_lives == last_lives - 1:
                print(f"\n  [deathlink] Life lost ({last_lives} -> {current_lives})")
                print("> ", end="", flush=True)
            last_lives = current_lives

        except Exception:
            pass
        stop_event.wait(0.1)

def trigger_death(pm, player_fish, sub_object):
    """Call the player death function then trigger respawn loop."""
    DEATH_FUNC = 0x00404E10

    cave = ctypes.windll.kernel32.VirtualAllocEx(
        pm.process_handle,
        None,
        64,
        MEM_COMMIT | MEM_RESERVE,
        PAGE_EXECUTE_READWRITE
    )
    if not cave:
        print(f"VirtualAllocEx failed: {ctypes.windll.kernel32.GetLastError()}")
        return False

    call_site  = cave + 6
    rel_offset = (DEATH_FUNC - (call_site + 5)) & 0xFFFFFFFF

    shellcode = bytearray([
        0x51,                                       # push ecx
        0xB9,                                       # mov ecx, imm32
        *sub_object.to_bytes(4, 'little'),          # sub_object address
        0xE8,                                       # call rel32
        *rel_offset.to_bytes(4, 'little'),          # relative offset to death func
        0x59,                                       # pop ecx
        0xC3,                                       # ret
    ])

    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(cave),
        bytes(shellcode),
        len(shellcode),
        ctypes.byref(written)
    )

    thread = ctypes.windll.kernel32.CreateRemoteThread(
        pm.process_handle,
        None, 0,
        ctypes.c_void_p(cave),
        None, 0, None
    )
    if not thread:
        print(f"CreateRemoteThread failed: {ctypes.windll.kernel32.GetLastError()}")
        ctypes.windll.kernel32.VirtualFreeEx(
            pm.process_handle, ctypes.c_void_p(cave), 0, MEM_RELEASE
        )
        return False

    ctypes.windll.kernel32.WaitForSingleObject(thread, 3000)
    ctypes.windll.kernel32.CloseHandle(thread)
    ctypes.windll.kernel32.VirtualFreeEx(
        pm.process_handle, ctypes.c_void_p(cave), 0, MEM_RELEASE
    )

    # trigger respawn loop by zeroing the respawn flag
    write_int(pm, player_fish + 0x98, 0)

    return True

def generate_shuffle(seed=None):
    """Return 60-element list where index=slot, value=content level. Slots 0 and 59 fixed."""
    rng = _random.Random(seed)
    indices = list(range(1, 59))
    rng.shuffle(indices)
    return [0] + indices + [59]


def _build_shuffle_caves(table_addr):
    """
    Build the three read-side remap caves.

    Cave 1 (30 bytes) — patches 0x49AB70
      Replaces: mov ecx,[eax+28]; test ecx,ecx  (5 bytes)
      Entry: EAX=level_obj  Exit: ECX=shuffle[slot], flags set by test ecx,ecx
      Returns to 0x49AB75 (jl 0x49AB83)

    Cave 2 (30 bytes) — patches 0x40510A
      Replaces: mov eax,[edi]; mov ecx,[eax+28]  (5 bytes)
      Entry: EDI=&level_obj  Exit: EAX=level_obj, ECX=shuffle[slot]
      Returns to 0x40510F (test ecx,ecx; jl ...)

    Cave 3 (31 bytes) — patches 0x403468  (7-byte patch: call+nop+nop)
      Replaces: push esi; push [eax+28]; lea esi,[eax+50]
      Entry: EAX=level_obj  Sets up stack/ESI identically but pushes shuffle[slot]
      Returns to 0x40346F (call 0x483BD0)
    """
    ta = table_addr.to_bytes(4, 'little')

    # Cave 1 — 0x49AB70
    # Byte layout (30 bytes):
    #  0: 52          push edx
    #  1: 8B 50 28    mov edx,[eax+28]
    #  4: 8B CA       mov ecx,edx          (default passthrough)
    #  6: 85 D2       test edx,edx
    #  8: 78 10       js .done  (+16 → byte 26)
    # 10: 83 FA 3B    cmp edx,59
    # 13: 77 0B       ja .done  (+11 → byte 26)
    # 15: 50          push eax
    # 16: B8 xx xx xx xx  mov eax,table_addr
    # 21: 0F B6 0C 10 movzx ecx,byte[eax+edx]
    # 25: 58          pop eax
    # 26: 5A          pop edx              (.done)
    # 27: 85 C9       test ecx,ecx         (flags for jl at 49AB75)
    # 29: C3          ret
    cave1 = bytes([
        0x52,
        0x8B, 0x50, 0x28,
        0x8B, 0xCA,
        0x85, 0xD2,
        0x78, 0x10,
        0x83, 0xFA, 0x3B,
        0x77, 0x0B,
        0x50,
        0xB8, *ta,
        0x0F, 0xB6, 0x0C, 0x10,
        0x58,
        0x5A,
        0x85, 0xC9,
        0xC3,
    ])
    assert len(cave1) == 30, len(cave1)

    # Cave 2 — 0x40510A
    # Byte layout (30 bytes):
    #  0: 8B 07        mov eax,[edi]        (restore original 1st instr)
    #  2: 52           push edx
    #  3: 8B 50 28     mov edx,[eax+28]
    #  6: 8B CA        mov ecx,edx          (default passthrough)
    #  8: 85 D2        test edx,edx
    # 10: 78 10        js .done  (+16 → byte 28)
    # 12: 83 FA 3B     cmp edx,59
    # 15: 77 0B        ja .done  (+11 → byte 28)
    # 17: 50           push eax
    # 18: B8 xx xx xx xx  mov eax,table_addr
    # 23: 0F B6 0C 10  movzx ecx,byte[eax+edx]
    # 27: 58           pop eax
    # 28: 5A           pop edx              (.done)
    # 29: C3           ret
    # after ret: 0x40510F = test ecx,ecx; jl ...  (EAX still = level_obj)
    cave2 = bytes([
        0x8B, 0x07,
        0x52,
        0x8B, 0x50, 0x28,
        0x8B, 0xCA,
        0x85, 0xD2,
        0x78, 0x10,
        0x83, 0xFA, 0x3B,
        0x77, 0x0B,
        0x50,
        0xB8, *ta,
        0x0F, 0xB6, 0x0C, 0x10,
        0x58,
        0x5A,
        0xC3,
    ])
    assert len(cave2) == 30, len(cave2)

    # Cave 3 — 0x403468  (7-byte patch: E8 rel32 90 90)
    # Byte layout (31 bytes):
    #  0: 59           pop ecx              (save ret addr = 0x40346D)
    #  1: 56           push esi             (save old ESI at EBP-8, as frame expects)
    #  2: 8B 50 28     mov edx,[eax+28]     (slot)
    #  5: 85 D2        test edx,edx
    #  7: 78 10        js .pass  (+16 → byte 25)
    #  9: 83 FA 3B     cmp edx,59
    # 12: 77 0B        ja .pass  (+11 → byte 25)
    # 14: 50           push eax
    # 15: B8 xx xx xx xx  mov eax,table_addr
    # 20: 0F B6 14 10  movzx edx,byte[eax+edx]
    # 24: 58           pop eax
    # 25: 52           push edx             (.pass — content_id arg at EBP-12)
    # 26: 8D 70 50     lea esi,[eax+50]     (array ptr for 0x483BD0)
    # 29: 51           push ecx             (re-push ret addr)
    # 30: C3           ret                  (→ 0x40346D nop nop; then call 0x483BD0)
    cave3 = bytes([
        0x59,
        0x56,
        0x8B, 0x50, 0x28,
        0x85, 0xD2,
        0x78, 0x10,
        0x83, 0xFA, 0x3B,
        0x77, 0x0B,
        0x50,
        0xB8, *ta,
        0x0F, 0xB6, 0x14, 0x10,
        0x58,
        0x52,
        0x8D, 0x70, 0x50,
        0x51,
        0xC3,
    ])
    assert len(cave3) == 31, len(cave3)

    return cave1, cave2, cave3


def install_shuffle_hook(pm, base, shuffle):
    """Allocate cave memory, write table+caves, patch all three sites. Returns cave base or None."""
    TOTAL = 60 + 30 + 30 + 31  # 151 bytes

    cave_mem = ctypes.windll.kernel32.VirtualAllocEx(
        pm.process_handle, None, TOTAL,
        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE,
    )
    if not cave_mem:
        print(f"  [shuffle] VirtualAllocEx failed: {ctypes.windll.kernel32.GetLastError()}")
        return None

    table_addr = cave_mem
    cave1_addr = cave_mem + 60
    cave2_addr = cave_mem + 60 + 30
    cave3_addr = cave_mem + 60 + 30 + 30

    write_bytes(pm, table_addr, bytes(shuffle[:60]))

    cave1, cave2, cave3 = _build_shuffle_caves(table_addr)
    write_bytes(pm, cave1_addr, cave1)
    write_bytes(pm, cave2_addr, cave2)
    write_bytes(pm, cave3_addr, cave3)

    # Site 1: 0x49AB70 — 5 bytes → call cave1
    site1 = base + SHUFFLE_SITE1_OFFSET
    rel1  = (cave1_addr - (site1 + 5)) & 0xFFFFFFFF
    write_bytes(pm, site1, bytes([0xE8]) + rel1.to_bytes(4, 'little'))

    # Site 2: 0x40510A — 5 bytes → call cave2
    site2 = base + SHUFFLE_SITE2_OFFSET
    rel2  = (cave2_addr - (site2 + 5)) & 0xFFFFFFFF
    write_bytes(pm, site2, bytes([0xE8]) + rel2.to_bytes(4, 'little'))

    # Site 3: 0x403468 — 7 bytes → call cave3 + nop + nop
    site3 = base + SHUFFLE_SITE3_OFFSET
    rel3  = (cave3_addr - (site3 + 5)) & 0xFFFFFFFF
    write_bytes(pm, site3, bytes([0xE8]) + rel3.to_bytes(4, 'little') + bytes([0x90, 0x90]))

    print(f"  [shuffle] table=0x{table_addr:08X}  cave1=0x{cave1_addr:08X}  cave2=0x{cave2_addr:08X}  cave3=0x{cave3_addr:08X}")
    print(f"  [shuffle] patched site1@0x{site1:08X}  site2@0x{site2:08X}  site3@0x{site3:08X}")
    return cave_mem


def remove_shuffle_hook(pm, base, cave_mem):
    """Restore original bytes at all three sites and free cave memory."""
    write_bytes(pm, base + SHUFFLE_SITE1_OFFSET, SHUFFLE_SITE1_ORIGINAL)
    write_bytes(pm, base + SHUFFLE_SITE2_OFFSET, SHUFFLE_SITE2_ORIGINAL)
    write_bytes(pm, base + SHUFFLE_SITE3_OFFSET, SHUFFLE_SITE3_ORIGINAL)
    ctypes.windll.kernel32.VirtualFreeEx(
        pm.process_handle, ctypes.c_void_p(cave_mem), 0, MEM_RELEASE,
    )
    print("  [shuffle] hooks removed, cave memory freed")


def print_help():
    print("Commands:")
    print("  lives <n>           - set lives")
    print("  progress <n>        - set progress meter")
    print("  maxstage <n>        - set mode0MaxStage directly")
    print("  status              - print all known values")
    print("  dump [count]        - hex dump level state region")
    print("  dump player [count] - hex dump player sub-object region")
    print("  item <name> [delay] - grant an item (optionally after delay seconds)")
    print("    items: life, fish")
    print("  die [delay]         - trigger player death (optionally after delay seconds)")
    print("  resize              - make game window resizable (applied on startup)")
    print("  borderless          - toggle borderless fullscreen (no res change)")
    print("  scalemouse          - toggle mouse-coordinate rescale hook")
    print("  centerfix           - toggle gameplay relative-input center fix")
    print("  nodash              - block dash (applied on startup)")
    print("  dash                - unblock dash (simulate receiving Dash item)")
    print("  nosuck              - block suck (applied on startup)")
    print("  suck                - unblock suck (simulate receiving Suck item)")
    print("  nopause             - NOP focus-loss pause (applied on startup)")
    print("  unpause             - restore focus-loss pause")
    print("  probe <hex_addr>    - execute BP: capture registers when addr is hit (bg)")
    print("  watchlevelid [n]    - write BP on level_id field, log n writes (default 8)")
    print("  stopwatch           - cancel active probe/watchlevelid")
    print("  randomize [seed]    - shuffle level order and install assembly hooks")
    print("  unrandomize         - remove shuffle hooks, restore original bytes")
    print("  showshuffle         - print current slot→content mapping")
    print("  quit                - exit")

def main():
    print(f"Attaching to {PROCESS_NAME}...")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
    except Exception as e:
        print(f"Failed to attach: {e}")
        sys.exit(1)

    base = pymem.process.module_from_name(
        pm.process_handle, PROCESS_NAME
    ).lpBaseOfDll
    print(f"Base: 0x{base:08X}")

    stop_event     = threading.Event()

    patch_dash_block(pm, base)
    patch_suck_block(pm, base)
    make_window_resizable()

    # capture native canvas size while still windowed (basis for mouse rescale)
    _hwnd = _game_hwnd()
    if _hwnd:
        _logical_wh[0] = _client_size(_hwnd)
        print(f"  [mscale] native canvas = {_logical_wh[0][0]}x{_logical_wh[0][1]}")

    session = DebugSession(pm)
    session.start()

    level_obj = capture_level_object(session, pm, base)

    max_stage_addr  = [None]
    fish_received   = [0]
    player_info     = [None]
    current_shuffle = [None]   # list[int] length 60: index=slot, value=content
    cave_mem_addr   = [None]   # base address of allocated cave block
    probe_stop      = [threading.Event()]
    probe_stop[0].set()  # initially "done"

    register_player_fish_bp(session, pm, base, player_info)
    start_max_stage_capture(session, pm, base, max_stage_addr)

    watcher_thread = threading.Thread(
        target=level_watcher,
        args=(session, pm, base, level_obj, max_stage_addr, fish_received, player_info, stop_event),
        daemon=True
    )
    watcher_thread.start()

    print()
    print_help()
    print()

    while True:
        try:
            parts = input("> ").strip().lower().split()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not parts:
            continue

        cmd = parts[0]

        if cmd == "quit":
            break

        elif cmd == "lives":
            if len(parts) < 2:
                print("Usage: lives <n>")
                continue
            try:
                write_int(pm, level_obj + OFFSET_LIVES, int(parts[1]))
                print(f"Lives set to {parts[1]}")
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "progress":
            if len(parts) < 2:
                print("Usage: progress <n>")
                continue
            try:
                write_int(pm, level_obj + OFFSET_PROGRESS, int(parts[1]))
                print(f"Progress set to {parts[1]}")
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "maxstage":
            if len(parts) < 2:
                print("Usage: maxstage <n>")
                continue
            if not max_stage_addr[0]:
                print("Max stage not yet captured — complete a level first.")
                continue
            try:
                write_int(pm, max_stage_addr[0], int(parts[1]))
                print(f"mode0MaxStage set to {parts[1]}")
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "status":
            try:
                print_status(pm, level_obj, max_stage_addr, fish_received, player_info)
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "dump":
            if len(parts) > 1 and parts[1] == "player":
                count = int(parts[2]) if len(parts) > 2 else 256
                if not player_info[0]:
                    print("Player fish not yet captured — enter a level first.")
                else:
                    try:
                        dump_region(pm, player_info[0]["sub_object"], count)
                    except Exception as e:
                        print(f"Failed: {e}")
            else:
                count = int(parts[1]) if len(parts) > 1 else 128
                try:
                    dump_region(pm, level_obj, count)
                except Exception as e:
                    print(f"Failed: {e}")

        elif cmd == "item":
            if len(parts) < 2:
                print("Usage: item <name> [delay]")
                continue
            item_name = parts[1]
            delay     = int(parts[2]) if len(parts) > 2 else 0

            def dispatch_item(item_name, delay):
                if delay:
                    print(f"  [item] {item_name} incoming in {delay}s...")
                    stop_event.wait(delay)
                if item_name == "life":
                    try:
                        current = read_int(pm, level_obj + OFFSET_LIVES)
                        write_int(pm, level_obj + OFFSET_LIVES, current + 1)
                        print(f"\n  [item] Life granted. Lives: {current + 1}")
                    except Exception as e:
                        print(f"\n  [item] Failed: {e}")
                elif item_name == "fish":
                    if not max_stage_addr[0]:
                        print(f"\n  [item] Max stage not yet captured — complete a level first.")
                    else:
                        try:
                            fish_received[0] += 1
                            allowed = max_allowed_stage(fish_received[0])
                            current = read_int(pm, max_stage_addr[0])
                            if current < allowed:
                                write_int(pm, max_stage_addr[0], allowed)
                                print(f"\n  [item] Fish zone unlocked. mode0MaxStage: {allowed} (fish_received={fish_received[0]})")
                            else:
                                print(f"\n  [item] Fish zone unlocked (no change needed). fish_received={fish_received[0]}")
                        except Exception as e:
                            print(f"\n  [item] Failed: {e}")
                else:
                    print(f"\n  [item] Unknown item: {item_name}")
                print("> ", end="", flush=True)

            threading.Thread(
                target=dispatch_item,
                args=(item_name, delay),
                daemon=True
            ).start()

        elif cmd == "die":
            delay = int(parts[1]) if len(parts) > 1 else 0

            def do_die(delay=delay):
                if delay:
                    print(f"  [die] Death in {delay}s...")
                    print("> ", end="", flush=True)
                    stop_event.wait(delay)
                if not player_info[0]:
                    print("\n  [die] No player fish — dropping.")
                    print("> ", end="", flush=True); return
                info = player_info[0]
                try:
                    level_id  = read_int(pm, level_obj + OFFSET_LEVEL_ID)
                    alive_ptr = read_int(pm, info["sub_object"] + OFFSET_ALIVE_PTR)
                    if (level_id + 1) in BONUS_LEVELS:
                        print(f"\n  [die] Bonus level {level_id + 1} — dropping.")
                        print("> ", end="", flush=True); return
                    if alive_ptr == 0:
                        print("\n  [die] alive_ptr=0 (respawning) — dropping.")
                        print("> ", end="", flush=True); return
                    result = trigger_death(pm, info["player_fish"], info["sub_object"])
                    print(f"\n  [die] trigger_death: {result}")
                except Exception as e:
                    print(f"\n  [die] Failed: {e}")
                print("> ", end="", flush=True)

            threading.Thread(target=do_die, daemon=True).start()

        elif cmd == "resize":
            make_window_resizable()

        elif cmd in ("borderless", "fs"):
            toggle_borderless()
            update_mouse_scale(pm)   # refresh scale for the new client size
            update_centerfix(pm)     # refresh recenter target for the new size

        elif cmd in ("scalemouse", "mscale"):
            if _mouse_cave[0] is None:
                install_mouse_scale(pm, base)
            else:
                remove_mouse_scale(pm, base)

        elif cmd == "centerfix":
            if _centerfix_cave[0] is None:
                install_centerfix(pm, base)
            else:
                remove_centerfix(pm, base)

        elif cmd == "nodash":
            patch_dash_block(pm, base)

        elif cmd == "dash":
            patch_dash_unblock(pm, base)

        elif cmd == "nosuck":
            patch_suck_block(pm, base)

        elif cmd == "suck":
            patch_suck_unblock(pm, base)

        elif cmd == "nopause":
            patch_focus_pause(pm, base)

        elif cmd == "unpause":
            unpatch_focus_pause(pm, base)

        elif cmd == "randomize":
            seed = parts[1] if len(parts) > 1 else None
            if seed is not None:
                try:
                    seed = int(seed)
                except ValueError:
                    pass  # keep as string seed
            shuffle = generate_shuffle(seed)
            if cave_mem_addr[0] is not None:
                remove_shuffle_hook(pm, base, cave_mem_addr[0])
                cave_mem_addr[0] = None
                current_shuffle[0] = None
            result = install_shuffle_hook(pm, base, shuffle)
            if result:
                cave_mem_addr[0]   = result
                current_shuffle[0] = shuffle
                print(f"  [shuffle] Seed: {seed!r}  (slots 1-58 shuffled)")
                print(f"  [shuffle] Slot 0 → content 0  (fixed)")
                for slot in range(1, 59):
                    content = shuffle[slot]
                    marker = " *" if slot != content else ""
                    print(f"  [shuffle] Slot {slot:2d} → content {content:2d}{marker}")
                print(f"  [shuffle] Slot 59 → content 59 (fixed)")

        elif cmd == "unrandomize":
            if cave_mem_addr[0] is None:
                print("  [shuffle] No hooks installed.")
            else:
                remove_shuffle_hook(pm, base, cave_mem_addr[0])
                cave_mem_addr[0]   = None
                current_shuffle[0] = None

        elif cmd == "probe":
            if len(parts) < 2:
                print("Usage: probe <hex_addr>")
                continue
            try:
                probe_addr = int(parts[1], 16)
            except ValueError:
                print("Usage: probe <hex_addr>")
                continue
            probe_stop[0].set()
            probe_stop[0] = threading.Event()
            ps   = probe_stop[0]
            lobj = level_obj
            session.unregister(0)   # free DR0 from any prior probe/watch
            print(f"  [probe] Waiting at 0x{probe_addr:08X} — trigger the action in-game now...")
            def _probe_cb(ctx, probe_addr=probe_addr, ps=ps, lobj=lobj):
                if ps.is_set():
                    return False
                print(f"\n  [probe] EIP=0x{ctx.Eip:08X}")
                print(f"    EAX=0x{ctx.Eax:08X}  EBX=0x{ctx.Ebx:08X}  ECX=0x{ctx.Ecx:08X}  EDX=0x{ctx.Edx:08X}")
                print(f"    ESI=0x{ctx.Esi:08X}  EDI=0x{ctx.Edi:08X}  EBP=0x{ctx.Ebp:08X}  ESP=0x{ctx.Esp:08X}")
                try:
                    print(f"    [ESP] =0x{read_int(pm, ctx.Esp):08X}  (ret addr)")
                except Exception:
                    pass
                for rn, rv in [("EAX", ctx.Eax), ("EBX", ctx.Ebx), ("ECX", ctx.Ecx)]:
                    if 0x1000 < rv < 0x7FFFFFFF:
                        try:
                            v = read_int(pm, rv + OFFSET_LEVEL_ID)
                            hint = " ← level_obj!" if rv == lobj else ""
                            print(f"    [{rn}+0x28]=0x{v:08X} ({v}){hint}")
                        except Exception:
                            pass
                print("> ", end="", flush=True)
                ps.set()
                return False   # one-shot
            session.register(0, probe_addr, _probe_cb)

        elif cmd == "watchlevelid":
            if level_obj is None:
                print("  Level object not captured — start game first.")
                continue
            n = int(parts[1]) if len(parts) > 1 else 8
            probe_stop[0].set()
            probe_stop[0] = threading.Event()
            ps = probe_stop[0]
            session.unregister(0)   # free DR0 from any prior probe/watch
            watch_addr = level_obj + OFFSET_LEVEL_ID
            hit_n      = [0]
            print(f"  [watch] Write BP on level_id @ 0x{watch_addr:08X}, capturing {n} writes — trigger in-game...")
            def _watch_cb(ctx, watch_addr=watch_addr, n=n, ps=ps):
                if ps.is_set():
                    return False
                hit_n[0] += 1
                try:
                    val = read_int(pm, watch_addr)
                except Exception:
                    val = -1
                print(f"\n  [watch] write #{hit_n[0]:2d}: EIP=0x{ctx.Eip:08X}  level_id→{val}")
                print(f"    EAX=0x{ctx.Eax:08X}  EBX=0x{ctx.Ebx:08X}  ECX=0x{ctx.Ecx:08X}")
                print("> ", end="", flush=True)
                if hit_n[0] >= n:
                    ps.set()
                    return False
                return True
            session.register(0, watch_addr, _watch_cb, bp_type=1, bp_len=3)

        elif cmd == "stopwatch":
            probe_stop[0].set()
            session.unregister(0)
            print("  [probe/watch] cancelled")

        elif cmd == "showshuffle":
            if current_shuffle[0] is None:
                print("  [shuffle] No shuffle active.")
            else:
                shuffle = current_shuffle[0]
                print(f"  [shuffle] cave @ 0x{cave_mem_addr[0]:08X}")
                for slot in range(60):
                    content = shuffle[slot]
                    marker = " *" if slot != content else ""
                    bonus = " (bonus)" if (content + 1) in BONUS_LEVELS else ""
                    print(f"  slot {slot:2d} → content {content:2d}{bonus}{marker}")

        else:
            print(f"Unknown command: {cmd}")
            print_help()

        

    stop_event.set()
    session.stop()
    watcher_thread.join(timeout=1)

if __name__ == "__main__":
    main()