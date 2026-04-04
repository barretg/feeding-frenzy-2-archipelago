import pymem
import pymem.process
import ctypes
import ctypes.wintypes as wintypes
import sys

PROCESS_NAME = "popcapgame1.exe"
LIVES_WRITE_OFFSET = 0x9C064

DBG_CONTINUE = 0x00010002
EXCEPTION_SINGLE_STEP = 0x80000004
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
        ("ExtendedRegisters", ctypes.c_byte * 512),  # fix: complete struct
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
        print(f"  SuspendThread failed: {ctypes.windll.kernel32.GetLastError()}")
        return False
    try:
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_CAPTURE
        if not ctypes.windll.kernel32.GetThreadContext(thread_handle, ctypes.byref(ctx)):
            print(f"  GetThreadContext failed: {ctypes.windll.kernel32.GetLastError()}")
            return False

        ctx.Dr0 = address
        ctx.Dr6 = 0
        ctx.Dr7 |= 0x1           # enable local BP0
        ctx.Dr7 &= ~(0xF << 16)  # clear RW0/LEN0: execution, length 1
        ctx.ContextFlags = CONTEXT_CAPTURE

        if not ctypes.windll.kernel32.SetThreadContext(thread_handle, ctypes.byref(ctx)):
            print(f"  SetThreadContext failed: {ctypes.windll.kernel32.GetLastError()}")
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
        ctypes.windll.kernel32.GetThreadContext(thread_handle, ctypes.byref(ctx))
        ctx.Dr0 = 0
        ctx.Dr7 &= ~0x1
        ctx.ContextFlags = CONTEXT_CAPTURE
        ctypes.windll.kernel32.SetThreadContext(thread_handle, ctypes.byref(ctx))
    finally:
        ctypes.windll.kernel32.ResumeThread(thread_handle)

def set_bp_on_thread(tid, address):
    th = get_thread_handle(tid)
    if th:
        ok = set_hardware_breakpoint(th, address)
        ctypes.windll.kernel32.CloseHandle(th)
        return ok
    return False

def derive_lives_address(ctx, target, pm):
    """
    Read the actual instruction bytes at target and derive
    the lives address from the correct register + offset.
    """
    code = pm.read_bytes(target, 8)
    print(f"  Instruction bytes at target: {code.hex(' ')}")

    # common mov [reg+offset], src patterns
    # 89 40 10 = mov [eax+10], eax
    # 89 48 10 = mov [ecx+10], ecx
    # 89 50 10 = mov [edx+10], edx
    # 89 58 10 = mov [ebx+10], ebx
    # 89 70 10 = mov [esi+10], esi
    # 89 78 10 = mov [edi+10], edi
    # first byte 89 = MOV r/m32, r32
    # second byte encodes ModRM: mod=01, reg=src, rm=dst_base
    if code[0] == 0x89:
        modrm = code[1]
        rm = modrm & 0x7
        reg_map = {0: ctx.Eax, 1: ctx.Ecx, 2: ctx.Edx,
                   3: ctx.Ebx, 6: ctx.Esi, 7: ctx.Edi}
        offset = code[2]
        base_reg = reg_map.get(rm)
        if base_reg is not None:
            addr = base_reg + offset
            print(f"  Decoded: [reg({rm})+0x{offset:02X}] = 0x{addr:08X}")
            return addr

    # fallback: print all regs and let user decide
    print("  Could not auto-decode instruction. Registers:")
    print(f"    EAX=0x{ctx.Eax:08X} ECX=0x{ctx.Ecx:08X} EDX=0x{ctx.Edx:08X}")
    print(f"    EBX=0x{ctx.Ebx:08X} ESI=0x{ctx.Esi:08X} EDI=0x{ctx.Edi:08X}")
    return None

def capture_lives_address(pm, base):
    target = base + LIVES_WRITE_OFFSET

    # print instruction bytes before attaching
    code = pm.read_bytes(target, 8)
    print(f"Instruction bytes at 0x{target:08X}: {code.hex(' ')}")
    print(f"Watching instruction — load a level to capture lives address...")

    if not ctypes.windll.kernel32.DebugActiveProcess(pm.process_id):
        err = ctypes.windll.kernel32.GetLastError()
        print(f"Failed to attach debugger. Error: {err}")
        sys.exit(1)

    ctypes.windll.kernel32.DebugSetProcessKillOnExit(False)

    threads = get_process_threads(pm.process_id)
    print(f"Found {len(threads)} existing threads, setting breakpoints...")
    for tid in threads:
        ok = set_bp_on_thread(tid, target)
        print(f"  Thread {tid}: {'ok' if ok else 'FAILED'}")

    lives_address = None
    debug_event = DEBUG_EVENT()

    while lives_address is None:
        if not ctypes.windll.kernel32.WaitForDebugEvent(ctypes.byref(debug_event), 100):
            continue

        event_code = debug_event.dwDebugEventCode
        tid = debug_event.dwThreadId

        if event_code == 2:  # CREATE_THREAD_DEBUG_EVENT
            print(f"  New thread {tid}, setting breakpoint...")
            # suspend ALL existing threads while we set up
            all_threads = get_process_threads(pm.process_id)
            handles = []
            for t in all_threads:
                if t != tid:
                    th = get_thread_handle(t)
                    if th:
                        ctypes.windll.kernel32.SuspendThread(th)
                        handles.append(th)
            
            set_bp_on_thread(tid, target)
            
            # resume all
            for th in handles:
                ctypes.windll.kernel32.ResumeThread(th)
                ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 1:  # EXCEPTION_DEBUG_EVENT
            code = debug_event.u.Exception.ExceptionRecord.ExceptionCode
            exc_addr = debug_event.u.Exception.ExceptionRecord.ExceptionAddress
            print(f"  Exception: code=0x{code:08X} addr=0x{exc_addr or 0:08X}")

            if code == EXCEPTION_SINGLE_STEP:
                th = get_thread_handle(tid)
                if th:
                    if ctypes.windll.kernel32.SuspendThread(th) != 0xFFFFFFFF:
                        try:
                            ctx = CONTEXT()
                            ctx.ContextFlags = CONTEXT_CAPTURE
                            if ctypes.windll.kernel32.GetThreadContext(th, ctypes.byref(ctx)):
                                eip = ctx.Eip
                                print(
                                    f"  Single step: EIP=0x{eip:08X} "
                                    f"EAX=0x{ctx.Eax:08X} ECX=0x{ctx.Ecx:08X} "
                                    f"EDX=0x{ctx.Edx:08X} ESI=0x{ctx.Esi:08X} "
                                    f"EDI=0x{ctx.Edi:08X}"
                                )
                                if eip == target:
                                    lives_address = derive_lives_address(ctx, target, pm)
                                    if lives_address:
                                        print(f"  Lives address: 0x{lives_address:08X}")
                                        clear_hardware_breakpoint(th)
                        finally:
                            ctypes.windll.kernel32.ResumeThread(th)
                    ctypes.windll.kernel32.CloseHandle(th)

        elif event_code == 3:  # CREATE_PROCESS_DEBUG_EVENT
            set_bp_on_thread(tid, target)

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