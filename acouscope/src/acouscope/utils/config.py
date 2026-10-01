# SPDX-License-Identifier: GPL-3.0-only
"""配置与工具函数。"""

import os
import json
import tempfile
from pathlib import Path
from dataclasses import dataclass, asdict, field


def _is_writable_dir(path: Path) -> bool:
    """探测目录是否可创建且可写（权限/沙箱拒绝时返回 False）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".acouscope_write_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


_RESOLVED_DIRS: dict[str, Path] = {}


def _candidate_dirs(primary: Path) -> list[Path]:
    """同用途候选目录（按优先级）：系统标准位置 → 逐级回退。"""
    project_root = Path(__file__).resolve().parents[3]
    return [
        primary,
        Path.home() / ".acouscope",
        project_root / ".acouscope_local",
        Path(tempfile.gettempdir()) / "acouscope",
    ]


def _resolve_dir(key: str, primary: Path) -> Path:
    """解析可写目录：首选系统标准位置，不可写时逐级回退。"""
    if key in _RESOLVED_DIRS:
        return _RESOLVED_DIRS[key]

    for cand in _candidate_dirs(primary):
        if _is_writable_dir(cand):
            _RESOLVED_DIRS[key] = cand
            return cand

    _RESOLVED_DIRS[key] = primary
    return primary


def data_dir_candidates() -> list[Path]:
    """数据目录的全部候选位置（供写入失败时逐个重试）。"""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return _candidate_dirs(base / "AcouScope")


def config_dir_candidates() -> list[Path]:
    """配置目录的全部候选位置（供写入失败时逐个重试）。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return _candidate_dirs(base / "AcouScope")


def get_config_dir() -> Path:
    """获取用户配置目录（不可写时自动回退）。

    Returns:
        配置目录路径
    """
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.sys.platform == "darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return _resolve_dir("config", base / "AcouScope")


def get_data_dir() -> Path:
    """获取用户数据目录（不可写时自动回退）。

    Returns:
        数据目录路径
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return _resolve_dir("data", base / "AcouScope")


def _settings_candidates(primary: Path) -> list[Path]:
    """settings.json 的候选位置（首选在前，随后各回退目录）。"""
    paths = [primary]
    for d in config_dir_candidates():
        p = d / "settings.json"
        if p not in paths:
            paths.append(p)
    return paths


def _clamp_int_setting(value, default: int, low: int, high: int) -> int:
    """整数设置钳位：非法/越界一律回退 default（T-928 与 reference_hz 同范式）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low or number > high:
        return default
    return number


