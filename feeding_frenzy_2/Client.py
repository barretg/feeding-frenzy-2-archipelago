"""
Feeding Frenzy 2 Archipelago Client
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wintypes
import sys
import threading
from typing import Optional

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

# ── Zone boundaries (0-indexed level where each new zone starts) ──────────────
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 49, 52, 55, 58, 61]

# ── Location IDs (must match world definition) ────────────────────────────────
BONUS_LEVELS = frozenset({4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60})
TOTAL_LEVELS = 60
LOC_BASE     = 0xFF20000 + 0x1000

ITEM_PROGRESSIVE_FISH = 0xFF20000 + 1
ITEM_1UP              = 0xFF20000 + 2

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


def write_int(pm: pymem.Pymem, address: int, value: int) -> None:
    buf     = value.to_bytes(4, byteorder="little")
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf, 4,
        ctypes.byref(written),
    )


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

        # fishy state
        self.player_fish:    Optional[int] = None
        self.sub_object:     Optional[int] = None

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
            logger.info(f"[FF2] Connected. DeathLink: {self._death_link_enabled}")

        elif cmd == "ReceivedItems":
            for item in args["items"]:
                item_id = item.item
                if item_id == ITEM_PROGRESSIVE_FISH:
                    self.fish_received += 1
                    logger.info(f"[FF2] Received Progressive Fish ({self.fish_received} total)")
                    if self.game_ready and self.max_stage_addr:
                        self._apply_fish_item()
                elif item_id == ITEM_1UP:
                    logger.info("[FF2] Received 1-Up")
                    if self.game_ready and self.level_obj:
                        self._apply_1up()

        elif cmd == "Bounced":
            if self._death_link_enabled and "DeathLink" in args.get("tags", []):
                source = args.get("data", {}).get("source", "")
                if source == self.player_names.get(self.slot, ""):
                    return
                self._receive_death_link()


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
            level_id = read_int(self.pm, self.level_obj + OFFSET_LEVEL_ID)
            if (level_id + 1) in BONUS_LEVELS:
                logger.info(f"[FF2] DeathLink — bonus level {level_id + 1}, dropping"); return
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
    STABLE_THRESHOLD = 3

    # wait for game process
    while not ctx.exit_event.is_set():
        try:
            ctx.pm = pymem.Pymem(PROCESS_NAME)
            logger.info(f"[FF2] Attached to {PROCESS_NAME}")
            break
        except Exception:
            logger.info(f"[FF2] Waiting for {PROCESS_NAME}...")
            await asyncio.sleep(3)

    if ctx.exit_event.is_set():
        return

    pm   = ctx.pm
    base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
    logger.info(f"[FF2] Base address: 0x{base:08X}")

    # capture level object in thread (blocks until player loads a level)
    loop = asyncio.get_event_loop()
    ctx.level_obj = await loop.run_in_executor(
        None, capture_level_object, pm, base
    )
    if not ctx.level_obj:
        logger.error("[FF2] Failed to capture level object.")
        return

    ctx.game_ready = True
    logger.info("[FF2] Game ready. Watching for checks...")

    # apply any fish items already received before game was ready
    if ctx.fish_received > 0 and ctx.max_stage_addr:
        ctx._apply_fish_item()

    # start max stage capture in background
    async def _capture_max_stage():
        result = await loop.run_in_executor(
            None, capture_max_stage_object, pm, base, ctx._stop_event
        )
        if result:
            ctx.max_stage_addr = result
            # apply any fish already received
            if ctx.fish_received > 0:
                ctx._apply_fish_item()

    Utils.async_start(_capture_max_stage())

    # capture player fish after level object is captured (guaranteed to be available at this point)
    async def _capture_player_fish():
        target = base + PLAYER_FISH_OFFSET
        # reuse same debug capture pattern as max stage
        result = await loop.run_in_executor(
            None, _do_capture_player_fish, pm, target, ctx._stop_event
        )
        if result:
            ctx.player_fish = result["player_fish"]
            ctx.sub_object  = result["sub_object"]
            logger.info(f"[FF2] Player fish: 0x{ctx.player_fish:08X} sub: 0x{ctx.sub_object:08X}")

    Utils.async_start(_capture_player_fish())

    # main poll loop
    while not ctx.exit_event.is_set():
        try:
            current_level = read_int(pm, ctx.level_obj + OFFSET_LEVEL_ID)
            current_stage = read_int(pm, ctx.level_obj + OFFSET_STAGE)
            current_lives = read_int(pm, ctx.level_obj + OFFSET_LIVES)

            # ── debounce level_id ─────────────────────────────────────────
            if current_level == ctx._stable_level_id:
                ctx._stable_count += 1
            else:
                ctx._stable_level_id = current_level
                ctx._stable_count    = 1

            if ctx._stable_count >= STABLE_THRESHOLD:
                current_level = ctx._stable_level_id

                # ── stage checks (stages 1 and 2 only) ───────────────────
                if ctx._last_stage is not None and current_stage != ctx._last_stage:
                    if current_stage in (1, 2):
                        check_key = (current_level, current_stage)
                        if check_key not in ctx._completed_stages:
                            ctx._completed_stages.add(check_key)
                            level_1   = current_level  # 0-indexed
                            is_bonus  = (level_1 + 1) in BONUS_LEVELS
                            if not is_bonus:
                                slot     = current_stage - 1  # stage 1 → slot 0, stage 2 → slot 1
                                loc_id   = location_id_for(level_1, slot)
                                ctx._send_location(loc_id)
                                logger.info(f"[FF2] Check: Level {level_1 + 1} Stage {current_stage}")

                # ── level completion ──────────────────────────────────────
                if ctx._last_level_id is not None and current_level == ctx._last_level_id + 1:
                    completed_id = ctx._last_level_id
                    if completed_id not in ctx._completed_levels:
                        ctx._completed_levels.add(completed_id)
                        level_1  = completed_id
                        loc_id   = location_id_for(level_1, 2)
                        ctx._send_location(loc_id)
                        logger.info(f"[FF2] Check: Level {level_1 + 1} Complete")

                        if completed_id == 59:
                            ctx._send_goal()
                            logger.info("[FF2] Goal reached — Final Boss defeated!")

                    # clear stale pointers — new level's fish not captured yet
                    ctx.player_fish = None
                    ctx.sub_object  = None
                    logger.info("[FF2] Player pointers cleared — re-capturing for new level")
                    Utils.async_start(_capture_player_fish())

                ctx._last_level_id = current_level
                ctx._last_stage    = current_stage

            # ── DeathLink send ────────────────────────────────────────────
            if ctx._last_lives is not None and current_lives == ctx._last_lives - 1:
                if ctx._death_link_written_lives == current_lives:
                    ctx._death_link_written_lives = None  # this decrement was ours, ignore
                else:
                    ctx._send_death_link()
            ctx._last_lives = current_lives

            # ── clamp mode0MaxStage ───────────────────────────────────────
            if ctx.max_stage_addr is not None:
                current_max = read_int(pm, ctx.max_stage_addr)
                if current_max != ctx._last_max_stage:
                    allowed = max_allowed_stage(ctx.fish_received)
                    if current_max > allowed:
                        write_int(pm, ctx.max_stage_addr, allowed)
                        logger.info(f"[FF2] MaxStage clamped {current_max} -> {allowed}")
                        reset_to_boundary_level(pm, ctx.level_obj)
                        ctx._last_max_stage = allowed
                    else:
                        ctx._last_max_stage = current_max

        except Exception as e:
            logger.debug(f"[FF2] Watcher error: {e}")

        await asyncio.sleep(0.1)

    ctx._stop_event.set()

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
