"""
Standalone stand-in for FF2Context's native IPC server (see feeding_frenzy_2/Client.py's
_start_native_server) — for manually testing ff2ap_hooks.dll against a running game
without needing a full Archipelago server/generated seed.

Listens on 127.0.0.1:39270, sends ALLOWED_MAX on connect (defaults wide open — nothing
gets clamped/blocked), and prints every line the DLL sends (LOG, LEVEL_COMPLETE,
STAGE_COMPLETE, GOAL, DEATH_LINK_SEND). Type a command and press Enter to send it to the
DLL — same protocol Client.py speaks, see native/ff2ap_hooks/ipc.h and each hooks/*.cpp
file for the exact command set. A blank input just prints the current connection state.

Useful commands:
    ALLOWED_MAX <n>        0-indexed highest level_id allowed (default is wide open)
    DASH_ENABLED <0|1>
    SUCK_ENABLED <0|1>
    SHUFFLE <60 comma-separated ints>   slot -> content level
    DEATH_LINK_TRIGGER
    TOGGLE_FULLSCREEN
    APPLY_1UP
"""
import asyncio
import sys

HOST, PORT = "127.0.0.1", 39270
DEFAULT_ALLOWED_MAX = 999

_writers = []


async def handle(reader, writer):
    peer = writer.get_extra_info("peername")
    print(f"[server] ff2ap_hooks.dll connected from {peer}")
    _writers.append(writer)
    writer.write(f"ALLOWED_MAX {DEFAULT_ALLOWED_MAX}\n".encode())
    await writer.drain()
    print(f"[server] sent ALLOWED_MAX {DEFAULT_ALLOWED_MAX}")

    buf = b""
    try:
        while True:
            chunk = await reader.read(512)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                print(f"[server] RECV: {line.decode(errors='replace')}")
    except Exception as e:
        print(f"[server] error: {e}")
    finally:
        if writer in _writers:
            _writers.remove(writer)
    print("[server] disconnected")


async def stdin_loop():
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            print(f"[server] {len(_writers)} DLL connection(s) active")
            continue
        if not _writers:
            print("[server] no DLL connected yet — command not sent")
            continue
        print(f"[server] SEND: {line}")
        data = (line + "\n").encode()
        for w in list(_writers):
            w.write(data)
            await w.drain()


async def main():
    srv = await asyncio.start_server(handle, HOST, PORT)
    print(f"[server] listening on {HOST}:{PORT} (ALLOWED_MAX={DEFAULT_ALLOWED_MAX})")
    print("[server] type a command + Enter to send it to the DLL, blank line for status, Ctrl+C to quit")
    async with srv:
        await asyncio.gather(srv.serve_forever(), stdin_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
