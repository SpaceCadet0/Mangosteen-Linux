# Third-party notices

Mangosteen for Linux is MIT-licensed (see [LICENSE](LICENSE)). It is built on the open-source components below, each
used under its own license; the license texts are available at the linked projects and, for the installed packages,
inside the bundle.

| Component | Used for | License |
| --- | --- | --- |
| [Python](https://www.python.org) 3.13 | The runtime | PSF License |
| [Qt 6](https://www.qt.io) through [PySide6](https://pyside.org) 6.12 | The user interface, painting, text, SVG and media playback | LGPL-3.0 (or GPL-2.0 / GPL-3.0) |
| [Pillow](https://python-pillow.github.io) | Reading and writing images | MIT-CMU (HPND) |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) with libheif, libde265 and x265 | HEIC (and AVIF) pictures | BSD-3-Clause; libheif and libde265 LGPL-3.0; x265 GPL-2.0-or-later |
| [NumPy](https://numpy.org) | Image maths | BSD-3-Clause |
| [OpenCV](https://opencv.org) (opencv-python-headless) | Blur, pixelation, face detection | Apache-2.0 |
| [pypdf](https://github.com/py-pdf/pypdf) | Joining, splitting, rotating and compressing PDF pages | BSD-3-Clause |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) and [PDFium](https://pdfium.googlesource.com/pdfium/) | Drawing PDF pages and reading their text | BSD-3-Clause / Apache-2.0 |
| [python-xlib](https://github.com/python-xlib/python-xlib) | Watching drags and the wheel keys on X11 | LGPL-2.1-or-later |
| [FFmpeg](https://ffmpeg.org) 8.x, the [BtbN build](https://github.com/BtbN/FFmpeg-Builds) with x264, libvpx, libaom, Opus, LAME and more | Video and audio (carried by the AppImage; the .deb uses the distribution's package) | GPL-3.0 |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Recognising text (optional; the distribution's package) | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Running the background-removal model (optional) | MIT |
| [IS-Net](https://github.com/xuebinqin/DIS) "general use" model, ONNX export by [rembg](https://github.com/danielgatis/rembg) | Remove background (optional, downloaded on request) | Apache-2.0 |
| [PyInstaller](https://pyinstaller.org) | Packaging the AppImage and .deb | GPL-2.0-or-later with an exception for the programs it builds |

## Qt and PySide6 (LGPL)

Qt and PySide6 are used under the GNU Lesser General Public License version 3. In the AppImage and the .deb they are
ordinary shared libraries in the bundle's `_internal` folder, not merged into the program, so they can be replaced by
your own build of the same version. Source: https://code.qt.io and https://code.qt.io/cgit/pyside/pyside-setup.git.

## GPL components

FFmpeg (in the AppImage) runs as a separate program that Mangosteen starts; it is not linked. Its licence text and exact
version are placed next to it (`FFmpeg-LICENSE.txt`, `FFmpeg-VERSION.txt`). The source is at
https://ffmpeg.org/download.html and the build scripts at https://github.com/BtbN/FFmpeg-Builds.

pillow-heif's binary wheels carry x265, which is licensed under GPL-2.0-or-later and runs inside the program's process
when a picture is saved as HEIC. The packages that contain it therefore include GPL-licensed code; Mangosteen's own
source stays MIT-licensed and is complete in this repository, and the sources of the third-party parts are at
https://github.com/bigcat88/pillow_heif, https://bitbucket.org/multicoreware/x265_git and
https://github.com/strukturag/libheif. HEIC is the only feature that needs x265: without pillow-heif (it is a normal
Python dependency, `pip uninstall pillow-heif`) Mangosteen still works and simply does not offer HEIC.

## IS-Net

The background-removal model is IS-Net from "Highly Accurate Dichotomous Image Segmentation" (Qin et al., ECCV 2022),
Copyright (c) Xuebin Qin, licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
It is not part of the package: Mangosteen downloads it only when you ask for the better model in Remove background,
stores it in `~/.local/share/mangosteen/models`, and runs it on your computer. The built-in method needs no download.
