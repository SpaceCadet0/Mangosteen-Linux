#!/usr/bin/env bash
# Downloads a static GPL FFmpeg build (BtbN/FFmpeg-Builds), verifies it against the checksums published with the same
# release, and unpacks ffmpeg and ffprobe plus the licence and version notes into the folder given as $1.
# Used for the AppImage, which carries its own FFmpeg; the .deb depends on the distribution's package instead.
set -euo pipefail
target="${1:?usage: fetch-ffmpeg.sh <target-folder>}"
mkdir -p "$target"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
api="https://api.github.com/repos/BtbN/FFmpeg-Builds/releases"
auth=()
[ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer ${GITHUB_TOKEN}")

# The newest dated autobuild that has a linux64 GPL build of a numbered FFmpeg release (not master).
curl -fsSL "${auth[@]}" "$api?per_page=30" -o "$work/releases.json"
read -r tag name < <(python3 - "$work/releases.json" <<'PY'
import json, re, sys
for release in json.load(open(sys.argv[1])):
    if not release["tag_name"].startswith("autobuild-"):
        continue
    for asset in release["assets"]:
        if re.fullmatch(r"ffmpeg-n\d+\.\d+(\.\d+)?-.*-linux64-gpl-\d+\.\d+\.tar\.xz", asset["name"]):
            print(release["tag_name"], asset["name"])
            sys.exit(0)
sys.exit("no numbered linux64-gpl autobuild found")
PY
)
base="https://github.com/BtbN/FFmpeg-Builds/releases/download/$tag"
echo "FFmpeg: $base/$name"
curl -fsSL "$base/$name" -o "$work/$name"
curl -fsSL "$base/checksums.sha256" -o "$work/checksums.sha256"
expected="$(grep " $name\$" "$work/checksums.sha256" | cut -d' ' -f1)"
actual="$(sha256sum "$work/$name" | cut -d' ' -f1)"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || { echo "FFmpeg checksum mismatch ($expected vs $actual)" >&2; exit 1; }

tar -xJf "$work/$name" -C "$work"
root="$(find "$work" -maxdepth 1 -type d -name 'ffmpeg-*' | head -n1)"
install -m 755 "$root/bin/ffmpeg" "$root/bin/ffprobe" "$target/"
cp "$root/LICENSE.txt" "$target/FFmpeg-LICENSE.txt"
printf '%s\nSource: https://ffmpeg.org/download.html\nBuild scripts: https://github.com/BtbN/FFmpeg-Builds\nArchive: %s/%s\nSHA-256: %s\n' \
    "$(basename "$root")" "$base" "$name" "$actual" > "$target/FFmpeg-VERSION.txt"
echo "FFmpeg unpacked into $target"
