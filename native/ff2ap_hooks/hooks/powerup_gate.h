#pragma once

namespace hooks {

// Power-up gate: detours the eater's collision handler (fn at base+0x3DEE0, thiscall,
// one arg = the actor touched) and returns before any eat check when the victim is a
// locked power-up class, so the fish swims through it untouched. Classes are identified
// by actor vtable; BonusStar and MermaidStar share one bit. Python drives it via "POWERUPS_UNLOCKED <bitmask>" (bit order in
// powerup_gate.cpp, mirrored by Client.py's POWERUP_ITEMS); fails open (all unlocked)
// until the client says otherwise.
bool InstallPowerupGate();

}  // namespace hooks
