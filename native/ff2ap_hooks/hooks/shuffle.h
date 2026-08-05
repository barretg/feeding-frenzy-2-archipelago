#pragma once

namespace hooks {

// Registers the "SHUFFLE <60 comma-separated ints>" IPC handler. On first receipt,
// updates state::g_shuffle_table/g_shuffle_active and patches the three read-side remap
// sites (same three sites and cave machine code Client.py's _build_shuffle_caves/
// _install_shuffle_hook used externally — see shuffle.cpp for the byte-for-byte
// breakdown) to redirect through state::g_shuffle_table, whose address never changes for
// the life of the process, so the caves only need installing once; later SHUFFLE messages
// (a reconnect resending the same table) just refresh the table contents.
void InstallShuffle();

}  // namespace hooks
