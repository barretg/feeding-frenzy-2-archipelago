add_library(ff2ap_hooks SHARED
  dllmain.cpp
  ipc.cpp
  state.cpp
  hooks/boundary_gate.cpp
  hooks/level_guard.cpp
  hooks/player_fish.cpp
  hooks/ability_gate.cpp
  hooks/deathlink.cpp
  hooks/boss_hp.cpp
  hooks/shuffle.cpp
  hooks/fullscreen.cpp
)

set_target_properties(ff2ap_hooks PROPERTIES PREFIX "")

target_link_libraries(ff2ap_hooks PRIVATE minhook ws2_32 kernel32 user32)
target_link_options(ff2ap_hooks PRIVATE /MAP)
