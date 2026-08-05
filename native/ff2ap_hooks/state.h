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

// Level shuffle table (slot -> content level, 0-indexed), populated by hooks/shuffle.cpp
// from the "SHUFFLE ..." IPC command. Not active (identity mapping) until then — matches
// Client.py's own level_shuffle default of range(60) when the option is off.
extern volatile bool g_shuffle_active;
extern volatile unsigned char g_shuffle_table[60];

// slot -> content level, honoring g_shuffle_table when active.
int ContentLevel(int slot);

// Mirrors Client.py's BONUS_LEVELS (1-indexed content ids): 4, 7, 12, 15, 20, 25, 28, 33,
// 36, 41, 45, 48, 51, 54, 57, 60.
bool IsBonusContentLevel(int content_id_0idx);

// Echo suppression for DeathLink: a death triggered by an incoming DEATH_LINK_TRIGGER
// (hooks/deathlink.cpp) causes the same lives-decrease the poll loop
// (hooks/level_guard.cpp) would otherwise report as a *new*, locally-caused DeathLink —
// which would bounce right back out and ping-pong forever. deathlink.cpp sets this to the
// life count it expects to result from the death it's about to cause; level_guard.cpp's
// poll loop checks it against the observed life count before sending DEATH_LINK_SEND, and
// clears it either way (a mismatch means something else caused the life change in the
// meantime, so the suppression no longer applies and shouldn't linger).
constexpr int kNoDeathLinkSuppress = -1;
extern volatile int g_deathlink_suppress_lives;

}  // namespace state
