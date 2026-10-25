"""Entry point for the frozen bundle (PyInstaller cannot start a package's __main__ with its relative imports)."""

import sys

from mangosteen.cli import main

if __name__ == "__main__":
    sys.exit(main())
