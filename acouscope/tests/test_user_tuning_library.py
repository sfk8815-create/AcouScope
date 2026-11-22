"""用户自定义律制模板库（数据层）测试。

判据：
1. CRUD 往返逐位相等（空库/损坏索引自愈、add/update/import/export/delete）
2. 冻结面与运行记录面（内置8/论文6、template_record 稳定、ruler_entries）
3. 非法输入有齿 + 变异自检（validate_cents、同名冲突、update全None）
"""

import pytest


class TestCrudRoundtrip:
    """判据1：CRUD 往返逐位相等。"""

    def test_empty_library_returns_list(self):
        from acouscope.analysis.tunings import user_templates

        # 空库无 index.json
        assert user_templates.load_index() == {"version": 1, "templates": []}
        assert user_templates.list_user_templates() == []

    def test_corrupted_index_self_heals(self):
        from acouscope.analysis.tunings import user_templates

        # 写损坏 JSON
        lib = user_templates.library_dir()
        lib.mkdir(parents=True, exist_ok=True)
        idx = user_templates.index_path()
        idx.write_text("not json {", encoding="utf-8")

        # 应自愈返回空索引，不抛
        assert user_templates.load_index() == {"version": 1, "templates": []}

    def test_add_and_parse_back_exact(self):
        from acouscope.analysis.tunings import user_templates
        from acouscope.analysis.tunings.scl import parse_scl_file

        cents = [150.0, 350.0, 700.0, 1200.0]
        entry = user_templates.add_user_template("五音示例", "自建（测试）", cents)
        assert entry["name"] == "五音示例"

        # 文件已落盘
        scl_path = user_templates.library_dir() / entry["file"]
        assert scl_path.is_file()

        # 回读音分逐值 == 输入
        scale = parse_scl_file(scl_path)
        read_back = list(scale.cents())
        for a, b in zip(read_back, cents):
            assert a == b

    def test_update_changes_cents_file_stable(self):
        from acouscope.analysis.tunings import user_templates
        from acouscope.analysis.tunings.scl import parse_scl_file

        cents1 = [150.0, 350.0, 700.0, 1200.0]
        entry = user_templates.add_user_template("示例改名", "旧来源", cents1)

        # update 只改 cents
        new_cents = [200.0, 400.0, 800.0, 1200.0]
        updated = user_templates.update_user_template(
            "示例改名", cents=new_cents, source="新来源"
        )

        # spec 不变（文件名稳定）
        spec = user_templates.user_spec("示例改名")
        assert spec.startswith("custom:")

        # 回读逐值 == 新值
        scl_path = user_templates.library_dir() / entry["file"]
        scale = parse_scl_file(scl_path)
        read_back = list(scale.cents())
        for a, b in zip(read_back, new_cents):
            assert a == b

    def test_import_export_roundtrip(self):
        from acouscope.analysis.tunings import user_templates
        from acouscope.analysis.tunings.scl import parse_scl_file, save_scl
        from acouscope.analysis.tunings.tuning_system import TuningSystem

        # 先写一个 .scl
        cents = [100.0, 250.0, 450.0, 617.48, 902.3, 1200.0]
        t = TuningSystem.from_cents(name="导入测试", source="源文件", cents=cents)
        tmp_scl = user_templates.library_dir() / "import_me.scl"
        save_scl(t, tmp_scl)

        # 导入为用户模板
        entry = user_templates.import_user_scl(tmp_scl, name="从文件导入")
        assert entry["name"] == "从文件导入"

        # 导出到新路径
        out = user_templates.library_dir() / "exported.scl"
        user_templates.export_user_scl("从文件导入", out)

        # 回读逐值 ==
        scale = parse_scl_file(out)
        read_back = list(scale.cents())
        for a, b in zip(read_back, cents):
            assert a == b

    def test_delete_removes_file_and_index(self):
        from acouscope.analysis.tunings import user_templates

        cents = [200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0]
        entry = user_templates.add_user_template("待删模板", "将删除", cents)

        assert user_templates.get_entry("待删模板") is not None
        ok = user_templates.delete_user_template("待删模板")
        assert ok is True

        # 文件与索引条目均消失
        scl_path = user_templates.library_dir() / entry["file"]
        assert not scl_path.is_file()
        assert user_templates.get_entry("待删模板") is None

    def test_delete_missing_returns_false(self):
        from acouscope.analysis.tunings import user_templates

        assert user_templates.delete_user_template("不存在的模板") is False


