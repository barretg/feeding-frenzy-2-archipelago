"""
Feeding Frenzy 2 Archipelago Client
"""
from __future__ import annotations

import asyncio
import importlib.resources
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import Utils
from CommonClient import CommonContext, server_loop, gui_enabled, ClientCommandProcessor, logger, get_base_parser
from settings import get_settings

GAME_NAME = "Feeding Frenzy 2"

# ── Zone boundaries (0-indexed level where each new zone starts) ──────────────
ZONE_BOUNDARIES = [0, 8, 16, 21, 29, 37, 45, 48, 51, 54, 57]

# ── Location IDs (must match world definition) ────────────────────────────────
BONUS_LEVELS = frozenset({4, 7, 12, 15, 20, 25, 28, 33, 36, 41, 45, 48, 51, 54, 57, 60})
LOC_BASE     = 0xFF20000 + 0x1000

ITEM_PROGRESSIVE_FISH = 0xFF20000 + 1
ITEM_1UP              = 0xFF20000 + 2
ITEM_DASH              = 0xFF20000 + 3
ITEM_SUCK              = 0xFF20000 + 4

# ── Native hook IPC (ff2ap_hooks.dll, injected via the dsound.dll proxy) ──────
# Loopback TCP, newline-delimited text — must match native/ff2ap_hooks/ipc.h.
# All game-memory access lives in the DLL now; this client is pure network/asyncio
# code, cross-platform (works the same whether the DLL is native Windows or running
# under Proton on SteamOS — the TCP link bridges the Wine boundary transparently).
NATIVE_IPC_HOST  = "127.0.0.1"
NATIVE_IPC_PORT  = 39270
NATIVE_DLL_NAMES = ("dsound.dll", "ff2ap_hooks.dll")
GAME_EXE_NAMES   = ("FeedingFrenzy2.exe", "FeedingFrenzyTwo.exe")  # CD vs Steam release; both spawn popcapgame1.exe itself
STEAM_APPID      = "3390"  # "Feeding Frenzy 2: Shipwreck Showdown Deluxe" — Steam release must be launched
                            # through Steam itself (steam://run), not the exe directly: the depot doesn't ship
                            # steam.dll on disk, Steam's own launcher injects it, and running the exe standalone
                            # fails with "Unable to launch steam.dll".


# ── Game logic helpers ────────────────────────────────────────────────────────

def max_allowed_stage(fish_received: int) -> int:
    next_zone_idx = fish_received + 1
    if next_zone_idx >= len(ZONE_BOUNDARIES):
        return 999
    return ZONE_BOUNDARIES[next_zone_idx] - 1


def location_id_for(level_id: int, slot: int) -> int:
    return LOC_BASE + (level_id * 3) + slot


# ── Native hook install / launch ──────────────────────────────────────────────

