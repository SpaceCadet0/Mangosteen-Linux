#!/usr/bin/env bash
# Builds dist/Mangosteen-<version>-x86_64.AppImage from the PyInstaller bundle (run build-bundle.sh first). It carries
# its own FFmpeg (fetch-ffmpeg.sh); Tesseract, when installed on the computer, is picked up from PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1)"
appdir="build/AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib" "$appdir/usr/bin" "$appdir/usr/share/applications" "$appdir/usr/share/icons"
cp -a dist/mangosteen "$appdir/usr/lib/mangosteen"
cp -a packaging/icons/hicolor "$appdir/usr/share/icons/hicolor"
cp packaging/icons/hicolor/256x256/apps/mangosteen.png "$appdir/mangosteen.png"
cp packaging/icons/hicolor/256x256/apps/mangosteen.png "$appdir/.DirIcon"
sed 's|^Exec=mangosteen|Exec=mangosteen|' packaging/mangosteen.desktop > "$appdir/mangosteen.desktop"
cp "$appdir/mangosteen.desktop" "$appdir/usr/share/applications/"
cp LICENSE THIRD-PARTY-NOTICES.md "$appdir/usr/lib/mangosteen/"

if [ "${SKIP_FFMPEG:-0}" != "1" ]; then
    packaging/fetch-ffmpeg.sh "$appdir/usr/bin"
elif command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
    echo "SKIP_FFMPEG=1: using the system FFmpeg at run time"
fi
# Qt 6.5+ needs this library on the host, and many desktops do not have it installed.
for lib in libxcb-cursor.so.0; do
    found="$(ldconfig -p | awk -v l="$lib" '$1 == l {print $NF; exit}')"
    [ -n "$found" ] && cp -L "$found" "$appdir/usr/lib/mangosteen/_internal/" || echo "warning: $lib not found to bundle"
done

cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export APPDIR="$HERE"
exec "$HERE/usr/lib/mangosteen/mangosteen" "$@"
APPRUN
chmod 755 "$appdir/AppRun"

tool="${APPIMAGETOOL:-appimagetool}"
mkdir -p dist
ARCH=x86_64 "$tool" --appimage-extract-and-run "$appdir" "dist/Mangosteen-${version}-x86_64.AppImage" 2>&1 \
    || ARCH=x86_64 "$tool" "$appdir" "dist/Mangosteen-${version}-x86_64.AppImage"
ls -la "dist/Mangosteen-${version}-x86_64.AppImage"
