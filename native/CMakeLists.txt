cmake_minimum_required(VERSION 3.15)

# popcapgame1.exe is a 32-bit process. Build it either way:
#   Visual Studio:  cmake -S native -B native/build -A Win32
#   Linux/clang-cl: cmake -S native -B native/build-linux -G Ninja \
#                     -DCMAKE_TOOLCHAIN_FILE=cmake/clang-cl-win32.cmake
project(ff2ap_native LANGUAGES C CXX)

# Checked after project() so CMAKE_SIZEOF_VOID_P is actually populated. The old check ran
# before it, so under any non-Visual-Studio generator it compared against an empty string
# and warned on correctly configured builds.
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
  message(WARNING "FF2 is a 32-bit process; this build is ${CMAKE_SIZEOF_VOID_P}-byte-pointer "
                  "and the DLLs won't load into it. Use -A Win32, or the clang-cl toolchain file.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
add_subdirectory(thirdparty/minhook)

add_subdirectory(proxy_dsound)
add_subdirectory(ff2ap_hooks)