def _read_native_asset(name: str) -> Optional[bytes]:
    # A .apworld is a zip that AP loads via zipimport without extracting it, so
    # Path(__file__)/"native"/name isn't a real filesystem path when installed that way
    # (it silently reports not-exists). importlib.resources reads through the zip either way.
    try:
        return importlib.resources.files(__package__).joinpath("native").joinpath(name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def _ensure_native_hooks_installed(game_dir: Path) -> None:
    """Write the bundled proxy/payload DLLs (and a local copy of the real system
    dsound.dll for the proxy to forward to) into the game's install directory,
    if missing or different from what's bundled in this apworld."""
    for name in NATIVE_DLL_NAMES:
        data = _read_native_asset(name)
        if data is None:
            logger.warning(f"[FF2] Native hook file missing from package: native/{name}")
            continue
        dst = game_dir / name
        if not dst.exists() or dst.read_bytes() != data:
            dst.write_bytes(data)
            logger.info(f"[FF2] Installed {name} -> {dst}")

    real_dst = game_dir / "dsound_real.dll"
    if not real_dst.exists():
        sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "SysWOW64" / "dsound.dll"
        if sys32.exists():
            shutil.copy2(sys32, real_dst)
            logger.info(f"[FF2] Installed dsound_real.dll -> {real_dst}")
        else:
            logger.warning("[FF2] Could not find system dsound.dll to copy as dsound_real.dll")


def _find_game_exe(p: Path) -> Optional[Path]:
    for name in GAME_EXE_NAMES:
        exe = p / name
        if exe.exists():
            return exe
    return None


def _valid_game_directory(path) -> Optional[Path]:
    if not path:
        return None
    p = Path(str(path))
    return p if _find_game_exe(p) else None


def _get_game_directory() -> Optional[Path]:
    configured = get_settings()["feeding_frenzy_2_options"]["game_directory"]
    return _valid_game_directory(configured)


def _pick_game_directory() -> Optional[Path]:
    # Browse from a fresh instance of the settings Path type rather than whatever's
    # currently stored — settings.py's Group.__getattribute__ only re-wraps a value
    # into its typed Path subclass (the thing .browse() lives on) if it's still a Path
    # instance; a prior save could have degraded it to a plain str (see below), which
    # would make ff2_settings["game_directory"].browse() blow up here. Browsing from a
    # fresh instance sidesteps that regardless of what's currently on disk.
    from . import FF2Settings
    chosen = FF2Settings.GameDirectory("").browse()
    if not chosen:
        return None
    # Keep the value's own Path subclass (what .browse() returns) rather than
    # coercing to a plain str — storing a bare str here is what breaks .browse() on
    # the next prompt in the first place.
    get_settings()["feeding_frenzy_2_options"]["game_directory"] = chosen
    get_settings().save()
    return _valid_game_directory(chosen)


def launch_game() -> None:
    game_dir = _get_game_directory()
    if game_dir is None:
        game_dir = _pick_game_directory()
        if game_dir is None:
            logger.warning("[FF2] No valid Feeding Frenzy 2 install directory selected "
                            f"(must contain one of {GAME_EXE_NAMES}).")
            return

    _ensure_native_hooks_installed(game_dir)

    exe = _find_game_exe(game_dir)
    if exe.name == "FeedingFrenzyTwo.exe":
        # Steam release: must go through Steam's own launcher so it can provide steam.dll;
        # running the exe directly fails with "Unable to launch steam.dll".
        os.startfile(f"steam://run/{STEAM_APPID}")
    else:
        subprocess.Popen([str(exe)], cwd=str(game_dir))
    logger.info(f"[FF2] Launched {exe}")


# ── Command processor ─────────────────────────────────────────────────────────

class FF2CommandProcessor(ClientCommandProcessor):
    def _cmd_fullscreen(self):
        """Toggle borderless windowed fullscreen with scaled mouse input."""
        ctx: FF2Context = self.ctx
        ctx._send_native("TOGGLE_FULLSCREEN")

    def _cmd_directory(self, path: str = "") -> None:
        """Manually set the Feeding Frenzy 2 install directory. Usage: /directory "<path>" """
        if not path:
            logger.warning('[FF2] Usage: /directory "<path to install folder>"')
            return
        game_dir = _valid_game_directory(path)
        if game_dir is None:
            logger.warning(f'[FF2] "{path}" does not contain one of {GAME_EXE_NAMES} '
                            f"-- not a valid Feeding Frenzy 2 install directory.")
            return
        from . import FF2Settings
        get_settings()["feeding_frenzy_2_options"]["game_directory"] = FF2Settings.GameDirectory(str(game_dir))
        get_settings().save()
        logger.info(f"[FF2] Game directory set to {game_dir}")

    def _cmd_uninstall(self):
        """Remove the injected native hook files from the game's install directory,
        restoring normal (unmodified) launches outside of Archipelago."""
        game_dir = _get_game_directory()
        if game_dir is None:
            logger.warning("[FF2] No valid Feeding Frenzy 2 install directory configured; nothing to uninstall.")
            return
        removed, failed = [], []
        for name in (*NATIVE_DLL_NAMES, "dsound_real.dll"):
            f = game_dir / name
            if not f.exists():
                continue
            try:
                f.unlink()
                removed.append(name)
            except OSError:
                failed.append(name)
        if failed:
            logger.warning(f"[FF2] Could not remove {', '.join(failed)} -- close the game first, then retry.")
        if removed:
            logger.info(f"[FF2] Removed: {', '.join(removed)}. The game will launch unmodified from now on.")
        elif not failed:
            logger.info("[FF2] Nothing to remove -- native hooks were not installed in this directory.")

    def _cmd_status(self):
        """Show current game state (as of the last update received from the game)."""
        ctx: FF2Context = self.ctx
        logger.info(f"Native hooks connected: {bool(ctx._native_writers)}")
        logger.info(f"Last known level (1-indexed): {ctx.last_known_level + 1 if ctx.last_known_level is not None else '?'}")
        logger.info(f"Last known stage: {ctx.last_known_stage}")
        logger.info(f"Fish received: {ctx.fish_received}")
        logger.info(f"Max allowed stage: {max_allowed_stage(ctx.fish_received)}")


# ── Context ───────────────────────────────────────────────────────────────────

class FF2Context(CommonContext):
    game                   = GAME_NAME
    command_processor      = FF2CommandProcessor
    items_handling         = 0b111  # full remote items

    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)

        # item/progression state
        self.fish_received:   int  = 0
        self.dash_received:   bool = False
        self.suck_received:   bool = False

        # native hook IPC (ff2ap_hooks.dll) — all game-memory access happens there now
        self._native_server:  Optional[asyncio.AbstractServer] = None
        self._native_writers: List[asyncio.StreamWriter]       = []

        # dedup / bookkeeping for checks reported over IPC
        self._completed_levels:   set  = set()
        self._completed_stages:   set  = set()
        self._death_link_enabled: bool = False

        # last-known state for /status — updated as native messages arrive, not live-polled
        self.last_known_level: Optional[int] = None
        self.last_known_stage: Optional[int] = None

        # shuffle state (persists across game restarts — same seed = same shuffle)
        self.level_shuffle: Optional[List[int]] = None

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            slot_data = args.get("slot_data", {})
            self._death_link_enabled = bool(slot_data.get("death_link", False))
            if self._death_link_enabled:
                Utils.async_start(self.update_death_link(True))
            shuffle = slot_data.get("level_shuffle")
            if shuffle:
                self.level_shuffle = shuffle
                self._push_shuffle()
            logger.info(f"[FF2] Connected. DeathLink: {self._death_link_enabled}")

        elif cmd == "ReceivedItems":
            is_full_resend = args.get("index", 0) == 0
            if is_full_resend:
                self.fish_received = 0  # full resend — recount from scratch
                self.dash_received = False
                self.suck_received = False
            for item in args["items"]:
                item_id = item.item
                if item_id == ITEM_PROGRESSIVE_FISH:
                    self.fish_received += 1
                    logger.info(f"[FF2] Received Progressive Fish ({self.fish_received} total)")
                elif item_id == ITEM_1UP:
                    logger.info("[FF2] Received 1-Up")
                    if not is_full_resend:
                        self._send_native("APPLY_1UP")
                elif item_id == ITEM_DASH:
                    self.dash_received = True
                    logger.info("[FF2] Received Dash")
                elif item_id == ITEM_SUCK:
                    self.suck_received = True
                    logger.info("[FF2] Received Suck")
            self._push_allowed_max()
            self._push_ability_state()

        elif cmd == "Bounced":
            if self._death_link_enabled and "DeathLink" in args.get("tags", []):
                source = args.get("data", {}).get("source", "")
                if source == self.player_names.get(self.slot, ""):
                    return
                self._send_native("DEATH_LINK_TRIGGER")

    def _content_level(self, slot: int) -> int:
        """Map a map-slot level ID to the content level ID for that slot."""
        if self.level_shuffle and 0 <= slot < len(self.level_shuffle):
            return self.level_shuffle[slot]
        return slot

    def _send_location(self, location_id: int):
        Utils.async_start(self.send_msgs([{
            "cmd": "LocationChecks",
            "locations": [location_id],
        }]))

    def _send_goal(self):
        Utils.async_start(self.send_msgs([{
            "cmd": "StatusUpdate",
            "status": 30,  # ClientStatus.CLIENT_GOAL
        }]))

    def _send_death_link(self):
        if self._death_link_enabled:
            logger.info("[FF2] DeathLink sent")
            Utils.async_start(self.send_msgs([{
                "cmd": "Bounce",
                "tags": ["DeathLink"],
                "data": {
                    "time":   asyncio.get_event_loop().time(),
                    "cause":  "Lost a life",
                    "source": self.player_names.get(self.slot, "FF2 Player"),
                },
            }]))

    # ── Native hook IPC ────────────────────────────────────────────────────────
    # ff2ap_hooks.dll connects here once injected. Every piece of gameplay-affecting
    # logic (boundary gate, dash/suck gating, level shuffle, DeathLink, boss/goal
    # detection, stage/level-completion tracking, fullscreen) runs in-process on the
    # DLL side; this link exists to keep it in sync with AP item/connection state and
    # to receive the events it detects.

    async def _start_native_server(self) -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            logger.info("[FF2] Native hooks connected")
            self._native_writers.append(writer)
            try:
                writer.write(f"ALLOWED_MAX {max_allowed_stage(self.fish_received)}\n".encode())
                writer.write(f"DASH_ENABLED {int(self.dash_received)}\n".encode())
                writer.write(f"SUCK_ENABLED {int(self.suck_received)}\n".encode())
                if self.level_shuffle:
                    writer.write((f"SHUFFLE {','.join(str(v) for v in self.level_shuffle[:60])}\n").encode())
                await writer.drain()

                buf = b""
                while True:
                    chunk = await reader.read(512)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        self._handle_native_line(line.decode(errors="ignore"))
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                if writer in self._native_writers:
                    self._native_writers.remove(writer)
                logger.info("[FF2] Native hooks disconnected")

        self._native_server = await asyncio.start_server(handle, NATIVE_IPC_HOST, NATIVE_IPC_PORT)

    def _handle_native_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        if line.startswith("LOG "):
            logger.info(f"[FF2-native] {line[4:]}")
            return

        if line.startswith("LEVEL_COMPLETE "):
            try:
                completed_id = int(line.split(" ", 1)[1])
            except ValueError:
                return
            self.last_known_level = completed_id
            if completed_id in self._completed_levels:
                return
            self._completed_levels.add(completed_id)
            content_lvl = self._content_level(completed_id)
            self._send_location(location_id_for(content_lvl, 2))
            logger.info(f"[FF2] Check: Slot {completed_id + 1} -> Content {content_lvl + 1} Complete")
            return

        if line.startswith("STAGE_COMPLETE "):
            parts = line.split(" ")
            if len(parts) != 3:
                return
            try:
                level_id, stage = int(parts[1]), int(parts[2])
            except ValueError:
                return
            self.last_known_level = level_id
            self.last_known_stage = stage
            check_key = (level_id, stage)
            if check_key in self._completed_stages:
                return
            self._completed_stages.add(check_key)
            content_lvl = self._content_level(level_id)
            if (content_lvl + 1) in BONUS_LEVELS:
                return  # bonus levels only get a Complete check, not per-stage
            self._send_location(location_id_for(content_lvl, stage - 1))
            logger.info(f"[FF2] Check: Slot {level_id + 1} -> Content {content_lvl + 1} Stage {stage}")
            return

        if line == "GOAL":
            self._send_goal()
            logger.info("[FF2] Boss defeated — goal sent!")
            return

        if line.startswith("DEATH_LINK_SEND"):
            # Echo suppression (a death we caused via an incoming DeathLink shouldn't
            # bounce back out as a new one) happens natively now — see
            # state::g_deathlink_suppress_lives in native/ff2ap_hooks/state.h. Every
            # DEATH_LINK_SEND that reaches here is a genuine, locally-caused death.
            self._send_death_link()
            return

    def _send_native(self, message: str) -> None:
        if not self._native_writers:
            return
        data = (message + "\n").encode()
        for writer in list(self._native_writers):
            try:
                writer.write(data)
            except (ConnectionResetError, BrokenPipeError):
                pass

    def _push_allowed_max(self) -> None:
        self._send_native(f"ALLOWED_MAX {max_allowed_stage(self.fish_received)}")

    def _push_ability_state(self) -> None:
        self._send_native(f"DASH_ENABLED {int(self.dash_received)}")
        self._send_native(f"SUCK_ENABLED {int(self.suck_received)}")

    def _push_shuffle(self) -> None:
        if not self.level_shuffle:
            return
        self._send_native(f"SHUFFLE {','.join(str(v) for v in self.level_shuffle[:60])}")

    # ── GUI ────────────────────────────────────────────────────────────────────

    def run_gui(self) -> None:
        from kvui import GameManager
        from kivy.metrics import dp
        from kivymd.uix.button import MDButton, MDButtonText

        class FF2Manager(GameManager):
            logging_pairs = [("Client", "Archipelago")]
            base_title = "Feeding Frenzy 2 Client"

            def build(self):
                b = super().build()
                button = MDButton(MDButtonText(text="Launch Game"), style="filled",
                                   size=(dp(100), dp(70)), radius=5,
                                   size_hint_x=None, size_hint_y=None, pos_hint={"center_y": 0.55},
                                   on_press=lambda _: launch_game())
                button.height = self.server_connect_bar.height
                self.connect_layout.add_widget(button)
                return b

        self.ui = FF2Manager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    Utils.init_logging("FF2Client", exception_logger="Client")

    async def _main():
        parser = get_base_parser(description="Feeding Frenzy 2 Archipelago Client")
        args   = parser.parse_args()

        ctx = FF2Context(args.connect, args.password)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        await ctx._start_native_server()

        await ctx.exit_event.wait()
        await ctx.shutdown()

    import colorama
    colorama.init()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
