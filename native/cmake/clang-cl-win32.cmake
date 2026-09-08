# Cross-compile the 32-bit Windows DLLs from Linux using clang-cl + lld-link against
# the MSVC CRT and Windows SDK that xwin unpacks.
#
# This targets the MSVC ABI (i686-pc-windows-msvc), not mingw, because the sources use
# MSVC constructs throughout: __declspec(naked), __asm{} blocks and __thiscall. clang
# supports all of them; GCC supports none of them on x86.
#
# Set up the sysroot once with:
#   xwin --accept-license --arch x86,x86_64 splat --output ~/.xwin
#
# Then configure and build with:
#   cmake -S native -B native/build-linux -G Ninja \
#         -DCMAKE_TOOLCHAIN_FILE=cmake/clang-cl-win32.cmake -DCMAKE_BUILD_TYPE=Release
#   cmake --build native/build-linux
#
# The Visual Studio path (cmake -S native -B native/build -A Win32) is untouched and
# still works; this is an additional way to build, not a replacement.

set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86)

set(XWIN_ROOT "$ENV{HOME}/.xwin" CACHE PATH "Root of the xwin splat output")
if(NOT EXISTS "${XWIN_ROOT}/crt/lib/x86")
  message(FATAL_ERROR
    "No 32-bit MSVC libraries under ${XWIN_ROOT}.\n"
    "xwin defaults to --arch x86_64, so re-run it including x86:\n"
    "  xwin --accept-license --arch x86,x86_64 splat --output ${XWIN_ROOT}")
endif()

find_program(CLANG_CL_EXE NAMES clang-cl REQUIRED)
find_program(LLD_LINK_EXE NAMES lld-link REQUIRED)

set(CMAKE_C_COMPILER   "${CLANG_CL_EXE}")
set(CMAKE_CXX_COMPILER "${CLANG_CL_EXE}")
set(CMAKE_LINKER       "${LLD_LINK_EXE}")

# llvm-lib and llvm-rc live in the `llvm` package, which is not needed just to build
# these DLLs: lld-link doubles as the librarian in /lib mode, and there are no .rc files
# to compile. Use the real tools when they happen to be installed, otherwise fall back so
# clang + lld alone are enough.
find_program(LLVM_LIB_EXE NAMES llvm-lib)
find_program(LLVM_RC_EXE  NAMES llvm-rc)
if(LLVM_LIB_EXE)
  set(CMAKE_AR "${LLVM_LIB_EXE}")
else()
  # lld-link only acts as a librarian when /lib is its *first* argument, and CMake's
  # static-library rule always emits /nologo ahead of anything this file can set. The
  # shim exists purely to put /lib in front.
  set(CMAKE_AR "${CMAKE_CURRENT_LIST_DIR}/lld-link-lib")
endif()
if(LLVM_RC_EXE)
  set(CMAKE_RC_COMPILER "${LLVM_RC_EXE}")
endif()

# clang-cl only infers the MSVC-style driver from its name, so on Linux the target has
# to be stated explicitly or it builds for the host.
set(_XWIN_TARGET "--target=i686-pc-windows-msvc -m32")

# /imsvc rather than -I so SDK headers are treated as system headers and their warnings
# stay out of the build output.
set(_XWIN_INCLUDES
  "/imsvc${XWIN_ROOT}/crt/include \
/imsvc${XWIN_ROOT}/sdk/include/ucrt \
/imsvc${XWIN_ROOT}/sdk/include/um \
/imsvc${XWIN_ROOT}/sdk/include/shared")

# -Wno-msvc-not-found silences the driver's search for a local VS install, which will
# never be present here; the sysroot is supplied by hand above and below.
set(_XWIN_FLAGS "${_XWIN_TARGET} ${_XWIN_INCLUDES} -Wno-msvc-not-found /EHsc /DWIN32 /D_WINDOWS")

set(CMAKE_C_FLAGS_INIT   "${_XWIN_FLAGS}")
set(CMAKE_CXX_FLAGS_INIT "${_XWIN_FLAGS}")

set(_XWIN_LIBPATHS
  "/libpath:${XWIN_ROOT}/crt/lib/x86 \
/libpath:${XWIN_ROOT}/sdk/lib/ucrt/x86 \
/libpath:${XWIN_ROOT}/sdk/lib/um/x86")

# /machine:x86 has to be explicit: lld-link otherwise infers the machine type from the
# first object it sees, which is fragile when a .def file is also in play.
#
# /MANIFEST:NO because CMake otherwise wraps every link in `cmake -E vs_link_exe`, which
# shells out to `rc` to compile a manifest resource. There is no rc.exe here, and none of
# these DLLs need a manifest. This also keeps llvm-rc (and the whole `llvm` package) from
# being a build requirement.
set(_XWIN_LINK "/machine:x86 /MANIFEST:NO ${_XWIN_LIBPATHS}")
set(CMAKE_EXE_LINKER_FLAGS_INIT    "${_XWIN_LINK}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${_XWIN_LINK}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${_XWIN_LINK}")

# Look for programs on the host, but headers and libraries only in the sysroot.
set(CMAKE_FIND_ROOT_PATH "${XWIN_ROOT}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# Link the CRT statically. These DLLs get injected into a game process that may be
# running inside a bare Proton prefix, where no Visual C++ redistributable is installed,
# so depending on vcruntime140.dll/ucrtbase.dll would be a launch failure waiting to
# happen. Static linking makes each DLL self-contained.
#
# Always the release CRT, even in Debug builds. xwin only fetches the debug CRT
# (libcmtd.lib and friends) when run with --include-debug-runtime, and it is not worth
# the extra download for a mod DLL that ships optimized. Debug info still works; only the
# CRT variant is pinned.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded")

# CMake's compiler-ABI try-compiles run as Debug unless told otherwise, which would drag
# in libcmtd.lib during configure and fail before the project ever builds.
set(CMAKE_TRY_COMPILE_CONFIGURATION Release)
