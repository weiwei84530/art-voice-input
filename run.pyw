import sys

if sys.platform != "win32":
    sys.exit("Art VoiceInput runs on Windows only (see docs/macos-port.md).")

from artvoiceinput.app import main

sys.exit(main())
