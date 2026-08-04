cmake_minimum_required(VERSION 3.15)

# popcapgame1.exe is a 32-bit process — configure with:
#   cmake -S native -B native/build -A Win32
if(NOT CMAKE_GENERATOR_PLATFORM STREQUAL "Win32" AND NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
  message(WARNING "FF2 is a 32-bit process; configure with -A Win32 or the DLLs won't load into it.")
endif()

project(ff2ap_native LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
add_subdirectory(thirdparty/minhook)

add_subdirectory(proxy_dsound)
add_subdirectory(ff2ap_hooks)