@dataclass
class Settings:
    """应用设置。

    可持久化的用户偏好设置。
    """

    # 界面
    language: str = "zh_CN"  # zh_CN / en_US
    theme: str = "dark"  # V099_TOKENS_V1：暗色优先默认（浅色 9 套仍可切换）
    # T-1001：图标风格（脚本派生三套 macos/win/mint + generic 基准兜底）；
    # 默认 generic = 既有行为不变；非法值由 theme.icon_style() 读数时回落。
    icon_style: str = "generic"
    window_width: int = 1200
    window_height: int = 800

    # 音频
    default_sample_rate: int = 44100
    default_channels: int = 1
    audio_buffer_size: int = 1024

    # 分析
    default_fft_size: int = 4096
    default_window: str = "hann"
    default_overlap: float = 0.5

    # 出图
    default_dpi: int = 300
    default_format: str = "svg"
    default_journal_template: str = "default"
    chart_font: str = "auto"  # 旧字段（兼容）：新代码使用下面两项
    chart_font_latin: str = "auto"  # 图表西文/数字字体（"auto" = 自动）
    pitch_snap_mode: str = "off"  # 音高网格吸附模式（T-802：off/12tet），表现层增值，原始 f0 不受影响
    chart_font_cjk: str = "auto"  # 图表中文字体（"auto" = 自动）
    # T-1044：图表设计器全局默认（P1 第②层「全局默认」；项目级留 P3 = T-1046）
    chart_designer_palette: str = "default"  # 数据序列配色（UI 四档见 ui/widgets/chart_designer.py）
    chart_designer_grid: bool = True  # 图表网格显隐
    chart_designer_figsize_w: float = 0.0  # 画幅宽（英寸）；0.0 = 用期刊模板值
    chart_designer_figsize_h: float = 0.0  # 画幅高（英寸）；0.0 = 用期刊模板值
    # T-1046 P3：图表样式预设（全局层；键 = 预设名，值 = params() 快照）。缺键兜底空 dict。
    chart_style_presets: dict[str, dict] = field(default_factory=dict)
    # T-921：A4 参考频率（Hz），影响音分/音名换算；默认 440.0（行为与改动前一致）
    reference_hz: float = 440.0
    # T-1005：多轨差异报警阈值（cents）——轨间差异**报警线**，非测量精度承诺；
    # 可配置范围 10–200（越界回退 50），权威常量见 multitrack/compare_diff.py。
    multitrack_diff_threshold_cents: float = 50.0

    # T-928：非模态任务进度中心——并发上限（1–4，越界回退 1）与排队上限
    # （1–256，越界回退 32）。权威常量在 ui/widgets/task_center.py 模块级，
    # 本处默认值须与之逐值一致（测试断言两处口径一致）。
    task_center_max_concurrency: int = 1
    task_center_queue_limit: int = 32

    # T-929：内存防护（memguard）——低内存预检阈值 / 危急阈值（MB）与模型闲置
    # 卸载分钟数；非法或越界一律回退默认。默认值与 system/memguard.py 模块级
    # 权威常量逐值一致（测试断言两处口径）。
    memguard_low_threshold_mb: int = 512
    memguard_critical_threshold_mb: int = 200
    memguard_model_idle_minutes: int = 10

    # 性能
    use_numba: bool = True
    max_memory_mb: int = 1024

    _filepath: Path = field(default_factory=Path, init=False, repr=False)

    @classmethod
    def load(cls, filepath: Path | None = None) -> "Settings":
        """从文件加载设置。

        Args:
            filepath: 设置文件路径，默认使用配置目录下的 settings.json

        Returns:
            Settings 实例
        """
        explicit = filepath is not None
        if filepath is None:
            filepath = get_config_dir() / "settings.json"

        settings = cls()
        settings._filepath = filepath

        # 显式路径只读该文件；默认路径按候选顺序找第一个可读的
        paths = [filepath] if explicit else _settings_candidates(filepath)
        for path in paths:
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(settings, key):
                        setattr(settings, key, value)
                # 旧版单一 chart_font 迁移到西文字体字段
                if (
                    settings.chart_font not in ("", "auto")
                    and settings.chart_font_latin == "auto"
                ):
                    settings.chart_font_latin = settings.chart_font
                settings._filepath = path
                break
            except (json.JSONDecodeError, IOError):
                continue  # 文件损坏/不可读时尝试下一候选

        # T-921：A4 参考频率非法/越界（400–480）一律回退 440.0
        try:
            reference = float(settings.reference_hz)
        except (TypeError, ValueError):
            reference = 440.0
        if not (400.0 <= reference <= 480.0):
            reference = 440.0
        settings.reference_hz = reference

        # T-1005：多轨差异报警阈值非法/越界（10–200）一律回退 50.0（报警线，非精度承诺）
        try:
            diff_threshold = float(settings.multitrack_diff_threshold_cents)
        except (TypeError, ValueError):
            diff_threshold = 50.0
        if not (10.0 <= diff_threshold <= 200.0):
            diff_threshold = 50.0
        settings.multitrack_diff_threshold_cents = diff_threshold

        # T-928：任务进度中心并发/排队上限非法或越界一律回退默认
        # （1–4 / 1–256；默认值与 task_center.py 模块级权威常量逐值一致）
        settings.task_center_max_concurrency = _clamp_int_setting(
            settings.task_center_max_concurrency, 1, 1, 4
        )
        settings.task_center_queue_limit = _clamp_int_setting(
            settings.task_center_queue_limit, 32, 1, 256
        )

        # T-929：内存防护阈值 / 模型闲置分钟非法或越界一律回退默认
        # （64–8192 / 64–8192 / 1–240；默认值与 system/memguard.py 权威常量逐值一致）
        settings.memguard_low_threshold_mb = _clamp_int_setting(
            settings.memguard_low_threshold_mb, 512, 64, 8192
        )
        settings.memguard_critical_threshold_mb = _clamp_int_setting(
            settings.memguard_critical_threshold_mb, 200, 64, 8192
        )
        settings.memguard_model_idle_minutes = _clamp_int_setting(
            settings.memguard_model_idle_minutes, 10, 1, 240
        )

        # T-1044：图表设计器全局默认——画幅非法/越界（宽 2.0–12.0 / 高 1.5–10.0 英寸）
        # 一律回退 0.0（0.0 = 用期刊模板值）；配色非字符串/空串回退 "default"
        # （未知名由 mpl_style.palette_cycle 记 warning 并降级，不在此抛异常）。
        for _field, _low, _high in (
            ("chart_designer_figsize_w", 2.0, 12.0),
            ("chart_designer_figsize_h", 1.5, 10.0),
        ):
            try:
                _fig = float(getattr(settings, _field))
            except (TypeError, ValueError):
                _fig = 0.0
            if _fig != 0.0 and not (_low <= _fig <= _high):
                _fig = 0.0
            setattr(settings, _field, _fig)
        _palette = getattr(settings, "chart_designer_palette", "default")
        settings.chart_designer_palette = (
            _palette.strip() if isinstance(_palette, str) and _palette.strip() else "default"
        )
        settings.chart_designer_grid = bool(getattr(settings, "chart_designer_grid", True))

        return settings

    def save(self, filepath: Path | None = None) -> None:
        """保存设置到文件（首选位置不可写时自动回退候选目录）。

        Args:
            filepath: 保存路径，默认使用加载时的路径
        """
        explicit = filepath is not None
        if filepath is None:
            filepath = getattr(self, "_filepath", None)
            if filepath is None:
                filepath = get_config_dir() / "settings.json"

        data = {
            k: v
            for k, v in asdict(self).items()
            if not k.startswith("_")
        }

        paths = [filepath] if explicit else _settings_candidates(filepath)
        last_err: Exception | None = None
        for path in paths:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._filepath = path
                return
            except OSError as e:
                last_err = e
                continue
        if last_err is not None:
            raise last_err
