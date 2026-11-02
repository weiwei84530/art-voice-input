"""Speakers muted while listening (錄音時暫時靜音電腦音效): win/mute.py (Core Audio) or mac/mute.py."""
from .system import MAC

if MAC:
    from .mac.mute import Muter, recover  # noqa: F401
else:
    from .win.mute import Muter, recover  # noqa: F401
