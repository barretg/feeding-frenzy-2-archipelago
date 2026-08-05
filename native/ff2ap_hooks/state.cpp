#include "state.h"

namespace state {

volatile intptr_t g_level_obj = 0;
volatile intptr_t g_player_fish = 0;
volatile intptr_t g_sub_object = 0;
volatile intptr_t g_boss_hp_addr = 0;

volatile bool g_shuffle_active = false;
volatile unsigned char g_shuffle_table[60] = {0};

volatile int g_deathlink_suppress_lives = kNoDeathLinkSuppress;

int ContentLevel(int slot) {
    if (!g_shuffle_active || slot < 0 || slot >= 60) {
        return slot;
    }
    return g_shuffle_table[slot];
}

bool IsBonusContentLevel(int content_id_0idx) {
    switch (content_id_0idx + 1) {
        case 4: case 7: case 12: case 15: case 20: case 25: case 28: case 33:
        case 36: case 41: case 45: case 48: case 51: case 54: case 57: case 60:
            return true;
        default:
            return false;
    }
}

}  // namespace state
