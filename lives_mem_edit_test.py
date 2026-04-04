import pymem
import pymem.process
import ctypes
import ctypes.wintypes as wintypes
import sys
import threading

PROCESS_NAME = "popcapgame1.exe"

# breakpoint: level state object
LEVEL_STATE_OFFSET = 0x9C064

# confirmed offsets from captured eax value
OFFSET_LIVES          = 0x10
OFFSET_SCORE          = 0x14
OFFSET_STAGE          = 0x24
OFFSET_LEVEL_ID       = 0x28
OFFSET_SCORE_SNAPSHOT = 0x38
OFFSET_LIVES_SNAPSHOT = 0x3C
OFFSET_PROGRESS       = 0x40

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
    THREAD_GET_CONTEXT |
    THREAD_SET_CONTEXT |
    THREAD_QUERY_INFORMATION
)

Wow64GetThreadContext = ctypes.windll.kernel32.Wow64GetThreadContext
Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Wow64GetThreadContext.restype = wintypes.BOOL

Wow64SetThreadContext = ctypes.windll.kernel32.Wow64SetThreadContext
Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
Wow64SetThreadContext.restype = wintypes.BOOL

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
        ("Ecx",               wintypes.DWORD),
        ("Edx",               wintypes.DWORD),
        ("Eax",               wintypes.DWORD),
        ("Ebp",               wintypes.DWORD),
        ("Eip",               wintypes.DWORD),
        ("SegCs",             wintypes.DWORD),
        ("EFlags",            wintypes.DWORD),
        ("Esp",               wintypes.DWORD),
        ("SegSs",             wintypes.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]

def get_process_threads(pid):
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    threads = []
    entry = THREADENTRY32()
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

def set_hardware_breakpoint(thread_handle, address):
    if ctypes.windll.kernel32.SuspendThread(thread_handle) == 0xFFFFFFFF:
        return False
    try:
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_CAPTURE
        if not Wow64GetThreadContext(thread_handle, ctypes.byref(ctx)):
            return False

        ctx.Dr0 = address
        ctx.Dr6 = 0
        ctx.Dr7 |= 0x1
        ctx.Dr7 &= ~(0xF << 16)
        ctx.ContextFlags = CONTEXT_CAPTURE

        if not Wow64SetThreadContext(thread_handle, ctypes.byref(ctx)):
            return False
        return True
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)

def clear_hardware_breakpoint(thread_handle):
    if ctypes.windll.kernel32.SuspendThread(thread_handle) == 0xFFFFFFFF:
        return
    try:
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_CAPTURE
        Wow64GetThreadContext(thread_handle, ctypes.byref(ctx))
        ctx.Dr0 = 0
        ctx.Dr7 &= ~0x1
        ctx.ContextFlags = CONTEXT_CAPTURE
        Wow64SetThreadContext(thread_handle, ctypes.byref(ctx))
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)

def set_bp_on_thread(tid, address):
    th = get_thread_handle(tid)
    if th:
        ok = set_hardware_breakpoint(th, address)
        ctypes.windll.kernel32.CloseHandle(th)
        return ok
    return False

def capture_level_object(pm, base):
    target = base + LEVEL_STATE_OFFSET

    code = pm.read_bytes(target, 8)
    print(f"Instruction bytes at 0x{target:08X}: {code.hex(' ')}")
    print(f"Watching instruction — load a level to capture game object...")

    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        err = ctypes.windll.kernel32.GetLastError()
        print(f"Failed to attach debugger. Error: {err}")
        sys.exit(1)

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    threads = get_process_threads(pm.process_id)
    print(f"Found {len(threads)} threads, setting breakpoints...")
    for tid in threads:
        ok = set_bp_on_thread(tid, target)
        print(f"  Thread {tid}: {'ok' if ok else 'FAILED'}")

    level_object = None
    debug_event  = DEBUG_EVENT()

    while level_object is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue

        event_code = debug_event.dwDebugEventCode
        tid        = debug_event.dwThreadId

        if event_code == 2:  # CREATE_THREAD_DEBUG_EVENT
            pass  # don't touch thread during creation

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
                            if Wow64GetThreadContext(th, ctypes.byref(ctx)):
                                eip = ctx.Eip
                                eax = ctx.Eax
                                print(
                                    f"  Hit: EIP=0x{eip:08X} "
                                    f"EAX=0x{eax:08X} ECX=0x{ctx.Ecx:08X} "
                                    f"EDX=0x{ctx.Edx:08X} ESI=0x{ctx.Esi:08X} "
                                    f"EDI=0x{ctx.Edi:08X}"
                                )
                                if eip == target:
                                    level_object = eax
                                    print(f"  Level object base: 0x{level_object:08X}")
                                    print(f"  lives    @ +0x{OFFSET_LIVES:02X} = 0x{level_object+OFFSET_LIVES:08X}")
                                    print(f"  score    @ +0x{OFFSET_SCORE:02X} = 0x{level_object+OFFSET_SCORE:08X}")
                                    print(f"  stage    @ +0x{OFFSET_STAGE:02X} = 0x{level_object+OFFSET_STAGE:08X}")
                                    print(f"  level_id @ +0x{OFFSET_LEVEL_ID:02X} = 0x{level_object+OFFSET_LEVEL_ID:08X}")
                                    print(f"  progress @ +0x{OFFSET_PROGRESS:02X} = 0x{level_object+OFFSET_PROGRESS:08X}")
                                    clear_hardware_breakpoint(th)
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:  # CREATE_PROCESS_DEBUG_EVENT
            set_bp_on_thread(tid, target)

        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )

        if level_object is not None:
            ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
            break

    return level_object

