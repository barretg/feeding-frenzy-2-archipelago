import pymem
import pymem.process
import ctypes
import ctypes.wintypes as wintypes
import sys
import threading

PROCESS_NAME = "popcapgame1.exe"

# breakpoint offsets
LEVEL_STATE_OFFSET   = 0x9C064
MAX_STAGE_OFFSET     = 0x9AED3
PLAYER_FISH_OFFSET   = 0x38D47

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
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 49, 52, 55, 58, 61]

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

def set_hardware_breakpoint(thread_handle, address, dr_index=0):
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

def set_bp_on_thread(tid, address, dr_index=0):
    th = get_thread_handle(tid)
    if th:
        ok = set_hardware_breakpoint(th, address, dr_index)
        ctypes.windll.kernel32.CloseHandle(th)
        return ok
    return False

def run_debug_capture(pm, target, dr_index, stop_event, on_hit):
    """
    Generic debug capture. Attaches debugger, sets breakpoint at target,
    calls on_hit(ctx) when it fires. Returns first non-None result from on_hit.
    """
    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        err = ctypes.windll.kernel32.GetLastError()
        print(f"  Failed to attach debugger. Error: {err}")
        return None

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    for tid in get_process_threads(pm.process_id):
        set_bp_on_thread(tid, target, dr_index)

    result      = None
    debug_event = DEBUG_EVENT()

    while result is None and (stop_event is None or not stop_event.is_set()):
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
                                result = on_hit(ctx)
                                if result is not None:
                                    clear_hardware_breakpoint(th, dr_index)
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:
            set_bp_on_thread(tid, target, dr_index)

        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )

        if result is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break

    return result

def capture_level_object(pm, base):
    target = base + LEVEL_STATE_OFFSET
    print(f"Watching 0x{target:08X} — press Start Game to capture level object...")

    def on_hit(ctx):
        eax = ctx.Eax
        if eax:
            print(f"  Level object: 0x{eax:08X}")
            print(f"  lives    @ 0x{eax+OFFSET_LIVES:08X}")
            print(f"  score    @ 0x{eax+OFFSET_SCORE:08X}")
            print(f"  stage    @ 0x{eax+OFFSET_STAGE:08X}")
            print(f"  level_id @ 0x{eax+OFFSET_LEVEL_ID:08X}")
            print(f"  progress @ 0x{eax+OFFSET_PROGRESS:08X}")
            return eax
        return None

    return run_debug_capture(pm, target, 0, None, on_hit)

def capture_player_fish(pm, base, stop_event):
    target = base + PLAYER_FISH_OFFSET
    print(f"  [player] Watching 0x{target:08X} — enter a level to capture player fish...")

    def on_hit(ctx):
        ecx = ctx.Ecx
        if not ecx:
            return None
        try:
            sub_object = read_int(pm, ecx + OFFSET_SUB_OBJECT)
            if not sub_object:
                return None
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
            return info
        except Exception:
            return None

    return run_debug_capture(pm, target, 0, stop_event, on_hit)

def capture_max_stage_object(pm, base, stop_event):
    target = base + MAX_STAGE_OFFSET
    print(f"  [maxstage] Watching 0x{target:08X} — complete a level to capture max stage...")

    def on_hit(ctx):
        ecx = ctx.Ecx
        candidate = ecx + OFFSET_MAX_STAGE
        try:
            value = read_int(pm, candidate)
            if 0 <= value <= 100:
                print(f"\n  [maxstage] Captured ecx=0x{ecx:08X}")
                print(f"  [maxstage] mode0MaxStage @ 0x{candidate:08X} = {value}")
                print("> ", end="", flush=True)
                return candidate
            else:
                print(f"\n  [maxstage] Ignoring bad capture: value={value}")
                print("> ", end="", flush=True)
        except Exception:
            pass
        return None

    return run_debug_capture(pm, target, 0, stop_event, on_hit)

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

def level_watcher(pm, level_obj, max_stage_addr, fish_received, player_info, stop_event):
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

                last_level_id = current_level
                last_stage    = current_stage

            # clamp mode0MaxStage only if it changed
            if max_stage_addr[0] is not None:
                current_max = read_int(pm, max_stage_addr[0])
                if current_max != last_max_stage:
                    allowed = max_allowed_stage(fish_received[0])
                    if current_max > allowed:
                        write_int(pm, max_stage_addr[0], allowed)
                        print(f"\n  [watcher] mode0MaxStage clamped {current_max} -> {allowed}")
                        reset_to_boundary_level(pm, level_obj)
                        print("> ", end="", flush=True)
                        last_max_stage = allowed
                    else:
                        last_max_stage = current_max

            # death link detection (lives dropped by exactly 1)
            if last_lives is not None and current_lives == last_lives - 1:
                print(f"\n  [deathlink] Life lost ({last_lives} -> {current_lives})")
                print("> ", end="", flush=True)
            last_lives = current_lives

        except Exception:
            pass
        stop_event.wait(0.1)

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

    level_obj = capture_level_object(pm, base)

    max_stage_addr = [None]
    fish_received  = [0]
    player_info    = [None]
    stop_event     = threading.Event()

    def background_captures():
        # sequential — player fish first, then max stage
        result = capture_player_fish(pm, base, stop_event)
        if result:
            player_info[0] = result

        if not stop_event.is_set():
            result = capture_max_stage_object(pm, base, stop_event)
            if result:
                max_stage_addr[0] = result

    threading.Thread(target=background_captures, daemon=True).start()

    watcher_thread = threading.Thread(
        target=level_watcher,
        args=(pm, level_obj, max_stage_addr, fish_received, player_info, stop_event),
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

        else:
            print(f"Unknown command: {cmd}")
            print_help()

    stop_event.set()
    watcher_thread.join(timeout=1)

if __name__ == "__main__":
    main()