class TestFrozenSurface:
    """判据2：冻结面与运行记录面。"""

    def test_builtin_count_and_keys(self):
        from acouscope.analysis.tunings.templates import (
            PAPER_TEMPLATE_KEYS,
            TEMPLATES,
            list_templates,
        )

        # 内置 8 项顺序不变
        assert len(TEMPLATES) == 8
        assert len(list_templates()) == 8
        assert list_templates() == [
            "12tet",
            "just_major",
            "pythagorean_diatonic",
            "quarter_comma_meantone",
            "chinese_sanfen_sunyi_12",
            "qin_lu",
            "indian_22_shruti",
            "arabic_24_tone",
        ]

        # 论文 6 项
        assert len(PAPER_TEMPLATE_KEYS) == 6

    def test_template_record_stable_for_custom(self):
        from acouscope.analysis import readout
        from acouscope.analysis.tunings import user_templates

        cents = [150.0, 350.0, 700.0, 1200.0]
        user_templates.add_user_template("稳定测试", "来源A", cents)

        spec = user_templates.user_spec("稳定测试")
        rec1 = readout.template_record(spec)
        rec2 = readout.template_record(spec)

        # 连续两次逐键 ==
        for key in rec1:
            assert rec1[key] == rec2[key], f"{key} 不稳定"

        # 自定义标识
        assert rec1["template_key"].startswith("custom:")
        assert rec1.get("template_custom") is True
        sha = rec1["template_sha256"]
        assert len(sha) == 64
        int(sha, 16)  # 验证是 hex

    def test_get_user_tuning_source_fidelity(self):
        from acouscope.analysis.tunings import user_templates

        cents = [100.0, 250.0, 450.0, 617.48, 902.3, 1200.0]
        user_templates.add_user_template("来源保真", "自建（测试）", cents)

        t = user_templates.get_user_tuning("来源保真")
        assert t.name == "来源保真"
        assert t.source == "自建（测试）"

    def test_ruler_entries_combines_builtin_and_user(self):
        from acouscope.analysis.tunings import user_templates

        # 加一个用户模板
        cents = [100.0, 250.0, 450.0, 617.48, 902.3, 1200.0]
        user_templates.add_user_template("尺上用户项", "来源B", cents)

        entries = user_templates.ruler_entries()

        # 8 内置 + 1 用户
        assert len(entries) == 9

        # 末项是用户模板
        last_name, last_spec = entries[-1]
        assert last_name == "尺上用户项"
        assert last_spec.startswith("custom:")