def read_int(pm, address):
    buf = pm.read_bytes(address, 4)
    return int.from_bytes(buf, byteorder='little')

def write_int(pm, address, value):
    buf = value.to_bytes(4, byteorder='little')
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf,
        4,
        ctypes.byref(written)
    )

def dump_region(pm, base, count=128):
    data = pm.read_bytes(base, count)
    print(f"Dump from 0x{base:08X} ({count} bytes):")
    for i in range(0, len(data), 16):
        row = data[i:i+16]
        hex_str  = ' '.join(f'{b:02X}' for b in row)
        int_vals = ' | '.join(
            f'{int.from_bytes(row[j:j+4], "little"):10d}'
            for j in range(0, min(16, len(row)), 4)
        )
        print(f"  +0x{i:03X}  {hex_str:<48}  {int_vals}")

def print_status(pm, level_obj):
    print(f"--- Level State (base 0x{level_obj:08X}) ---")
    print(f"  lives         : {read_int(pm, level_obj + OFFSET_LIVES)}")
    print(f"  score         : {read_int(pm, level_obj + OFFSET_SCORE)}")
    print(f"  stage         : {read_int(pm, level_obj + OFFSET_STAGE)}")
    print(f"  level_id      : {read_int(pm, level_obj + OFFSET_LEVEL_ID)}")
    print(f"  score_snapshot: {read_int(pm, level_obj + OFFSET_SCORE_SNAPSHOT)}")
    print(f"  lives_snapshot: {read_int(pm, level_obj + OFFSET_LIVES_SNAPSHOT)}")
    print(f"  progress      : {read_int(pm, level_obj + OFFSET_PROGRESS)}")

# def level_watcher(pm, level_obj, stop_event):
#     completed = set()
#     last_level_id = None

#     while not stop_event.is_set():
#         try:
#             current = read_int(pm, level_obj + OFFSET_LEVEL_ID)
#             if last_level_id is not None and current == last_level_id + 1:
#                 completed_id = last_level_id
#                 if completed_id in completed:
#                     print(f"\n  [watcher] Level {completed_id+1} COMPLETE (already seen)") # +1 for 1-based display
#                 else:
#                     completed.add(completed_id)
#                     print(f"\n  [watcher] Level {completed_id+1} COMPLETE (new!)") # +1 for 1-based display
#                 print("> ", end="", flush=True)
#             last_level_id = current
#         except Exception:
#             pass
#         stop_event.wait(0.1)

def level_watcher(pm, level_obj, stop_event):
    completed_levels = set()
    completed_stages = set()
    last_level_id = None
    last_stage = None

    while not stop_event.is_set():
        try:
            current_level = read_int(pm, level_obj + OFFSET_LEVEL_ID)
            current_stage = read_int(pm, level_obj + OFFSET_STAGE)

            # stage checks (only stages 1 and 2, not 0)
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
            last_stage = current_stage
        except Exception:
            pass
        stop_event.wait(0.1)

def print_help():
    print("Commands:")
    print("  lives <n>       - set lives")
    print("  progress <n>    - set progress meter")
    print("  item <name> <n> - grant 1 item (e.g. life) after n seconds")
    print("  status          - print all known values")
    print("  dump [count]    - hex dump level state region")
    print("  quit            - exit")

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

    stop_event = threading.Event()
    watcher_thread = threading.Thread(
        target=level_watcher,
        args=(pm, level_obj, stop_event),
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

        elif cmd == "status":
            try:
                print_status(pm, level_obj)
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "dump":
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
            delay = int(parts[2]) if len(parts) > 2 else 0

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