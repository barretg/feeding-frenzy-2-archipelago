#pragma once

namespace hooks {

// Progressive Frenzy: byte-patches the frenzy counter clamp in AddFrenzy (0x47C550).
// The counter at player+0x290 is clamped to 35; the multiplier tier (player+0x29C) is
// counter/7 + 1, so tier 1 = no frenzy and tier 6 = Mega Frenzy. Python sends
// "FRENZY_LEVEL <0..5>" and the clamp becomes 7 * level. Fails open (level 5, vanilla)
// until the client says otherwise.
void InstallFrenzyGate();

}  // namespace hooks
