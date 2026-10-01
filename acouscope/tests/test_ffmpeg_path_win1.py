# SPDX-License-Identifier: GPL-3.0-only
"""WIN-1 守卫：audio/io.py 捆绑 ffmpeg 路径解析（Windows .exe 候选 + 目录陷阱 + 回退）。

背景（Windows 回传物审计）：旧实现候选文件名写无扩展名 "ffmpeg"，Windows 上
恒不命中；且同名目录会因 exists()+X_OK 双真被误选。本档钉新行为：平台后缀、
is_file 守卫、X_OK 守卫、系统 PATH 回退、全缺 ⇒ None。
全部用例纯 tmp 文件系统 + monkeypatch，零真网络、零 Qt、零真 shutil 触碰。
"""
import pathlib
import sys
import types

from acouscope.audio import io as aio


def _make_pkg(tmp_path, *, name, mode=0o755, as_dir=False):
    """搭假包布局 tmp/pkg/audio/io.py + tmp/pkg/resources/bin/<name>。

    返回 (假 __file__, 期望二进制绝对路径·resolve 后)。
    """
    pkg = tmp_path / "pkg"
    (pkg / "audio").mkdir(parents=True)
    bindir = pkg / "resources" / "bin"
    bindir.mkdir(parents=True)
    target = bindir / name
    if as_dir:
        target.mkdir()
    else:
        target.write_bytes(b"#!/bin/sh\n")
        target.chmod(mode)
    return str(pkg / "audio" / "io.py"), str(target.resolve())


def _stub_which(monkeypatch, ret):
    monkeypatch.setattr(aio, "shutil", types.SimpleNamespace(which=lambda n: ret))


def test_win32_candidate_uses_exe_suffix(monkeypatch, tmp_path):
    """Windows 场景：包内只有 ffmpeg.exe ⇒ 必须命中（旧实现此处恒不中=改前必红）。"""
    fake_file, expected = _make_pkg(tmp_path, name="ffmpeg.exe")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(aio, "__file__", fake_file)
    _stub_which(monkeypatch, None)
    assert aio._get_ffmpeg_path() == expected


def test_posix_candidate_uses_bare_name(monkeypatch, tmp_path):
    """非 Windows 场景：包内是无扩展名 ffmpeg ⇒ 必须命中（mac 包回归保护）。"""
    fake_file, expected = _make_pkg(tmp_path, name="ffmpeg")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(aio, "__file__", fake_file)
    _stub_which(monkeypatch, None)
    assert aio._get_ffmpeg_path() == expected


def test_same_name_directory_not_selected(monkeypatch, tmp_path):
    """同名目录陷阱：resources/bin/ffmpeg 是目录（exists+X_OK 双真）⇒ 必须跳过（旧实现选中它=改前必红）。"""
    fake_file, _dir = _make_pkg(tmp_path, name="ffmpeg", as_dir=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(aio, "__file__", fake_file)
    _stub_which(monkeypatch, "WHICH_SENTINEL")
    assert aio._get_ffmpeg_path() == "WHICH_SENTINEL"


def test_non_executable_bundled_falls_back(monkeypatch, tmp_path):
    """随包文件在但无执行位 ⇒ 回退系统 PATH。"""
    fake_file, _ = _make_pkg(tmp_path, name="ffmpeg", mode=0o644)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(aio, "__file__", fake_file)
    _stub_which(monkeypatch, "WHICH_SENTINEL")
    assert aio._get_ffmpeg_path() == "WHICH_SENTINEL"


def test_returns_none_when_nothing_found(monkeypatch, tmp_path):
    """无随包二进制且系统无 ffmpeg ⇒ None（上层给「未找到 FFmpeg」友好提示）。"""
    pkg = tmp_path / "pkg"
    (pkg / "audio").mkdir(parents=True)
    (pkg / "resources" / "bin").mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(aio, "__file__", str(pkg / "audio" / "io.py"))
    _stub_which(monkeypatch, None)
    assert aio._get_ffmpeg_path() is None
