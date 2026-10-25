#!/usr/bin/env bash
# Builds the one-folder PyInstaller bundle into dist/mangosteen (needs the project installed with its dependencies
# and `pip install pyinstaller` in the active environment).
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/make_icons.py
rm -rf dist/mangosteen build/pyinstaller
pyinstaller --noconfirm --distpath dist --workpath build/pyinstaller packaging/mangosteen.spec
du -sh dist/mangosteen
