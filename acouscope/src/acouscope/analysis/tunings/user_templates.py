# SPDX-License-Identifier: GPL-3.0-only
"""用户自定义律制模板库（数据层，零 Qt 依赖）。

纯 Python CRUD 操作：索引 `index.json` + `.scl` 文件对持久化；
提供 `ruler_entries()` 统一数据源（内置 + 用户），供 P3 GUI 入口使用。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

# 运行时调用（非顶层绑定），保证 conftest autouse monkeypatch 能命中
from acouscope.utils import config as _config


def library_dir() -> Path:
    """用户律制模板库目录（随 `get_data_dir()` 变化）。"""
    return Path(_config.get_data_dir()) / "tuning_templates"


INDEX_FILENAME = "index.json"
INDEX_VERSION = 1


def index_path() -> Path:
    return library_dir() / INDEX_FILENAME


def _slug(name: str) -> str:
    """文件名片段：仅保留 ASCII 字母数字、`-`、`_`；其余转 `_`，折叠连续 `_`。"""
    kept = "".join(
        ch if (ch.isalnum() and ch.isascii()) or ch in "-_" else "_" for ch in str(name)
    ).strip("_")
    while "__" in kept:
        kept = kept.replace("__", "_")
    return kept or "scale"


def load_index() -> dict:
    """加载索引；缺失/损坏/版本不对/条目非法 ⇒ 返回空索引，绝不抛异常。"""
    path = index_path()
    if not path.is_file():
        return {"version": INDEX_VERSION, "templates": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {"version": INDEX_VERSION, "templates": []}
    if not isinstance(raw, dict):
        return {"version": INDEX_VERSION, "templates": []}
    if raw.get("version") != INDEX_VERSION:
        return {"version": INDEX_VERSION, "templates": []}
    templates = raw.get("templates", [])
    if not isinstance(templates, list):
        return {"version": INDEX_VERSION, "templates": []}
    # 逐条校验，非法条目丢弃
    good: list[dict] = []
    for entry in templates:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        source = entry.get("source", "")
        file = entry.get("file", "")
        if not (isinstance(name, str) and name):
            continue
        if not (isinstance(source, str) and source):
            continue
        if not (isinstance(file, str) and file):
            continue
        # 防目录穿越：文件名内不含 /、\、..
        if "/" in file or "\\" in file or ".." in file:
            continue
        good.append({"name": name, "source": source, "file": file})
    return {"version": INDEX_VERSION, "templates": good}


def save_index(index: dict) -> None:
    """原子写索引：tmp 文件 + os.replace。"""
    lib = library_dir()
    lib.mkdir(parents=True, exist_ok=True)
    path = index_path()
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def list_user_templates() -> list[dict]:
    """列出全部用户律制模板（按 name 排序）；索引有条目但 .scl 缺失则跳过。"""
    index = load_index()
    lib = library_dir()
    result: list[dict] = []
    for entry in index.get("templates", []):
        path = lib / entry["file"]
        if not path.is_file():
            continue  # 自愈：跳过缺失文件
        result.append({
            "name": entry["name"],
            "source": entry["source"],
            "file": entry["file"],
            "path": str(path.absolute()),
            "spec": f"custom:{path}",
        })
    result.sort(key=lambda e: e["name"])
    return result


def get_entry(name: str) -> dict | None:
    """按名查索引条目（不校验文件存在）。"""
    for entry in load_index().get("templates", []):
        if entry["name"] == name:
            return entry
    return None


def user_spec(name: str) -> str:
    """用户模板的 custom: spec；不存在则抛 KeyError。"""
    entry = get_entry(name)
    if entry is None:
        raise KeyError(f"用户律制模板不存在：{name!r}")
    lib = library_dir()
    path = lib / entry["file"]
    return f"custom:{path}"


def validate_cents(cents) -> None:
    """校验音分序列：至少 1 个值、全部有限、首值 > 0、严格递增。"""
    if not isinstance(cents, (list, tuple)):
        raise ValueError("cents 必须是 list 或 tuple")
    if len(cents) < 1:
        raise ValueError("音分序列至少需含一个音级")
    import math
    for i, v in enumerate(cents):
        fv = float(v)
        if not math.isfinite(fv):
            raise ValueError(f"音分序列第 {i} 个值非有限数：{v!r}")
        if i == 0 and fv <= 0:
            raise ValueError(f"音分序列首值必须 > 0，实际 {fv}")
        if i > 0:
            prev = float(cents[i - 1])
            if fv <= prev:
                raise ValueError(f"音分序列非严格递增：第 {i} 个值 {fv} ≤ 前值 {prev}")


def add_user_template(name: str, source: str, cents) -> dict:
    """新增用户律制模板；同名或 slug 冲突显式抛 ValueError。"""
    name = str(name).strip()
    source = str(source).strip()
    if not name:
        raise ValueError("模板名称不能为空")
    if not source:
        raise ValueError("来源不能为空")
    validate_cents(cents)

    # 同名已存在检查
    if get_entry(name) is not None:
        raise ValueError(f"用户律制模板已存在：{name!r}")

    # 文件名生成：slug + sha256(name)[:8] 后缀，同名稳定、异名不撞
    slug = _slug(name)
    name_hash = hashlib.sha256(name.strip().encode("utf-8")).hexdigest()[:8]
    lib = library_dir()
    scl_path = lib / f"{slug}-{name_hash}.scl"

    # 文件冲突检查（显式报错，禁静默覆盖）
    if scl_path.is_file():
        raise ValueError(f"文件名冲突（{scl_path.name}）：{name!r}")

    # 构造与写出
    from acouscope.analysis.tunings.scl import save_scl
    from acouscope.analysis.tunings.tuning_system import TuningSystem

    tuning = TuningSystem.from_cents(name=name, source=source, cents=list(cents))
    save_scl(tuning, scl_path)

    # 追加索引
    index = load_index()
    entry = {"name": name, "source": source, "file": scl_path.name}
    index["templates"].append(entry)
    save_index(index)
    return entry


def update_user_template(name: str, *, source: str | None = None, cents=None) -> dict:
    """更新用户律制模板（文件名/slug 保持不变）；全 None 抛 ValueError。"""
    entry = get_entry(name)
    if entry is None:
        raise KeyError(f"用户律制模板不存在：{name!r}")
    if source is None and cents is None:
        raise ValueError("update_user_template 至少需提供 source 或 cents")

    lib = library_dir()
    scl_path = lib / entry["file"]

    if cents is not None:
        validate_cents(cents)

    # 构造新 tuning（取现有 name/source，按传入更新）
    from acouscope.analysis.tunings.scl import save_scl
    from acouscope.analysis.tunings.tuning_system import TuningSystem

    cur_name = entry["name"]
    cur_source = source if source is not None else entry["source"]
    if cents is not None:
        tuning = TuningSystem.from_cents(name=cur_name, source=cur_source, cents=list(cents))
    else:
        # 只更新 source：回读文件构造新对象
        from acouscope.analysis.tunings.templates import load_scl
        old = load_scl(scl_path)
        tuning = TuningSystem.from_cents(name=cur_name, source=cur_source, cents=list(old.degrees[1:]))

    save_scl(tuning, scl_path)

    # 更新索引
    index = load_index()
    for item in index["templates"]:
        if item["name"] == name:
            item["source"] = cur_source
            break
    save_index(index)

    return {"name": cur_name, "source": cur_source, "file": entry["file"]}


def delete_user_template(name: str) -> bool:
    """删除用户律制模板（.scl + 索引条目）；不存在返回 False。"""
    entry = get_entry(name)
    if entry is None:
        return False

    lib = library_dir()
    scl_path = lib / entry["file"]
    scl_path.unlink(missing_ok=True)

    index = load_index()
    new_templates = [e for e in index["templates"] if e["name"] != name]
    index["templates"] = new_templates
    save_index(index)
    return True


def import_user_scl(path, *, name: str | None = None, source: str | None = None) -> dict:
    """从 .scl 文件导入为用户律制模板。"""
    from acouscope.analysis.tunings.scl import parse_scl_file

    file_path = Path(path)
    scale = parse_scl_file(file_path)
    cents = list(scale.cents())
    template_name = name or scale.description or file_path.stem
    template_source = source or f"用户导入的 .scl 文件：{file_path.name}"
    return add_user_template(template_name, template_source, cents)


def export_user_scl(name: str, path) -> Path:
    """导出用户律制模板为 .scl 文件。"""
    from acouscope.analysis.tunings.scl import save_scl

    tuning = get_user_tuning(name)
    return save_scl(tuning, path)


def get_user_tuning(name: str) -> "TuningSystem":
    """按名取 TuningSystem 对象（用索引里的 name/source）。"""
    from acouscope.analysis.tunings.templates import load_scl

    entry = get_entry(name)
    if entry is None:
        raise KeyError(f"用户律制模板不存在：{name!r}")
    lib = library_dir()
    path = lib / entry["file"]
    return load_scl(path, name=entry["name"], source=entry["source"])


def ruler_entries() -> list[tuple[str, str]]:
    """律制标尺选择器数据源：内置 8 项 + 用户 N 项。"""
    from acouscope.analysis.tunings.templates import get_template, list_templates

    result: list[tuple[str, str]] = []
    for key in list_templates():
        result.append((get_template(key).name, key))
    for entry in list_user_templates():
        result.append((entry["name"], entry["spec"]))
    return result
