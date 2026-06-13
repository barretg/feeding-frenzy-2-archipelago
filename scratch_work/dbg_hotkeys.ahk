; Send F9 (Run) to x32dbg without stealing focus from the game
; Press Numpad0 while in-game to resume x32dbg
Numpad0::PostMessage, 0x100, 0x78, 0, , ahk_exe x32dbg.exe

; Numpad1 = F8 (Step over)
Numpad1::PostMessage, 0x100, 0x77, 0, , ahk_exe x32dbg.exe

; Numpad2 = F7 (Step into)
Numpad2::PostMessage, 0x100, 0x76, 0, , ahk_exe x32dbg.exe
