# SPDX-License-Identifier: GPL-3.0-only
"""AcouScope 入口模块。"""

import sys
import threading
from pathlib import Path

from acouscope.utils.log import get_logger

_log = get_logger("main")

# 预热延后秒数：不与冷启动窗口争核（T-901b 有意设计，改动需真机 profile 另议）
MATPLOTLIB_WARM_DELAY_S = 8.0


def _warm_matplotlib():
    """后台预热 matplotlib（import + 字体缓存构建，冷启动可达数秒）。

    不导入 Qt 后端（须在主线程），只预热与 Qt 无关的部分；
    提前完成后，首次切换 3D 频谱图/导出图表不再卡顿。
    延迟触发（T-901b）。
    """
    try:
        import matplotlib
        import matplotlib.font_manager  # noqa: F401 触发字体缓存构建
        from matplotlib.figure import Figure  # noqa: F401
    except Exception as e:
        _log.warning("matplotlib 预热失败（首次 3D/导出可能卡顿）: %s", e)


def main():
    """程序主入口。"""
    # 确保 src 目录在路径中（开发模式）
    src_path = Path(__file__).parent.parent.parent
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    # 单实例守卫（T-1029）：早于 AppController / QApplication
    from acouscope.utils.single_instance import try_acquire

    _si = try_acquire()
    if _si is False:
        _log.info("AcouScope 已在运行，本次启动退出。")
        sys.exit(0)
    elif _si is None:
        _log.warning("单实例守卫机制失败（fail-open，照常启动）。")

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("错误：未找到 PyQt6，请先安装依赖。")
        print("  pip install PyQt6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("AcouScope")
    app.setOrganizationName("AcouScope")

    # App 基座（T-1031 · 视觉语言 §五）：统一原生控件绘制底座 + 全局字族/字号。
    # 只写在生产入口（裁定 F′）：测试 qapp 夹具统一经 apply_theme 建窗，
    # 基座若进 apply_theme 会静默改动全部 GUI 测试的控件度量。
    try:
        from PyQt6.QtGui import QFont

        from acouscope.ui.theme import TOKENS, ui_font_families

        app.setStyle("Fusion")
        # 主族名 = typography.family 的整条跨平台回落链（T-1037）：此前只取链首项，
        # 缺字体环境下真正渲染的字体由 Qt 自行决定，回落链不在我们手里。
        # 数据源末尾的泛型兜底不进 setFamilies（其只接受具体族名，由 helper 剔除）。
        # 注：本机 PyQt6 无 QApplication.setApplicationFont（static 方法），
        #     用等价的 QGuiApplication.setFont（全局默认字体）落地。
        f = QFont()
        f.setFamilies(ui_font_families())
        f.setPointSize(TOKENS["typography"]["body"])
        app.setFont(f)
    except Exception as e:
        _log.warning("App 基座（Fusion/全局字体）施加失败，回退系统默认: %s", e)

    # 启动即应用已保存主题（含跟随系统的运行时监听）
    try:
        from acouscope.ui.theme import apply_theme
        from acouscope.utils.config import Settings

        apply_theme(Settings.load().theme)
    except Exception as e:
        _log.warning("应用已保存主题失败，回退默认主题: %s", e)
        from acouscope.ui.theme import apply_theme

        apply_theme("dark")

    # 后台预热 matplotlib，避免首次使用 3D 频谱图时界面冻结
    # 预热延迟到窗口就绪后 8s（冷启动窗口内不与 UI 初始化争核；T-901b）
    warm_timer = threading.Timer(MATPLOTLIB_WARM_DELAY_S, _warm_matplotlib)
    warm_timer.daemon = True
    warm_timer.start()

    window = MainWindow(controller)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
