# SPDX-License-Identifier: GPL-3.0-only
"""项目管理模块。"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

from acouscope.analysis.pitch_grid import PitchGridModel
from acouscope.utils.log import get_logger

_log = get_logger("app.project")


@dataclass
class ProjectFile:
    """项目中的音频文件条目。"""

    path: str
    label: str = ""
    analysis_results: Dict[str, Any] = field(default_factory=dict)
    # 文件级元数据（T-907）：键 = 我方字段名（同 annotation/metadata.py FIELD_TERMS.key，
    # 如 Title/Creator/SamplingRate…），值统一 str；可选控制键 "_standard"
    # 记录用户所选著录标准（DAT63 / GBT31219.4 / custom），数据层不校验取值。
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    """项目数据结构。"""

    name: str = "未命名项目"
    files: List[ProjectFile] = field(default_factory=list)
    annotations: List[Dict] = field(default_factory=list)
    presets: Dict[str, Dict] = field(default_factory=dict)
    # "0.2"（T-907）：新增 ProjectFile.metadata；旧 "0.1" 文件 load 时原样保留不报错。
    # 注意：项目级元数据无消费方，本版本不加 Project.metadata（见 T-907 任务书）。
    version: str = "0.2"


def _serialize_analysis_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """分析结果序列化（浅拷贝，T-804）。

    若含键 "pitch_grid" 且值为 PitchGridModel 实例，替换为 .to_dict() 的
    JSON 安全 dict；其余键原样保留。
    """
    out = dict(results)
    value = out.get("pitch_grid")
    if isinstance(value, PitchGridModel):
        out["pitch_grid"] = value.to_dict()
    return out


def _deserialize_analysis_results(
    results: Dict[str, Any], source: str = ""
) -> Dict[str, Any]:
    """分析结果反序列化（浅拷贝，T-804）。

    若 "pitch_grid" 为 dict，尝试 PitchGridModel.from_dict(...) 还原为模型；
    失败（Exception）保留原 dict 不抛出（遗留/损坏文件零崩溃）。

    参数:
        source: 项目文件路径（仅用于失败日志定位，T-1074 G3④）。
    """
    out = dict(results)
    value = out.get("pitch_grid")
    if isinstance(value, dict):
        try:
            out["pitch_grid"] = PitchGridModel.from_dict(value)
        except Exception as e:
            # T-1074 G3④（承 T72-09）：静默降级补日志痕（带来源路径）；
            # 返回值语义不变——仍保留原 dict、不外抛（遗留/损坏文件零崩溃）。
            _log.warning(
                "pitch_grid 反序列化失败(%s)，保留原 dict: %s",
                source or "未知来源",
                e,
            )
    return out


def _load_metadata(raw: Any) -> Dict[str, str]:
    """文件级元数据反序列化（T-907，向后兼容硬要求）。

    旧格式无 metadata 键 / null / 非 dict → 空 dict（零崩溃、零告警）；
    键值统一字符串化，保持 {str: str} 不变式（非字符串值容忍不抛）。
    """
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


class ProjectManager:
    """项目管理器。

    负责项目的创建、保存、加载。
    """

    FILE_EXTENSION = ".acouproj"

    def __init__(self):
        self._current_project: Project = Project()
        self._filepath: Path | None = None

    @property
    def current(self) -> Project:
        """当前项目。"""
        return self._current_project

    @property
    def filepath(self) -> Path | None:
        """项目文件路径。"""
        return self._filepath

    def new(self, name: str = "未命名项目") -> Project:
        """创建新项目。

        Args:
            name: 项目名称

        Returns:
            新的 Project 对象
        """
        self._current_project = Project(name=name)
        self._filepath = None
        return self._current_project

    def save(self, filepath: str | Path | None = None) -> None:
        """保存项目。

        Args:
            filepath: 保存路径，为 None 时使用当前路径
        """
        if filepath is not None:
            self._filepath = Path(filepath)

        if self._filepath is None:
            raise ValueError("未指定保存路径")

        data = {
            "name": self._current_project.name,
            "version": self._current_project.version,
            "files": [
                {
                    "path": f.path,
                    "label": f.label,
                    "analysis_results": _serialize_analysis_results(f.analysis_results),
                    "metadata": f.metadata,
                }
                for f in self._current_project.files
            ],
            "annotations": self._current_project.annotations,
            "presets": self._current_project.presets,
        }

        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self._filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def save_to(self, filepath: str | Path) -> None:
        """写盘到指定路径，但不改变当前项目路径（T-322 autosave 快照用）。

        自动保存未命名项目时不得把项目"命名"到快照文件，否则后续手动保存
        会默认落到快照目录；保存后还原原 filepath 语义。
        """
        prev = self._filepath
        try:
            self.save(filepath)
        finally:
            self._filepath = prev

    def load(self, filepath: str | Path) -> Project:
        """加载项目。

        Args:
            filepath: 项目文件路径

        Returns:
            加载的 Project 对象
        """
        filepath = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._current_project = Project(
            name=data.get("name", "未命名项目"),
            files=[
                ProjectFile(
                    path=f["path"],
                    label=f.get("label", ""),
                    analysis_results=_deserialize_analysis_results(
                        f.get("analysis_results", {}), source=str(filepath)
                    ),
                    metadata=_load_metadata(f.get("metadata")),
                )
                for f in data.get("files", [])
            ],
            annotations=data.get("annotations", []),
            presets=data.get("presets", {}),
            # 旧 "0.1" 文件原样保留不报错；缺键兜底 "0.2"（T-907）。
            version=data.get("version", "0.2"),
        )
        self._filepath = filepath

        return self._current_project

    def add_file(self, filepath: str | Path, label: str = "") -> ProjectFile:
        """向项目添加音频文件。

        Args:
            filepath: 音频文件路径
            label: 文件标签

        Returns:
            新增的 ProjectFile 对象
        """
        pf = ProjectFile(path=str(filepath), label=label)
        self._current_project.files.append(pf)
        return pf

    def get_file(self, filepath: str | Path) -> ProjectFile | None:
        """按路径精确匹配查询文件条目（T-907）。

        读/写 metadata 的统一入口，收敛 controller 散排 next(...) 模式。

        Args:
            filepath: 音频文件路径

        Returns:
            匹配的 ProjectFile；不存在返回 None（不抛）。
        """
        target = str(filepath)
        for pf in self._current_project.files:
            if pf.path == target:
                return pf
        return None

    def remove_file(self, filepath: str | Path) -> bool:
        """按路径精确匹配移除文件条目（T-907）。

        Args:
            filepath: 音频文件路径

        Returns:
            命中移除返回 True；未命中返回 False（幂等、不抛）。
        """
        target = str(filepath)
        files = self._current_project.files
        for i, pf in enumerate(files):
            if pf.path == target:
                del files[i]
                return True
        return False