class TestValidationAndErrors:
    """判据3：非法输入有齿。"""

    def test_empty_name_raises(self):
        from acouscope.analysis.tunings import user_templates

        with pytest.raises(ValueError, match="名称"):
            user_templates.add_user_template("  ", "来源", [100.0, 200.0])

    def test_empty_source_raises(self):
        from acouscope.analysis.tunings import user_templates

        with pytest.raises(ValueError, match="来源"):
            user_templates.add_user_template("模板", "  ", [100.0, 200.0])

    def test_non_increasing_cents_raises(self):
        from acouscope.analysis.tunings import user_templates

        # 非严格递增：相邻相等值也须报错
        with pytest.raises(ValueError, match="递增"):
            user_templates.add_user_template("非严格递增", "来源", [100.0, 200.0, 200.0])

    def test_non_finite_cents_raises(self):
        from acouscope.analysis.tunings import user_templates

        with pytest.raises(ValueError, match="有限"):
            user_templates.add_user_template("非有限", "来源", [float("nan")])

    def test_negative_first_cents_raises(self):
        from acouscope.analysis.tunings import user_templates

        with pytest.raises(ValueError, match="首值"):
            user_templates.add_user_template("负首值", "来源", [-50.0, 100.0])

    def test_duplicate_add_raises(self):
        from acouscope.analysis.tunings import user_templates

        user_templates.add_user_template("重复名", "来源1", [100.0, 200.0])
        with pytest.raises(ValueError, match="已存在"):
            user_templates.add_user_template("重复名", "来源2", [150.0, 300.0])

    def test_update_all_none_raises(self):
        from acouscope.analysis.tunings import user_templates

        user_templates.add_user_template("需更新", "来源", [100.0, 200.0])
        with pytest.raises(ValueError, match="至少"):
            user_templates.update_user_template("需更新", source=None, cents=None)

    def test_update_missing_raises_keyerror(self):
        from acouscope.analysis.tunings import user_templates

        with pytest.raises(KeyError):
            user_templates.update_user_template("不存在", source="新来源")

    def test_list_not_polluted_after_failed_add(self):
        from acouscope.analysis.tunings import user_templates

        before = [e["name"] for e in user_templates.list_user_templates()]
        try:
            user_templates.add_user_template("失败添加", "来源", [200.0, 150.0])
        except ValueError:
            pass

        after = [e["name"] for e in user_templates.list_user_templates()]
        assert before == after

    def test_import_bad_scl_raises_and_library_unpolluted(self):
        from acouscope.analysis.tunings import user_templates

        lib = user_templates.library_dir()
        lib.mkdir(parents=True, exist_ok=True)

        # 坏 .scl：非数字比值行
        bad_scl = lib / "bad.scl"
        bad_scl.write_text("12\nnot a number\n", encoding="utf-8")

        before = [e["name"] for e in user_templates.list_user_templates()]
        with pytest.raises(ValueError):
            user_templates.import_user_scl(bad_scl)
        after = [e["name"] for e in user_templates.list_user_templates()]
        assert before == after

    def test_import_negative_ratio_scl_raises_and_library_unpolluted(self):
        from acouscope.analysis.tunings import user_templates

        lib = user_templates.library_dir()
        lib.mkdir(parents=True, exist_ok=True)

        # 负比值 .scl（parse_scl_file 应抛）
        neg_scl = lib / "negative.scl"
        neg_scl.write_text("5\n-\n2\n3\n4\n5\n6\n", encoding="utf-8")

        before = [e["name"] for e in user_templates.list_user_templates()]
        with pytest.raises(ValueError):
            user_templates.import_user_scl(neg_scl)
        after = [e["name"] for e in user_templates.list_user_templates()]
        assert before == after

    def test_unicode_bom_corrupt_index_self_heals(self):
        from acouscope.analysis.tunings import user_templates

        lib = user_templates.library_dir()
        lib.mkdir(parents=True, exist_ok=True)
        idx = user_templates.index_path()
        idx.write_bytes(b"\xff\xfe\x00")

        # 非 UTF-8 字节应自愈回空索引，不抛
        assert user_templates.load_index() == {"version": 1, "templates": []}

    def test_two_chinese_named_templates_coexist(self):
        """判据①：两个不同中文名模板可共存且逐值 ==；删其一不影响另一。"""
        from acouscope.analysis.tunings import user_templates
        from acouscope.analysis.tunings.scl import parse_scl_file

        cents_a = [150.0, 350.0, 700.0, 1200.0]
        cents_b = [200.0, 400.0, 800.0, 1200.0]

        entry_a = user_templates.add_user_template("宫商角徵羽", "五音律", cents_a)
        entry_b = user_templates.add_user_template("七声音阶试", "七声律", cents_b)

        # 恰 2 项
        listed = user_templates.list_user_templates()
        assert len(listed) == 2

        # slug（不含哈希）相同但文件名不同
        assert entry_a["file"] != entry_b["file"]

        # 各自 parse_scl_file 回读逐值 ==
        lib = user_templates.library_dir()
        for entry, expected_cents in [(entry_a, cents_a), (entry_b, cents_b)]:
            scale = parse_scl_file(lib / entry["file"])
            read_back = list(scale.cents())
            for a, b in zip(read_back, expected_cents):
                assert a == b

        # 同名重复 add 仍抛 ValueError
        with pytest.raises(ValueError, match="已存在"):
            user_templates.add_user_template("宫商角徵羽", "重复", cents_a)

        # update 前后 user_spec 不变
        spec_before = user_templates.user_spec("宫商角徵羽")
        updated = user_templates.update_user_template(
            "宫商角徵羽", cents=[160.0, 350.0, 700.0, 1200.0]
        )
        spec_after = user_templates.user_spec("宫商角徵羽")
        assert spec_before == spec_after

        # 删其一不影响另一
        user_templates.delete_user_template("宫商角徵羽")
        remaining = [e["name"] for e in user_templates.list_user_templates()]
        assert "宫商角徵羽" not in remaining
        assert "七声音阶试" in remaining

    def test_ruler_entries_builtin_prefix_matches_templates(self):
        from acouscope.analysis.tunings import user_templates
        from acouscope.analysis.tunings.templates import get_template, list_templates

        entries = user_templates.ruler_entries()
        expected_prefix = [(get_template(k).name, k) for k in list_templates()]
        assert entries[:8] == expected_prefix
