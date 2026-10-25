# Security policy

Mangosteen for Linux works offline: it does not send files or data anywhere, has no accounts and no telemetry. It runs
with the rights of the signed-in user. On X11 it asks the X server for the pointer and key state while a drag is in
progress (and listens for selection changes of the drag-and-drop protocol), which it uses only to notice Shift, Ctrl or
Alt during a drag and to learn which files are being dragged. It listens on a local socket (Qt's `QLocalServer`, restricted to your user) so
that a second launch can pass its files to the running instance. FFmpeg and
Tesseract run as separate processes started with the file names you chose.

## Supported versions

Only the [latest release](https://github.com/SpaceCadet0/Mangosteen-Linux/releases/latest) gets fixes.

## Reporting a vulnerability

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/SpaceCadet0/Mangosteen-Linux/security/advisories/new)
rather than in a public issue. Include the version, what you did and what happened. You will get an answer within a
week.

Problems in FFmpeg, Qt, PDFium or the other libraries belong to those projects; a new Mangosteen release picks up their
fixes.
