"""Checks GitHub for a newer release and installs it the way this copy was installed: the AppImage replaces itself,
the .deb is installed with the system's password prompt, and a copy installed from source with pip is reinstalled
from the release's source archive. Nothing here touches Qt, so the window runs it on a worker thread."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from . import log, paths

REPOSITORY = "SpaceCadet0/Mangosteen-Linux"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
_LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_TIMEOUT = 20

# Where distributions keep their certificate bundle, for when the bundled OpenSSL looks in the build machine's place.
_CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/ca-bundle.pem",
             "/etc/ssl/cert.pem", "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem")

APPIMAGE, DEB, PIP, MANUAL = "appimage", "deb", "pip", "manual"


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass
class Release:
    tag: str
    version: tuple[int, ...]
    notes: str
    page: str
    assets: list[Asset] = field(default_factory=list)
    source_archive: str = ""

    @property
    def version_text(self) -> str:
        return self.tag.removeprefix("v")


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    """(0, 2, 0) from "v0.2.0" or "0.2.0"; a pre-release suffix is ignored."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(release: Release, current: str = __version__) -> bool:
    return release.version > parse_version(current)


# MARK: Network

def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not context.get_ca_certs():
        for candidate in _CA_FILES:
            if os.path.exists(candidate):
                context.load_verify_locations(candidate)
                break
    return context


def _open(url: str, accept: str = "application/octet-stream"):  # noqa: ANN202
    request = urllib.request.Request(url, headers={"User-Agent": f"Mangosteen/{__version__}", "Accept": accept})
    return urllib.request.urlopen(request, timeout=_TIMEOUT, context=_ssl_context())


def release_from_json(data: dict) -> Release:
    tag = data["tag_name"]
    assets = [Asset(item["name"], item["browser_download_url"], int(item.get("size") or 0))
              for item in data.get("assets", [])]
    return Release(tag, parse_version(tag), data.get("body") or "", data.get("html_url") or RELEASES_PAGE, assets,
                   data.get("tarball_url") or f"https://github.com/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz")


def latest_release() -> Release:
    try:
        with _open(_LATEST, "application/vnd.github+json") as response:
            return release_from_json(json.load(response))
    except (OSError, ValueError, KeyError) as error:
        if getattr(error, "code", None) == 404:
            raise UpdateError("no release has been published yet") from error
        raise UpdateError(str(getattr(error, "reason", None) or error)) from error


def download(url: str, target: Path, progress: Callable[[float], None] | None = None, size: int = 0) -> None:
    """Downloads to `target` + ".part" and renames it when complete, so an interrupted download leaves nothing."""
    part = target.with_name(target.name + ".part")
    try:
        with _open(url) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or size or 0)
            done = 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0))
        os.replace(part, target)
    except OSError as error:
        part.unlink(missing_ok=True)
        raise UpdateError(str(getattr(error, "reason", None) or error)) from error


# MARK: How this copy was installed

def _arch() -> str:
    machine = platform.machine().lower()
    return "x86_64" if machine == "amd64" else machine


def _pip_source() -> dict | None:
    """pip's record of where this copy came from (direct_url.json), when it was installed from a folder or archive."""
    try:
        from importlib.metadata import distribution

        text = distribution("mangosteen").read_text("direct_url.json")
        return json.loads(text) if text else None
    except Exception:  # noqa: BLE001 - not installed with pip at all
        return None


def install_method() -> str:
    if os.environ.get("APPIMAGE"):
        return APPIMAGE
    if getattr(sys, "frozen", False):
        return DEB if str(Path(sys.executable).resolve()).startswith("/opt/mangosteen/") else MANUAL
    source = _pip_source()
    if source is not None and not source.get("dir_info", {}).get("editable"):
        return PIP
    return MANUAL


def asset_for(release: Release, method: str) -> Asset | None:
    arch = _arch()
    for asset in release.assets:
        if method == APPIMAGE and asset.name.endswith(f"-{arch}.AppImage"):
            return asset
        if method == DEB and arch == "x86_64" and asset.name.endswith("_amd64.deb"):
            return asset
    return None


