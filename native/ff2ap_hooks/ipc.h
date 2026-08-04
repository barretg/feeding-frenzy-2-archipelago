#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>

// Loopback TCP link to the Python AP client. Newline-delimited plain-text commands —
// see Client.py's native IPC handler for the Python side of this protocol. Growing list
// of message types lives with whichever hook module owns them (boundary_gate.cpp for
// ALLOWED_MAX/LEVEL_COMPLETE, etc.) — this file only owns the transport plus the two
// pieces of state/behavior every hook needs (the allowed-max value, and a way to log).
//
//   Python -> DLL:  "ALLOWED_MAX <n>\n"       (0-indexed highest level_id allowed)
//   DLL -> Python:  "LEVEL_COMPLETE <n>\n"    (0-indexed level that was just legitimately cleared)
//   DLL -> Python:  "LOG <text>\n"            (relayed to Client.py's logger, for visibility
//                                               into what a hook is doing without attaching a
//                                               debugger)
namespace ipc {

constexpr uint16_t kPort = 39270;

// INT32_MAX until the first ALLOWED_MAX arrives, so the hook is a no-op (never blocks
// gameplay) before the AP client has told it anything — fail open, not closed, since an
// unconnected DLL (game launched outside the AP flow) shouldn't brick solo play.
extern std::atomic<int> g_allowed_max;

using LineHandler = std::function<void(const std::string& line)>;

// Spawns the connect/receive background thread. Safe to call once from DllMain's worker
// thread, after every hook module has called RegisterHandler. Keeps retrying the
// connection in the background if the client isn't up yet or drops.
void Init();

// Thread-safe. Enqueues a line to send on the IPC thread — never blocks the calling
// thread on socket I/O (critical: this may be called from the hooked game thread).
void QueueSend(const std::string& line);

// Convenience — QueueSend("LOG " + msg).
void Log(const std::string& msg);

// Registers a callback invoked (on the IPC receive thread) for every incoming line that
// isn't ALLOWED_MAX (handled internally). Each hook module registers its own handler and
// ignores lines it doesn't recognize — not a dispatch table keyed by command name, since
// the number of handlers stays small. Call before Init().
void RegisterHandler(LineHandler handler);

}  // namespace ipc
