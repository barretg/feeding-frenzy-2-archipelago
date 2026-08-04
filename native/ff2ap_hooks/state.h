#pragma once

#include <cstdint>

// Shared cache of game-object pointers, filled by the various capture hooks and read by
// anything else that needs them (DeathLink needs player_fish/sub_object, the poll loop
// needs level_obj, etc.). Values persist for the process lifetime once first captured —
// confirmed live this session that level_obj in particular is allocated once and reused
// in place across level transitions, not reallocated.
//
// Plain `volatile intptr_t`, not std::atomic — aligned word-sized reads/writes are
// already atomic on x86, and that's all these need (a cached pointer with no ordering
// protocol). std::atomic<int>/<uintptr_t> here triggers a template-instantiation error
// deep in this MSVC toolchain's <atomic> (reproducible, cause not identified — a plain
// std::atomic<int> in ipc.h works fine, but the same type extern-declared in this header
// and used from hooks/*.cpp does not) — not worth chasing further given volatile covers
// the actual requirement.
namespace state {

extern volatile intptr_t g_level_obj;
extern volatile intptr_t g_player_fish;
extern volatile intptr_t g_sub_object;
extern volatile intptr_t g_boss_hp_addr;

}  // namespace state
