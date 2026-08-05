#pragma once

namespace hooks {

// Direct byte-patch gate for Dash/Suck (not a MinHook detour — there's no "call
// original" case, the call site is just NOP'd out or restored). Defaults to blocked
// (matches vanilla-locked-until-received behavior); Python drives it via
// "DASH_ENABLED <0|1>" / "SUCK_ENABLED <0|1>" over IPC, pushed once on every new
// connection (not just on item receipt) so a reconnect after a game restart re-applies
// whatever was already unlocked.
void InstallAbilityGate();

}  // namespace hooks
