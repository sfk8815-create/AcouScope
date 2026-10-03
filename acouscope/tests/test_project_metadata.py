# SPDX-License-Identifier: GPL-3.0-only
"""T-907：Project 数据层文件级元数据测试（app/project.py）。

覆盖需求说明 Step 5 清单：
① 往返：new → add_file 设文件 metadata → save → load → 各文件 metadata 逐项相等；
② 项目级不变式：Project 不因本任务新增 metadata 属性（防擅自加回无用字段）；
③ 向后兼容：无 metadata 键的旧格式 json load → metadata=={} 不抛；
   metadata=null / 非字符串值容忍（字符串化，不抛）；
④ get_file：存在 path → 返回对应 ProjectFile；不存在 → None（不抛）；
⑤ remove_file：存在 path → True 且 files 少一项（幂等）；不存在 → False 不变；
⑥ version：新项目 "0.2"；旧 "0.1" 文件 load 不报错且原样保留；缺键兜底 "0.2"；
⑦ 禁词（02_References 下 "The Pitch Grid" 文档文件名首段品牌词）0 命中。

口径：纯数据层、离屏、不构造 MainWindow。
"""

import json
from pathlib import Path

from acouscope.app.project import Project, ProjectManager

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_settings_llama_models.py 口径）。
_BANNED = "Mel" + "odyne"

_PROJECT_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "app" / "project.py"
)


def _write_old_format(path: Path, **overrides) -> None:
    """手写旧格式 .acouproj（无 metadata 键、version 0.1）。"""
    data = {
        "name": "旧格式项目",
        "version": "0.1",
        "files": [
            {"path": "/a/old1.wav", "label": "旧一"},
            {"path": "/a/old2.wav", "label": ""},
        ],
        "annotations": [],
        "presets": {},
    }
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class TestFileMetadataRoundtrip:
    def test_roundtrip_per_file(self, tmp_path):
        """① 多文件各自 metadata 逐项往返相等。"""
        pm = ProjectManager()
        pm.new("元数据往返")
        pf1 = pm.add_file("/a/one.wav", "一")
        pf1.metadata.update({"Title": "田野录音一", "Creator": "张三", "_standard": "DAT63"})
        pf2 = pm.add_file("/a/two.wav")
        pf2.metadata["SamplingRate"] = "44100"
        assert pm.current.files[0] is pf1

        proj_path = tmp_path / "rt.acouproj"
        pm.save(proj_path)

        pm2 = ProjectManager()
        loaded = pm2.load(proj_path)
        assert len(loaded.files) == 2
        assert loaded.files[0].metadata == pf1.metadata
        assert loaded.files[1].metadata == {"SamplingRate": "44100"}
        # 值类型不变式：全部 str
        for f in loaded.files:
            assert all(isinstance(v, str) for v in f.metadata.values())

    def test_empty_metadata_roundtrip(self, tmp_path):
        """未填 metadata 的文件往返后仍为空 dict。"""
        pm = ProjectManager()
        pm.new("空元数据")
        pm.add_file("/a/empty.wav")
        proj_path = tmp_path / "empty.acouproj"
        pm.save(proj_path)

        loaded = ProjectManager().load(proj_path)
        assert loaded.files[0].metadata == {}


class TestProjectLevelInvariant:
    def test_project_has_no_metadata_attr(self):
        """② 项目级不变式：Project 无 metadata 属性（T-907 明确不加）。"""
        assert not hasattr(Project(), "metadata")
        pm = ProjectManager()
        pm.new()
        assert not hasattr(pm.current, "metadata")


class TestBackwardCompat:
    def test_old_format_without_metadata_key(self, tmp_path):
        """③ 旧格式无 metadata 键 → 文件 metadata=={}、零崩溃。"""
        p = tmp_path / "old.acouproj"
        _write_old_format(p)
        loaded = ProjectManager().load(p)
        assert [f.path for f in loaded.files] == ["/a/old1.wav", "/a/old2.wav"]
        assert all(f.metadata == {} for f in loaded.files)

    def test_metadata_null_tolerated(self, tmp_path):
        """metadata=null → 空 dict，不抛。"""
        p = tmp_path / "null.acouproj"
        _write_old_format(
            p,
            files=[{"path": "/a/n.wav", "label": "", "metadata": None}],
        )
        loaded = ProjectManager().load(p)
        assert loaded.files[0].metadata == {}

    def test_non_string_values_stringified(self, tmp_path):
        """非字符串值容忍：读取时统一字符串化，不抛。"""
        p = tmp_path / "mixed.acouproj"
        _write_old_format(
            p,
            version="0.2",
            files=[
                {
                    "path": "/a/m.wav",
                    "label": "",
                    "metadata": {"SamplingRate": 44100, "BitDepth": 16},
                }
            ],
        )
        loaded = ProjectManager().load(p)
        assert loaded.files[0].metadata == {"SamplingRate": "44100", "BitDepth": "16"}


class TestGetFile:
    def test_get_file_hit(self):
        """④ 存在 path → 返回对应 ProjectFile（同一对象）。"""
        pm = ProjectManager()
        pm.new()
        pf = pm.add_file("/a/hit.wav")
        assert pm.get_file("/a/hit.wav") is pf
        # Path 入参等价 str
        assert pm.get_file(Path("/a/hit.wav")) is pf

    def test_get_file_miss(self):
        """不存在 path → None（不抛）。"""
        pm = ProjectManager()
        pm.new()
        pm.add_file("/a/one.wav")
        assert pm.get_file("/a/missing.wav") is None


class TestRemoveFile:
    def test_remove_hit(self):
        """⑤ 存在 path → True 且 files 少一项。"""
        pm = ProjectManager()
        pm.new()
        pm.add_file("/a/keep.wav")
        pm.add_file("/a/drop.wav")
        assert pm.remove_file("/a/drop.wav") is True
        assert [f.path for f in pm.current.files] == ["/a/keep.wav"]

    def test_remove_miss_and_idempotent(self):
        """不存在 path → False 且 files 不变；重复移除幂等。"""
        pm = ProjectManager()
        pm.new()
        pf = pm.add_file("/a/only.wav")
        assert pm.remove_file("/a/nope.wav") is False
        assert [f.path for f in pm.current.files] == ["/a/only.wav"]
        assert pm.remove_file("/a/only.wav") is True
        assert pm.current.files == []
        assert pm.remove_file("/a/only.wav") is False  # 幂等不抛
        assert pf.metadata == {}  # 被移除条目自身状态不受影响


class TestVersion:
    def test_new_project_version_02(self):
        """⑥ 新项目 version == "0.2"。"""
        pm = ProjectManager()
        pm.new("v2")
        assert pm.current.version == "0.2"

    def test_load_old_01_preserved(self, tmp_path):
        """旧 "0.1" 文件 load 不报错且原样保留。"""
        p = tmp_path / "v01.acouproj"
        _write_old_format(p)
        loaded = ProjectManager().load(p)
        assert loaded.version == "0.1"

    def test_load_missing_version_defaults_02(self, tmp_path):
        """缺 version 键 → 兜底 "0.2"。"""
        p = tmp_path / "noversion.acouproj"
        _write_old_format(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        del data["version"]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        loaded = ProjectManager().load(p)
        assert loaded.version == "0.2"


class TestBannedWord:
    def test_banned_word_zero_hits(self):
        """⑦ 禁词（品牌词）在 project.py 与本测试文件中 0 命中。"""
        for f in (_PROJECT_PY, Path(__file__).resolve()):
            src = f.read_text(encoding="utf-8")
            assert _BANNED not in src, f"{f.name} 出现禁词 {_BANNED!r}"
