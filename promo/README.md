# Mangosteen demo video

A [Remotion](https://www.remotion.dev) project for the looping demo, built on the macOS app's (SpaceCadet0/Mangosteen,
`promo/`): one scene per wheel (Convert, Tools, Actions) in the light theme, 30 fps. Start dragging a file, tap the
key without letting go, drop it on a segment. The icons, wheels and windows are the Linux app's own.

```bash
python promo/scripts/make_assets.py          # from the repository root: icons, thumbnails, Trim and Float snapshots
cd promo && npm ci
npx remotion studio                          # preview
npx remotion render LinuxDemoSquare out/LinuxDemoSquare.mp4 --codec=h264 --crf=12   # 1000 × 1000, welcome window
npx remotion render LinuxDemo out/LinuxDemo.mp4 --codec=h264 --crf=12               # 1600 × 1000, README
```

Add `--browser-executable=<chrome-headless-shell>` to use a browser that is already installed.

Then, from the repository root:

```bash
ffmpeg -i promo/out/LinuxDemoSquare.mp4 -vf scale=600:600:flags=lanczos -an -c:v libx264 -preset slow -crf 24 \
  -pix_fmt yuv420p -movflags +faststart src/mangosteen/assets/welcome-demo.mp4
ffmpeg -ss 2.9 -i src/mangosteen/assets/welcome-demo.mp4 -frames:v 1 src/mangosteen/assets/welcome-demo.png
ffmpeg -i promo/out/LinuxDemo.mp4 -an -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart \
  docs/media/mangosteen-demo.mp4
ffmpeg -i promo/out/LinuxDemo.mp4 -vf fps=30,scale=1200:-1:flags=lanczos -c:v libwebp_anim -q:v 80 \
  -compression_level 6 -loop 0 docs/images/demo.webp
```

The sample photos are `docs/samples/*.webp`.
