"""Entry of the setup exe (installer/setup.spec): setup with the payload attached, uninstall without it."""
import sys

from installer.ui import main

sys.exit(main())