def can_install(release: Release, method: str | None = None) -> bool:
    method = method or install_method()
    if method in (APPIMAGE, DEB):
        return asset_for(release, method) is not None and (method != DEB or shutil.which("pkexec") is not None)
    return method == PIP


def manual_steps(release: Release, method: str | None = None) -> str:
    """The commands for a copy the window cannot update by itself."""
    method = method or install_method()
    if method == DEB:
        asset = asset_for(release, DEB)
        name = asset.name if asset else f"mangosteen_{release.version_text}_amd64.deb"
        return (f"wget {asset.url if asset else RELEASES_PAGE}\n"
                f"sudo apt install ./{name}")
    source = _pip_source()
    folder = (source or {}).get("url", "").removeprefix("file://")
    if folder:
        return f"cd {folder}\ngit pull\npip install ."
    return f"pip install --upgrade {release.source_archive}"


# MARK: Installing

def install(release: Release, progress: Callable[[float], None] | None = None,
            method: str | None = None) -> list[str]:
    """Installs `release`; returns the command that starts the new version."""
    method = method or install_method()
    log.write(f"update to {release.tag} ({method})")
    if method == APPIMAGE:
        return _install_appimage(release, progress)
    if method == DEB:
        return _install_deb(release, progress)
    if method == PIP:
        return _install_pip(release)
    raise UpdateError("this copy cannot be updated from the app")


def _install_appimage(release: Release, progress: Callable[[float], None] | None) -> list[str]:
    asset = asset_for(release, APPIMAGE)
    if asset is None:
        raise UpdateError(f"the release has no AppImage for {_arch()}")
    current = Path(os.environ["APPIMAGE"])
    target = current.with_name(asset.name)
    if not os.access(current.parent, os.W_OK):
        raise UpdateError(f"{current.parent} is not writable")
    # Replacing even the running file is safe: the running copy keeps the old one open until it exits.
    download(asset.url, target, progress, asset.size)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if target != current:
        current.unlink(missing_ok=True)
    return [str(target)]


def _install_deb(release: Release, progress: Callable[[float], None] | None) -> list[str]:
    asset = asset_for(release, DEB)
    if asset is None:
        raise UpdateError("the release has no .deb for this processor")
    folder = paths.state_dir() / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    package = folder / asset.name
    download(asset.url, package, progress, asset.size)
    if progress:
        progress(1.0)
    _run(["pkexec", "apt-get", "install", "-y", "--allow-downgrades", str(package)], timeout=900)
    package.unlink(missing_ok=True)
    return ["/usr/bin/mangosteen"]


def _install_pip(release: Release) -> list[str]:
    _run([sys.executable, "-m", "pip", "install", "--upgrade", release.source_archive], timeout=1800)
    from shutil import which

    installed = which("mangosteen") or str(Path(sys.executable).with_name("mangosteen"))
    return [installed] if os.path.exists(installed) else [sys.executable, "-m", "mangosteen"]


def _run(command: list[str], timeout: int) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(str(error)) from error
    if result.returncode in (126, 127) and command[0] == "pkexec":
        raise UpdateError("the password prompt was dismissed")
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        log.write(f"update command failed: {command[:3]}: {' | '.join(lines[-6:])}")
        raise UpdateError(lines[-1] if lines else f"exit code {result.returncode}")


def restart_command(new_command: list[str]) -> list[str]:
    """Waits for this process to exit (so the new one becomes the running instance, at most ten seconds), then starts
    the new version."""
    script = 'i=0; while kill -0 "$0" 2>/dev/null && [ $i -lt 50 ]; do sleep 0.2; i=$((i+1)); done; exec "$@"'
    return ["/bin/sh", "-c", script, str(os.getpid()), *new_command]


__all__ = ["APPIMAGE", "DEB", "MANUAL", "PIP", "RELEASES_PAGE", "Asset", "Release", "UpdateError", "asset_for",
           "can_install", "download", "install", "install_method", "is_newer", "latest_release", "manual_steps",
           "parse_version", "release_from_json", "restart_command"]
