add_library(ff2ap_hooks SHARED
  dllmain.cpp
  ipc.cpp
  hooks/boundary_gate.cpp
  hooks/level_guard.cpp
)

set_target_properties(ff2ap_hooks PROPERTIES PREFIX "")

target_link_libraries(ff2ap_hooks PRIVATE minhook ws2_32 kernel32)
