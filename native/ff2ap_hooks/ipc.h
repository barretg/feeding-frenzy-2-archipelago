#pragma once

#include <atomic>
#include <cstdint>
#include <string>

// Loopback TCP link to the Python AP client. Newline-delimited plain-text commands —
// see Client.py's native IPC handler for the Python side of this protocol.
//
//   Python -> DLL:  "ALLOWED_MAX <n>\n"       (0-indexed highest level_id allowed)
//   DLL -> Python:  "LEVEL_COMPLETE <n>\n"    (0-indexed level that was just legitimately cleared)
namespace ipc {

constexpr uint16_t kPort = 39270;

// INT32_MAX until the first ALLOWED_MAX arrives, so the hook is a no-op (never blocks
// gameplay) before the AP client has told it anything — fail open, not closed, since an
// unconnected DLL (game launched outside the AP flow) shouldn't brick solo play.
extern std::atomic<int> g_allowed_max;

// Spawns the connect/receive background thread. Safe to call once from DllMain's worker
// thread. Keeps retrying the connection in the background if the client isn't up yet or
// drops.
void Init();

// Thread-safe. Enqueues a line to send on the IPC thread — never blocks the calling
// thread on socket I/O (critical: this may be called from the hooked game thread).
void QueueSend(const std::string& line);

}  // namespace ipc
