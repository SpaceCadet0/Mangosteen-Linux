#!/usr/bin/env bash
# Builds dist/mangosteen_<version>_amd64.deb from the PyInstaller bundle (run build-bundle.sh first).
# The bundle goes to /opt/mangosteen; FFmpeg and Tesseract come from the distribution's packages.
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n1)"
arch="$(dpkg --print-architecture)"
root="build/deb/mangosteen_${version}_${arch}"
rm -rf "$root"
mkdir -p "$root/DEBIAN" "$root/opt" "$root/usr/bin" "$root/usr/share/applications" "$root/usr/share/doc/mangosteen"
cp -a dist/mangosteen "$root/opt/mangosteen"
ln -s /opt/mangosteen/mangosteen "$root/usr/bin/mangosteen"
install -m 644 packaging/mangosteen.desktop "$root/usr/share/applications/mangosteen.desktop"
cp -a packaging/icons/hicolor "$root/usr/share/icons-hicolor-tmp"
mkdir -p "$root/usr/share/icons"
mv "$root/usr/share/icons-hicolor-tmp" "$root/usr/share/icons/hicolor"
install -m 644 LICENSE "$root/usr/share/doc/mangosteen/copyright"
install -m 644 THIRD-PARTY-NOTICES.md "$root/usr/share/doc/mangosteen/THIRD-PARTY-NOTICES.md"
find "$root/opt" -type d -exec chmod 755 {} +
find "$root/usr" -type d -exec chmod 755 {} +

size="$(du -sk "$root" | cut -f1)"
cat > "$root/DEBIAN/control" <<CONTROL
Package: mangosteen
Version: ${version}
Section: utils
Priority: optional
Architecture: ${arch}
Installed-Size: ${size}
Maintainer: Igor Rusakov <r3415222000@gmail.com>
Homepage: https://github.com/SpaceCadet0/Mangosteen-Linux
Depends: libc6 (>= 2.35), ffmpeg, libxcb-cursor0, libxkbcommon-x11-0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0, libegl1, libgl1, libpulse0
Recommends: tesseract-ocr, tesseract-ocr-eng
Suggests: tesseract-ocr-rus, tesseract-ocr-spa
Description: Zero-click file converter and toolbox
 Hold Shift, Ctrl or Alt while dragging files and a round wheel appears at the
 pointer: drop onto a segment to convert, edit or act on them. Converts images,
 PDF, documents, tables, video and audio; crops, compresses, annotates, hides,
 trims and more. Works offline; results are written next to the originals.
CONTROL
cat > "$root/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
exit 0
POSTINST
chmod 755 "$root/DEBIAN/postinst"
dpkg-deb --root-owner-group -Zxz -z6 --build "$root" "dist/mangosteen_${version}_${arch}.deb"
ls -la "dist/mangosteen_${version}_${arch}.deb"
