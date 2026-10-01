# SPDX-License-Identifier: GPL-3.0-only
"""
AcouScope - 面向音乐与数字人文领域研究的跨平台声学分析软件。

模块结构:
    app         - 应用层（控制器、项目管理、偏好设置）
    audio       - 音频 I/O（文件读写、播放控制）
    dsp         - DSP 引擎（FFT、STFT、滤波器、窗函数、单位换算）
    analysis    - 分析服务（音高、频谱、共振峰、音色、时域特征）
    ui          - GUI 层（主窗口、控件）
    visualization - 可视化与出图
    utils       - 工具函数（配置）
"""

__version__ = "0.99.20260925"
__version_display__ = "0.99_20260925(beta)"
__version_suffix = "Beta"
__app_name__ = "AcouScope"
__app_name_cn__ = "音析"
__author__ = "Fengkai Shi"
__license__ = "GPL-3.0-only"
