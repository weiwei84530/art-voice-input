"""The operating system's side of things that are not text (windows, focus, the mouse hook, sounds): win/system.py
or mac/system.py, which have the same functions. Everything that talks to the OS lives in win/ and mac/, behind
modules at the old names (selection, hotkey, output's keyboard, mute, autostart, system); this is the only place
that looks at sys.platform, besides a few data tables (keys, paths, theme)."""
import sys

MAC = sys.platform == "darwin"

if MAC:
    from .mac.system import *  # noqa: F401,F403
else:
    from .win.system import *  # noqa: F401,F403
