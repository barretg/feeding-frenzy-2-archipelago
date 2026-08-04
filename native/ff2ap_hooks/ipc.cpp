#include "ipc.h"

#include <winsock2.h>
#include <ws2tcpip.h>

#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

#pragma comment(lib, "ws2_32.lib")

namespace ipc {

std::atomic<int> g_allowed_max{INT32_MAX};

namespace {

std::mutex g_send_mutex;
std::condition_variable g_send_cv;
std::deque<std::string> g_send_queue;

// Only ever appended to during startup (each hook module's Install* call, all on the
// same DllMain worker thread, before Init() starts the receive thread that reads this) —
// no lock needed for that ordering, but see Init()'s comment.
std::vector<LineHandler> g_handlers;

void HandleLine(const std::string& line) {
    if (line.rfind("ALLOWED_MAX ", 0) == 0) {
        try {
            g_allowed_max.store(std::stoi(line.substr(12)), std::memory_order_relaxed);
        } catch (...) {
            // malformed line — ignore, keep the previous value
        }
        return;
    }
    for (const auto& handler : g_handlers) {
        handler(line);
    }
}

// Drains the outgoing queue onto the socket. Runs on the IPC thread only.
void FlushSendQueue(SOCKET sock) {
    std::unique_lock<std::mutex> lock(g_send_mutex);
    while (!g_send_queue.empty()) {
        std::string line = std::move(g_send_queue.front());
        g_send_queue.pop_front();
        lock.unlock();
        line += '\n';
        send(sock, line.c_str(), static_cast<int>(line.size()), 0);
        lock.lock();
    }
}

void SenderThread(SOCKET sock, std::atomic<bool>& stop) {
    while (!stop.load(std::memory_order_relaxed)) {
        std::unique_lock<std::mutex> lock(g_send_mutex);
        g_send_cv.wait_for(lock, std::chrono::milliseconds(200),
                            [&] { return !g_send_queue.empty() || stop.load(); });
        lock.unlock();
        FlushSendQueue(sock);
    }
}

// One connect-serve-disconnect cycle. Returns when the connection drops so the caller
// can retry.
void RunConnection() {
    SOCKET sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock == INVALID_SOCKET) {
        return;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(kPort);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (connect(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        closesocket(sock);
        return;
    }

    std::atomic<bool> stop{false};
    std::thread sender(SenderThread, sock, std::ref(stop));

    std::string buffer;
    char chunk[512];
    for (;;) {
        int n = recv(sock, chunk, sizeof(chunk), 0);
        if (n <= 0) {
            break;
        }
        buffer.append(chunk, n);
        size_t pos;
        while ((pos = buffer.find('\n')) != std::string::npos) {
            HandleLine(buffer.substr(0, pos));
            buffer.erase(0, pos + 1);
        }
    }

    stop.store(true);
    g_send_cv.notify_all();
    sender.join();
    closesocket(sock);
}

void ConnectLoop() {
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        return;
    }
    for (;;) {
        RunConnection();
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

}  // namespace

void Init() {
    std::thread(ConnectLoop).detach();
}

void QueueSend(const std::string& line) {
    {
        std::lock_guard<std::mutex> lock(g_send_mutex);
        g_send_queue.push_back(line);
    }
    g_send_cv.notify_all();
}

void Log(const std::string& msg) {
    QueueSend("LOG " + msg);
}

void RegisterHandler(LineHandler handler) {
    g_handlers.push_back(std::move(handler));
}

}  // namespace ipc
