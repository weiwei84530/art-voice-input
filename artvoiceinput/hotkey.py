"""The hotkey that turns listening on and off: win/hotkey.py (low-level hooks) or mac/hotkey.py (a Quartz event
tap), the same Hotkeys class."""
from .system import MAC

if MAC:
    from .mac.hotkey import Hotkeys  # noqa: F401
else:
    from .win.hotkey import Hotkeys  # noqa: F401
