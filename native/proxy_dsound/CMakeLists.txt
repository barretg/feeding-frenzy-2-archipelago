add_library(proxy_dsound SHARED
  dllmain.cpp
  dsound.def
)

set_target_properties(proxy_dsound PROPERTIES
  OUTPUT_NAME "dsound"
  PREFIX ""
)

target_link_libraries(proxy_dsound PRIVATE kernel32)
