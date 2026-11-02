"""Launch at login: win/autostart.py (the HKCU Run key) or mac/autostart.py (a LaunchAgent)."""
from .system import MAC

if MAC:
    from .mac.autostart import APP_ID, FLAG, command, set_enabled  # noqa: F401
else:
    from .win.autostart import APP_ID, FLAG, command, set_enabled  # noqa: F401
