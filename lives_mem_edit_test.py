import pymem
import pymem.process
import ctypes
import ctypes.wintypes as wintypes
import sys

PROCESS_NAME = "popcapgame1.exe"
LIVES_WRITE_OFFSET = 0x9C064

DBG_CONTINUE = 0x00010002
EXCEPTION_SINGLE_STEP = 0x80000004
CONTEXT_FULL = 0x00010007
TH32CS_SNAPTHREAD = 0x00000004

class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]

class EXCEPTION_RECORD(ctypes.Structure):
    pass

EXCEPTION_RECORD._fields_ = [
    ("ExceptionCode", wintypes.DWORD),
    ("ExceptionFlags", wintypes.DWORD),
    ("ExceptionRecord", ctypes.POINTER(EXCEPTION_RECORD)),
    ("ExceptionAddress", ctypes.c_void_p),
    ("NumberParameters", wintypes.DWORD),
    ("ExceptionInformation", ctypes.c_ulong * 15),
]

class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [
        ("ExceptionRecord", EXCEPTION_RECORD),
        ("dwFirstChance", wintypes.DWORD),
    ]

class DEBUG_EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("Exception", EXCEPTION_DEBUG_INFO),
        ("pad", ctypes.c_byte * 160),
    ]

class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [
        ("dwDebugEventCode", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
        ("u", DEBUG_EVENT_UNION),
    ]

class CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wintypes.DWORD),
        ("Dr0", wintypes.DWORD),
        ("Dr1", wintypes.DWORD),
        ("Dr2", wintypes.DWORD),
        ("Dr3", wintypes.DWORD),
        ("Dr6", wintypes.DWORD),
        ("Dr7", wintypes.DWORD),
        ("FloatSave", ctypes.c_byte * 112),
        ("SegGs", wintypes.DWORD),
        ("SegFs", wintypes.DWORD),
        ("SegEs", wintypes.DWORD),
        ("SegDs", wintypes.DWORD),
        ("Edi", wintypes.DWORD),
        ("Esi", wintypes.DWORD),
        ("Ebx", wintypes.DWORD),
        ("Edx", wintypes.DWORD),
        ("Ecx", wintypes.DWORD),
        ("Eax", wintypes.DWORD),
        ("Ebp", wintypes.DWORD),
        ("Eip", wintypes.DWORD),
        ("SegCs", wintypes.DWORD),
        ("EFlags", wintypes.DWORD),
        ("Esp", wintypes.DWORD),
        ("SegSs", wintypes.DWORD),
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
    THREAD_ALL_ACCESS = 0x1F03FF
    return ctypes.windll.kernel32.OpenThread(THREAD_ALL_ACCESS, False, tid)

def set_hardware_breakpoint(thread_handle, address):
    ctx = CONTEXT()
    ctx.ContextFlags = CONTEXT_FULL
    ctypes.windll.kernel32.GetThreadContext(thread_handle, ctypes.byref(ctx))
    ctx.Dr0 = address
    ctx.Dr7 = (ctx.Dr7 & ~0xF) | 0x1
    ctypes.windll.kernel32.SetThreadContext(thread_handle, ctypes.byref(ctx))

def clear_hardware_breakpoint(thread_handle):
    ctx = CONTEXT()
    ctx.ContextFlags = CONTEXT_FULL
    ctypes.windll.kernel32.GetThreadContext(thread_handle, ctypes.byref(ctx))
    ctx.Dr0 = 0
    ctx.Dr7 = ctx.Dr7 & ~0x1
    ctypes.windll.kernel32.SetThreadContext(thread_handle, ctypes.byref(ctx))

def capture_lives_address(pm, base):
    target = base + LIVES_WRITE_OFFSET
    print(f"Watching instruction at 0x{target:08X} — load a level to capture lives address...")

    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        err = ctypes.windll.kernel32.GetLastError()
        print(f"Failed to attach debugger. Error: {err}")
        sys.exit(1)

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    # set breakpoint on all existing threads immediately
    threads = get_process_threads(pm.process_id)
    print(f"Found {len(threads)} existing threads, setting breakpoints...")
    for tid in threads:
        th = get_thread_handle(tid)
        if th:
            set_hardware_breakpoint(th, target)
            ctypes.windll.kernel32.CloseHandle(th)

    lives_address = None
    debug_event = DEBUG_EVENT()

    while lives_address is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue

        event_code = debug_event.dwDebugEventCode
        tid = debug_event.dwThreadId

        if event_code == 2:  # CREATE_THREAD_DEBUG_EVENT
            th = get_thread_handle(tid)
            if th:
                set_hardware_breakpoint(th, target)
                ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 1:  # EXCEPTION_DEBUG_EVENT
            code = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            print(f"  Exception: code=0x{code:08X} addr=0x{exc_addr or 0:08X}")

            if code == EXCEPTION_SINGLE_STEP and exc_addr == target:
                th = get_thread_handle(tid)
                if th:
                    ctx = CONTEXT()
                    ctx.ContextFlags = CONTEXT_FULL
                    ctypes.windll.kernel32.GetThreadContext(th, ctypes.byref(ctx))
                    eax = ctx.Eax
                    lives_address = eax + 0x10
                    print(f"Captured eax=0x{eax:08X}, lives at 0x{lives_address:08X}")
                    clear_hardware_breakpoint(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:  # CREATE_PROCESS_DEBUG_EVENT
            th = get_thread_handle(tid)
            if th:
                set_hardware_breakpoint(th, target)
                ctypes.windll.kernel32.CloseHandle(th)

        ctypes.windll.kernel32.ContinueDebugEvent(
            debug_event.dwProcessId, tid, DBG_CONTINUE
        )

    ctypes.windll.kernel32.DebugActiveProcessStop(pm.process_id)
    return lives_address

def write_lives(pm, address, value):
    buf = value.to_bytes(4, byteorder='little')
    written = ctypes.c_size_t(0)
    ctypes.windll.kernel32.WriteProcessMemory(
        pm.process_handle,
        ctypes.c_void_p(address),
        buf,
        4,
        ctypes.byref(written)
    )

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

    lives_address = capture_lives_address(pm, base)

    print("\nReady. Type a number to set lives, or 'quit' to exit.\n")
    while True:
        try:
            val = input("> ").strip()
            if val.lower() == "quit":
                break
            lives = int(val)
            write_lives(pm, lives_address, lives)
            print(f"Lives set to {lives}")
        except ValueError:
            print("Enter a number")
        except Exception as e:
            print(f"Write failed: {e}")

if __name__ == "__main__":
    main()