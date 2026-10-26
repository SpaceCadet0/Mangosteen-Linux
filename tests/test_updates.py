import stat
import subprocess
import time

import pytest

from mangosteen.core import updates


def release(tag="v0.3.0", assets=()):
    return updates.release_from_json({
        "tag_name": tag, "body": "## What's new\n- things", "html_url": "https://example.invalid/r",
        "assets": [{"name": name, "browser_download_url": url, "size": 0} for name, url in assets],
    })


def test_versions_compare_as_numbers():
    assert updates.parse_version("v0.2.0") == (0, 2)
    assert updates.parse_version("0.10.1") > updates.parse_version("0.9.9")
    assert updates.parse_version("v1.0.0-beta") == (1,)
    assert updates.is_newer(release("v0.2.1"), "0.2.0")
    assert not updates.is_newer(release("v0.2.0"), "0.2")
    assert not updates.is_newer(release("v0.1.9"), "0.2.0")


def test_release_reads_the_api_reply():
    r = release("v0.3.0", [("Mangosteen-0.3.0-x86_64.AppImage", "https://x/a"), ("mangosteen_0.3.0_amd64.deb", "https://x/d")])
    assert r.version_text == "0.3.0"
    assert r.source_archive.endswith("/archive/refs/tags/v0.3.0.tar.gz")
    assert [a.name for a in r.assets] == ["Mangosteen-0.3.0-x86_64.AppImage", "mangosteen_0.3.0_amd64.deb"]


def test_assets_match_the_processor(monkeypatch):
    r = release("v0.3.0", [("Mangosteen-0.3.0-x86_64.AppImage", "a"), ("mangosteen_0.3.0_amd64.deb", "d")])
    monkeypatch.setattr(updates.platform, "machine", lambda: "x86_64")
    assert updates.asset_for(r, updates.APPIMAGE).name.endswith(".AppImage")
    assert updates.asset_for(r, updates.DEB).name.endswith(".deb")
    monkeypatch.setattr(updates.platform, "machine", lambda: "aarch64")
    assert updates.asset_for(r, updates.APPIMAGE) is None
    assert updates.asset_for(r, updates.DEB) is None
    assert not updates.can_install(r, updates.APPIMAGE)


def test_install_method(monkeypatch, tmp_path):
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "Mangosteen.AppImage"))
    assert updates.install_method() == updates.APPIMAGE
    monkeypatch.delenv("APPIMAGE")
    monkeypatch.setattr(updates, "_pip_source", lambda: {"url": "file:///home/pi/Mangosteen-Linux", "dir_info": {}})
    assert updates.install_method() == updates.PIP
    assert updates.can_install(release(), updates.PIP)
    monkeypatch.setattr(updates, "_pip_source", lambda: {"url": "file:///src", "dir_info": {"editable": True}})
    assert updates.install_method() == updates.MANUAL
    assert "git pull" in updates.manual_steps(release(), updates.MANUAL)


def test_the_appimage_replaces_itself(monkeypatch, tmp_path):
    new = tmp_path / "download" / "Mangosteen-0.3.0-x86_64.AppImage"
    new.parent.mkdir()
    new.write_bytes(b"#!/bin/sh\necho new\n")
    current = tmp_path / "apps" / "Mangosteen-0.2.0-x86_64.AppImage"
    current.parent.mkdir()
    current.write_bytes(b"old")
    monkeypatch.setenv("APPIMAGE", str(current))
    monkeypatch.setattr(updates.platform, "machine", lambda: "x86_64")
    seen = []
    command = updates.install(release("v0.3.0", [(new.name, new.as_uri())]), seen.append)
    target = current.with_name(new.name)
    assert command == [str(target)]
    assert target.read_bytes() == new.read_bytes()
    assert target.stat().st_mode & stat.S_IXUSR
    assert not current.exists()
    assert not list(current.parent.glob("*.part"))
    assert seen and seen[-1] == 1.0


def test_a_failed_download_leaves_nothing(monkeypatch, tmp_path):
    target = tmp_path / "file"
    with pytest.raises(updates.UpdateError):
        updates.download((tmp_path / "missing").as_uri(), target)
    assert not target.exists() and not list(tmp_path.glob("*.part"))


def test_restart_waits_for_this_process(tmp_path):
    marker = tmp_path / "started"
    # A grandchild, so it is reaped when it ends rather than left as a zombie of the test process.
    pid = subprocess.run(["sh", "-c", "sleep 0.6 >/dev/null 2>&1 & echo $!"], capture_output=True, text=True).stdout
    line = updates.restart_command(["touch", str(marker)])
    line[3] = pid.strip()  # wait for the sleeper instead of the test process
    began = time.monotonic()
    subprocess.run(line, check=True, timeout=10)
    assert marker.exists()
    assert time.monotonic() - began >= 0.4


def test_the_window_offers_the_update(qapp, monkeypatch):
    from mangosteen.ui.update_window import UpdateWindow

    monkeypatch.setattr(updates, "can_install", lambda r, method=None: True)
    window = UpdateWindow()
    window._checked(release("v99.0.0"))
    assert window.action_button.isVisibleTo(window) and window.notes.isVisibleTo(window)
    window._checked(release("v0.0.1"))
    assert not window.action_button.isVisibleTo(window)
    monkeypatch.setattr(updates, "can_install", lambda r, method=None: False)
    window._checked(release("v99.0.0"))
    assert window.steps.isVisibleTo(window) and window.steps.toPlainText()
    window._failed("offline")
    assert window.action_button.text()
    window.close()
