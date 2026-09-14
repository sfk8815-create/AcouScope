# SPDX-License-Identifier: GPL-3.0-only
"""房间声学分析模块。

包含：
- 房间模态分析（Room Modes）
- Sabine 混响时间计算
- Farina 指数扫频冲激响应测量
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple


# ======================================================================
# 房间模态分析
# ======================================================================

@dataclass
class RoomMode:
    """单个房间模态。"""
    frequency: float          # 频率 Hz
    nx: int                   # x 方向阶数
    ny: int                   # y 方向阶数
    nz: int                   # z 方向阶数
    mode_type: str            # "axial" / "tangential" / "oblique"
    amplitude_db: float       # 相对幅度 (dB)，轴向 0dB，切向 -3dB，斜向 -6dB


def calculate_room_modes(
    length_x: float,
    length_y: float,
    length_z: float,
    max_order: int = 10,
    max_freq: float = 300.0,
    speed_of_sound: float = 343.0,
) -> List[RoomMode]:
    """计算矩形房间的固有模态。

    使用 Rayleigh 方程：
        f = (c/2) * sqrt((nx/Lx)^2 + (ny/Ly)^2 + (nz/Lz)^2)

    Args:
        length_x: 房间长度 (m)
        length_y: 房间宽度 (m)
        length_z: 房间高度 (m)
        max_order: 每个方向的最大阶数
        max_freq: 最大频率 (Hz)
        speed_of_sound: 声速 (m/s)，默认 20°C 干燥空气 343 m/s

    Returns:
        按频率排序的 RoomMode 列表
    """
    modes = []
    half_c = speed_of_sound / 2.0

    for nx in range(0, max_order + 1):
        for ny in range(0, max_order + 1):
            for nz in range(0, max_order + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue

                term = (nx / length_x) ** 2 + (ny / length_y) ** 2 + (nz / length_z) ** 2
                freq = half_c * np.sqrt(term)

                if freq > max_freq:
                    continue

                # 判断模态类型
                nonzero = sum(1 for n in (nx, ny, nz) if n > 0)
                if nonzero == 1:
                    mode_type = "axial"
                    amp_db = 0.0
                elif nonzero == 2:
                    mode_type = "tangential"
                    amp_db = -3.0
                else:
                    mode_type = "oblique"
                    amp_db = -6.0

                modes.append(RoomMode(
                    frequency=float(freq),
                    nx=nx, ny=ny, nz=nz,
                    mode_type=mode_type,
                    amplitude_db=amp_db,
                ))

    # 按频率排序
    modes.sort(key=lambda m: m.frequency)
    return modes


def synthesize_mode_response(
    modes: List[RoomMode],
    freq_range: Tuple[float, float] = (20, 300),
    num_points: int = 1000,
    q_factor: float = 20.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """合成房间模态的理论频率响应。

    每个模态用高斯函数（dB 域为抛物线）表示，叠加得到总响应。

    Args:
        modes: 房间模态列表
        freq_range: 频率范围 (Hz)
        num_points: 频率分辨率
        q_factor: 模态品质因数（控制带宽）

    Returns:
        (频率数组, dB 幅度数组)
    """
    freqs = np.logspace(
        np.log10(max(freq_range[0], 1)),
        np.log10(freq_range[1]),
        num_points,
    )
    response = np.full(num_points, -80.0)

    for mode in modes:
        # 高斯函数在 dB 域：A - (f - f0)^2 / (2 * sigma^2)
        # sigma = f0 / Q
        sigma = mode.frequency / q_factor
        mode_response = mode.amplitude_db - (freqs - mode.frequency) ** 2 / (2 * sigma ** 2)
        # 叠加（对数域）
        response = np.logaddexp(response * np.log(10) / 20, mode_response * np.log(10) / 20)
        response = response * 20 / np.log(10)

    # 归一化到 0 dB
    peak = np.max(response)
    if peak > -80:
        response -= peak

    return freqs, response


# ======================================================================
# Sabine 混响时间计算器
# ======================================================================

@dataclass
class AbsorptionMaterial:
    """吸声材料定义。"""
    name: str
    # 倍频程中心频率下的吸声系数
    coefficients: dict  # {125: 0.01, 250: 0.02, 500: 0.05, 1000: 0.1, 2000: 0.15, 4000: 0.2}


# 常用建筑材料吸声系数数据库（倍频程，125Hz ~ 4kHz）
MATERIAL_DATABASE = {
    "concrete": AbsorptionMaterial(
        name="混凝土（光滑）",
        coefficients={125: 0.01, 250: 0.01, 500: 0.02, 1000: 0.02, 2000: 0.03, 4000: 0.04},
    ),
    "brick": AbsorptionMaterial(
        name="砖墙（抹灰）",
        coefficients={125: 0.02, 250: 0.03, 500: 0.04, 1000: 0.05, 2000: 0.06, 4000: 0.07},
    ),
    "wood": AbsorptionMaterial(
        name="木板",
        coefficients={125: 0.08, 250: 0.10, 500: 0.10, 1000: 0.08, 2000: 0.08, 4000: 0.10},
    ),
    "glass": AbsorptionMaterial(
        name="玻璃窗",
        coefficients={125: 0.05, 250: 0.04, 500: 0.03, 1000: 0.03, 2000: 0.02, 4000: 0.02},
    ),
    "carpet": AbsorptionMaterial(
        name="地毯（厚）",
        coefficients={125: 0.08, 250: 0.15, 500: 0.30, 1000: 0.50, 2000: 0.60, 4000: 0.65},
    ),
    "acoustic_foam": AbsorptionMaterial(
        name="声学泡沫（5cm）",
        coefficients={125: 0.15, 250: 0.35, 500: 0.70, 1000: 0.90, 2000: 0.95, 4000: 0.95},
    ),
    "gypsum_board": AbsorptionMaterial(
        name="石膏板",
        coefficients={125: 0.20, 250: 0.15, 500: 0.10, 1000: 0.08, 2000: 0.06, 4000: 0.05},
    ),
    "curtain": AbsorptionMaterial(
        name="厚重窗帘",
        coefficients={125: 0.05, 250: 0.10, 500: 0.20, 1000: 0.40, 2000: 0.60, 4000: 0.65},
    ),
    "person": AbsorptionMaterial(
        name="人体（每人）",
        coefficients={125: 0.30, 250: 0.45, 500: 0.55, 1000: 0.60, 2000: 0.65, 4000: 0.70},
    ),
}

OCTAVE_BANDS = [125, 250, 500, 1000, 2000, 4000]


def sabine_rt60(
    volume: float,
    total_absorption: dict,
    speed_of_sound: float = 343.0,
) -> dict:
    """Sabine 公式计算 RT60。

    RT60 = 0.161 * V / A  (当 c = 343 m/s 时，0.161 ≈ 24 ln(10) / c)

    更准确的公式：RT60 = (24 * ln(10) / c) * V / A

    Args:
        volume: 房间体积 (m³)
        total_absorption: 各倍频程总吸声量 {freq: sabins}
        speed_of_sound: 声速 (m/s)

    Returns:
        各倍频程 RT60 值 {freq: seconds}
    """
    factor = 24.0 * np.log(10.0) / speed_of_sound  # ≈ 0.161
    rt60 = {}
    for freq, absorption in total_absorption.items():
        if absorption > 0:
            rt60[freq] = factor * volume / absorption
        else:
            rt60[freq] = float('inf')
    return rt60


def calculate_total_absorption(
    surfaces: List[Tuple[float, str]],
    num_people: int = 0,
) -> dict:
    """计算房间总吸声量。

    Args:
        surfaces: [(面积 m², 材料 key), ...]
        num_people: 人数

    Returns:
        各倍频程总吸声量 {freq: sabins}
    """
    total = {f: 0.0 for f in OCTAVE_BANDS}

    for area, material_key in surfaces:
        if material_key in MATERIAL_DATABASE:
            mat = MATERIAL_DATABASE[material_key]
            for freq in OCTAVE_BANDS:
                total[freq] += area * mat.coefficients.get(freq, 0.0)

    # 人体吸声（按每人 0.5m² 等效面积近似）
    if num_people > 0:
        person_mat = MATERIAL_DATABASE["person"]
        for freq in OCTAVE_BANDS:
            total[freq] += num_people * person_mat.coefficients.get(freq, 0.0) * 0.5

    return total


# ======================================================================
# Farina 指数扫频冲激响应测量
# ======================================================================

def generate_exponential_sweep(
    f_start: float = 20.0,
    f_end: float = 20000.0,
    duration: float = 10.0,
    sample_rate: int = 48000,
    fade_in: float = 0.05,
    fade_out: float = 0.2,
) -> Tuple[np.ndarray, np.ndarray]:
    """生成 Farina 指数扫频信号。

    Args:
        f_start: 起始频率 (Hz)
        f_end: 结束频率 (Hz)
        duration: 持续时间 (s)
        sample_rate: 采样率 (Hz)
        fade_in: 淡入时间 (s)
        fade_out: 淡出时间 (s)

    Returns:
        (扫频信号, 时间轴)
    """
    n_samples = int(duration * sample_rate)
    t = np.arange(n_samples) / sample_rate

    # 指数扫频相位函数
    # phi(t) = 2*pi*f1*T / ln(f2/f1) * (exp(t/T * ln(f2/f1)) - 1)
    ratio = f_end / f_start
    log_ratio = np.log(ratio)
    phase = 2.0 * np.pi * f_start * duration / log_ratio * (
        np.exp(t / duration * log_ratio) - 1.0
    )

    sweep = np.sin(phase)

    # 淡入淡出
    if fade_in > 0:
        n_fade_in = int(fade_in * sample_rate)
        fade_in_curve = np.sin(np.linspace(0, np.pi / 2, n_fade_in)) ** 2
        sweep[:n_fade_in] *= fade_in_curve

    if fade_out > 0:
        n_fade_out = int(fade_out * sample_rate)
        fade_out_curve = np.cos(np.linspace(0, np.pi / 2, n_fade_out)) ** 2
        sweep[-n_fade_out:] *= fade_out_curve

    return sweep, t


def generate_inverse_filter(
    sweep: np.ndarray,
    f_start: float = 20.0,
    f_end: float = 20000.0,
    sample_rate: int = 48000,
) -> np.ndarray:
    """生成扫频信号的逆滤波器。

    幅度随频率 1/f 衰减（"去粉"），使得扫频信号通过逆滤波器后是平的。

    Args:
        sweep: 正向扫频信号
        f_start: 起始频率 (Hz)
        f_end: 结束频率 (Hz)
        sample_rate: 采样率 (Hz)

    Returns:
        逆滤波器（与 sweep 等长）
    """
    n = len(sweep)
    # 时间反转
    inverse = sweep[::-1].copy()

    # 计算 1/f 幅度包络（"去粉"）
    # Farina 方法：时间反转的扫频乘以 1/f 幅度包络
    duration = n / sample_rate
    t = np.arange(n) / sample_rate
    ratio = f_end / f_start
    log_ratio = np.log(ratio)

    # 瞬时频率随时间的变化
    inst_freq = f_start * np.exp(t / duration * log_ratio)

    # 1/f 幅度包络（归一化）
    envelope = f_start / inst_freq  # 从 1 降到 f_start/f_end

    # 应用包络
    inverse *= envelope

    # 归一化能量
    energy = np.sum(inverse ** 2)
    if energy > 0:
        inverse /= np.sqrt(energy / n)

    return inverse


def compute_impulse_response(
    recorded_sweep: np.ndarray,
    inverse_filter: np.ndarray,
) -> np.ndarray:
    """通过卷积计算冲激响应。

    Args:
        recorded_sweep: 录制的扫频响应信号
        inverse_filter: 逆滤波器

    Returns:
        冲激响应（长度为 len(recorded) + len(inverse) - 1）
    """
    # FFT 卷积
    n_fft = 1
    while n_fft < len(recorded_sweep) + len(inverse_filter) - 1:
        n_fft *= 2

    spec_record = np.fft.rfft(recorded_sweep, n_fft)
    spec_inverse = np.fft.rfft(inverse_filter, n_fft)

    ir_freq = spec_record * spec_inverse
    ir = np.fft.irfft(ir_freq, n_fft)

    # 截断到有效长度
    return ir[:len(recorded_sweep) + len(inverse_filter) - 1]


def extract_ir_peak(
    ir: np.ndarray,
    pre_peak: float = 0.01,
    post_peak: float = 1.0,
    sample_rate: int = 48000,
) -> Tuple[np.ndarray, int]:
    """提取冲激响应的主要峰值部分。

    Args:
        ir: 冲激响应
        pre_peak: 峰值前保留时间 (s)
        post_peak: 峰值后保留时间 (s)
        sample_rate: 采样率 (Hz)

    Returns:
        (截取的 IR, 峰值在原信号中的索引)
    """
    peak_idx = np.argmax(np.abs(ir))
    n_pre = int(pre_peak * sample_rate)
    n_post = int(post_peak * sample_rate)

    start = max(0, peak_idx - n_pre)
    end = min(len(ir), peak_idx + n_post)

    return ir[start:end], peak_idx - start


def rt60_from_ir(
    ir: np.ndarray,
    sample_rate: int = 48000,
    method: str = "T30",
) -> Tuple[dict, np.ndarray, np.ndarray]:
    """从冲激响应计算 RT60。

    使用 Schroeder 积分后曲线，然后用线性回归计算衰减率。

    Args:
        ir: 冲激响应
        sample_rate: 采样率 (Hz)
        method: "T20" (-5~-25dB), "T30" (-5~-35dB), "EDT" (0~-10dB)

    Returns:
        (结果字典, 时间轴, Schroeder 衰减曲线 (dB))
    """
    # Schroeder 反向积分
    energy = ir ** 2
    schroeder = np.cumsum(energy[::-1])[::-1]
    schroeder /= schroeder[0]  # 归一化

    # 转换为 dB
    eps = 1e-10
    schroeder_db = 10.0 * np.log10(schroeder + eps)

    # 时间轴
    t = np.arange(len(ir)) / sample_rate

    # 确定拟合区间
    if method == "T20":
        db_start, db_end = -5.0, -25.0
    elif method == "T30":
        db_start, db_end = -5.0, -35.0
    elif method == "EDT":
        db_start, db_end = 0.0, -10.0
    else:
        db_start, db_end = -5.0, -35.0

    # 找到区间
    mask = (schroeder_db <= db_start) & (schroeder_db >= db_end)
    if np.sum(mask) < 10:
        return {"rt60": 0.0, "method": method, "valid": False}, t, schroeder_db

    # 线性拟合
    t_fit = t[mask]
    db_fit = schroeder_db[mask]

    # 最小二乘拟合: db = slope * t + intercept
    slope, intercept = np.polyfit(t_fit, db_fit, 1)

    # RT60 = -60 / slope
    rt60 = -60.0 / slope if slope < 0 else 0.0

    result = {
        "rt60": float(rt60),
        "method": method,
        "valid": bool(rt60 > 0),
        "slope": float(slope),
        "intercept": float(intercept),
        "db_start": db_start,
        "db_end": db_end,
    }

    return result, t, schroeder_db
