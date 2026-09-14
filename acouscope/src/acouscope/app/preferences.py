# SPDX-License-Identifier: GPL-3.0-only
"""偏好设置。

对 Settings 的薄封装，提供更便捷的属性访问。
"""

from acouscope.utils import Settings


class Preferences:
    """偏好设置管理。

    提供类型安全的设置访问和验证。
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def settings(self) -> Settings:
        """底层 Settings 对象。"""
        return self._settings

    # ---- 语言 ----
    @property
    def language(self) -> str:
        return self._settings.language

    @language.setter
    def language(self, value: str):
        if value in ("zh_CN", "en_US"):
            self._settings.language = value

    # ---- 音频 ----
    @property
    def default_sample_rate(self) -> int:
        return self._settings.default_sample_rate

    @default_sample_rate.setter
    def default_sample_rate(self, value: int):
        if value in (22050, 44100, 48000, 96000, 192000):
            self._settings.default_sample_rate = value

    # ---- FFT ----
    @property
    def default_fft_size(self) -> int:
        return self._settings.default_fft_size

    @default_fft_size.setter
    def default_fft_size(self, value: int):
        # 确保是 2 的幂
        if value > 0 and (value & (value - 1)) == 0:
            self._settings.default_fft_size = value

    def save(self):
        """保存设置到磁盘。"""
        self._settings.save()
