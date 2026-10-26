# Mangosteen demo video

A [Remotion](https://www.remotion.dev) project for the looping demo, built on the macOS app's (SpaceCadet0/Mangosteen,
`promo/`): one scene per wheel (Convert, Tools, Actions) in the light theme, 30 fps. Start dragging a file, tap the
key without letting go, drop it on a segment. The icons, wheels and windows are the Linux app's own.

```bash
python promo/scripts/make_assets.py          # from the repository root: icons, thumbnails, Trim and Float snapshots
cd promo && npm ci
npx remotion studio                          # preview
# Lossless PNG frames: the videos are encoded from them, never from an already compressed video.
npx remotion render LinuxDemo frames-wide --sequence --image-format=png               # 1600 × 1000, README
npx remotion render LinuxDemoSquare frames-square --sequence --image-format=png       # 1000 × 1000, welcome window
```

Add `--browser-executable=<chrome-headless-shell>` to use a browser that is already installed.

Then, from the repository root:

```bash
# README animation: every frame a keyframe (-kmin 0 -kmax 1), so nothing of a vanished element is left behind.
mkdir -p promo/frames-readme
ffmpeg -i promo/frames-wide/element-%03d.png -vf scale=1200:-1:flags=lanczos promo/frames-readme/f-%03d.png
img2webp -loop 0 -kmin 0 -kmax 1 -lossy -q 85 -m 6 -d 33 promo/frames-readme/f-*.png -o docs/images/demo.webp
ffmpeg -framerate 30 -i promo/frames-wide/element-%03d.png -vf format=yuv420p -an -c:v libx264 -preset slow \
  -tune animation -crf 17 -g 30 -movflags +faststart docs/media/mangosteen-demo.mp4
# Welcome window (shown at 300 × 300; 600 × 600 for HiDPI) and its still. An animated WebP, which Qt plays with its
# image plugins alone: its video player needs a multimedia backend that PySide6 for ARM does not have.
mkdir -p promo/frames-welcome
ffmpeg -i promo/frames-square/element-%03d.png -vf scale=600:600:flags=lanczos promo/frames-welcome/f-%03d.png
img2webp -loop 0 -kmin 0 -kmax 1 -lossy -q 80 -m 6 -d 33 promo/frames-welcome/f-*.png -o src/mangosteen/assets/welcome-demo.webp
ffmpeg -i promo/frames-square/element-087.png -vf scale=600:600:flags=lanczos src/mangosteen/assets/welcome-demo.png
```

The sample photos are `docs/samples/*.webp`.
