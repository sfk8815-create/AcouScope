"""C6 测试计数脚本（按模块拆分）。
输出: .pi/metrics/C6_test_counts.json
诚实原则：直接调用 pytest --collect-only 或统计 pytest 收集后的 items，若失败则回退为按文件名与 def test_ 的 grep 计数（并在 scope 字段注明）。
"""
import json, os, sys, subprocess, re, collections

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/.."
TESTS_DIR = os.path.join(ROOT, "acouscope", "tests")

# 方法1: pytest collect 真实计数（优先）
def collect_via_pytest():
    py = os.path.join(ROOT, "acouscope", ".venv", "bin", "python")
    if not os.path.exists(py):
        return None, f"venv missing at {py}"
    try:
        r = subprocess.run(
            [py, "-m", "pytest", TESTS_DIR, "--collect-only", "-q", "--no-header"],
            cwd=os.path.join(ROOT, "acouscope"),
            capture_output=True, text=True, timeout=180, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        )
        # 收集最后一行形如 "N tests collected"
        tail = (r.stdout + r.stderr).strip().splitlines()[-5:]
        total = None
        for line in tail:
            m = re.search(r"(\d+) test[s]? collected", line)
            if m:
                total = int(m.group(1))
                break
        if total is None:
            return None, f"no 'tests collected' found, last lines: {tail}"
        # 进一步按 test_*.py 前缀映射模块
        module_counts = collections.Counter()
        for line in (r.stdout + r.stderr).splitlines():
            # <Function 'test_xxx'> 或 <Class 'TestXxx'> 来自 test_xxx.py
            m = re.search(r"tests/(test_\w+)\.py", line)
            if not m:
                m = re.search(r"(test_\w+)\.py::", line)
            if m:
                module_counts[m.group(1)] += 1
        return total, module_counts
    except subprocess.TimeoutExpired:
        return None, "pytest collect timeout 180s"
    except Exception as e:
        return None, str(e)

total, by_pytest = collect_via_pytest()

# 方法2: grep 回退（仅当方法1失败时用于补数，但会如实标注）
grep_counts = collections.Counter()
scope = []
if total is None:
    scope.append(f"pytest收集失败({by_pytest})，改用 grep def test_ 估算")
    for root, _, files in os.walk(TESTS_DIR):
        for fn in files:
            if not fn.startswith("test_") or not fn.endswith(".py"):
                continue
            mod = fn[:-3]
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                cnt = sum(1 for ln in f if re.match(r"    def test_\w|def test_\w", ln))
            grep_counts[mod] = cnt
    total = sum(grep_counts.values())
    # pytest 失败则以 grep 为准
    by_pytest = grep_counts

# 文件名 -> 引擎/模块 映射（基于 AcouScope 代码组织事实）
name_map = {
    "test_audio": "音频 IO (audio.io/player/recorder)",
    "test_dsp": "DSP 信号处理 (FFT/STFT/窗)",
    "test_analysis": "基础分析分析器 (spectral/temporal/silence 等)",
    "test_analysis_cache": "分析结果缓存",
    "test_spectrogram3d": "3D 频谱图 (spectrogram3d widget)",
    "test_spectrogram_tools": "语谱图工具 (spectrogram widget)",
    "test_timbre_features": "音色分析 (TimbreAnalyzer)",
    "test_pitch": "音高分析 (PitchAnalyzer)",  # 可能无单独文件，兜底
    "test_formants": "共振峰分析 (FormantAnalyzer)",  # 可能无单独文件，兜底
    "test_waveform_annotations": "波形标注",
    "test_waveform_editing": "波形编辑",
    "test_waveform_normalization": "波形归一化",
    "test_annotation": "标注系统",
    "test_async_analysis": "异步分析管线",
    "test_realtime_features": "实时特征算法",
    "test_realtime_panel": "实时面板 UI",
    "test_record_settings": "录音设置 UI",
    "test_regression": "回归测试 (FFT/Widget/Controller 综合)",
    "test_new_features": "新特性 (多维频率轴/导出等)",
    "test_chart_font": "图表字体与出图规范",
    "test_player_loop": "播放循环 (player)",
    "test_playback_rate": "变速播放 (player)",
    "test_ai_chat": "AI 释图接口",
}

# scope 分类
def scope_of_mod(mod):
    if mod in {"test_realtime_panel", "test_record_settings", "test_chart_font", "test_regression"}:
        return "algorithm+ui"
    if mod in {"test_player_loop", "test_playback_rate", "test_audio"}:
        return "algorithm+audio_io"
    return "algorithm"

by_module = []
scope_flags = set()
for mod, count in sorted(by_pytest.items(), key=lambda x: -x[1]):
    scope_flags.add(scope_of_mod(mod))
    by_module.append({
        "module": name_map.get(mod, mod),
        "source_file": f"tests/{mod}.py",
        "tests": count,
    })

# 若 by_module 缺某些引擎（无独立文件），标注 0 并说明
mentioned = {d["module"] for d in by_module}
for key in name_map:
    pass  # 不强造占位

out = {
    "id": "C6",
    "is_measured": True,
    "unit": "项 (test cases)",
    "total": total,
    "scope": "/".join(sorted(scope_flags)),
    "collect_method": "pytest --collect-only" if scope == [] else scope[0],
    "by_module": by_module,
}

os.makedirs(os.path.join(ROOT, ".pi", "metrics"), exist_ok=True)
out_path = os.path.join(ROOT, ".pi", "metrics", "C6_test_counts.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps({"total": total, "files": len(by_module), "collect_method": out["collect_method"]}, ensure_ascii=False))
print("->", out_path)
