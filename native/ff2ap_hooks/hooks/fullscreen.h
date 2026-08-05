#pragma once

namespace hooks {

// Registers the "TOGGLE_FULLSCREEN" IPC handler (driven by Client.py's /fullscreen
// command). Direct port of Client.py's _toggle_fullscreen/_apply_borderless/
// _install_mouse_scale/_install_centerfix — same WndProc mouse-rescale cave and
// SetCursorPos IAT redirect, using VirtualAlloc/direct pointer writes instead of the
// external VirtualAllocEx/WriteProcessMemory versions. The window-style manipulation
// (SetWindowLongA/SetWindowPos/ClipCursor, FindWindowA("Gatsu", ...)) is plain User32
// and works identically in-process.
void InstallFullscreen();

}  // namespace hooks
