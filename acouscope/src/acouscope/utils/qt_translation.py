# SPDX-License-Identifier: GPL-3.0-only
"""G2：Qt 标准按钮（Yes/No/OK/Cancel）中文翻译的幂等安装 · 共享模块。

供两处复用：生产入口（界面语言在 MainWindow 构造内就绪后首次安装）与
「设置→应用」切语言（运行期同步）。本模块**只**依赖 ``PyQt6.QtCore`` 与
``acouscope.i18n``（只读 get_language）；严禁 import 程序入口或主窗口模块，
避免与之成环。翻译目录由 ``QLibraryInfo`` 运行时解析，禁硬编码绝对路径。
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# 语言 → Qt 自带中文翻译文件（QLibraryInfo.TranslationsPath 下）
_QM_BY_LANG = {"zh_CN": "qt_zh_CN.qm", "zh_TW": "qt_zh_TW.qm"}
# 由 app 持有 QTranslator 引用的属性名（防 Python GC 提前回收底层 C++ 对象）
_HOLDER_ATTR = "_qt_zh_translator"


def install_qt_translation(app):
    """按当前界面语言幂等同步 Qt 标准按钮翻译。

    读 ``acouscope.i18n.get_language()``（只读）：zh_CN → qt_zh_CN.qm，
    zh_TW → qt_zh_TW.qm；en_US / 未知语言 → 卸载后返回 None。

    幂等：无论接下来是否安装，先 ``removeTranslator`` + 清引用卸载 app 上
    已持有的旧 translator，故重复调用（含运行期切换语言）不会叠加、不会
    残留过期语言态。``app is None`` 安全返回 None。返回已安装并持有的
    QTranslator，未安装时返回 None。
    """
    if app is None:
        return None

    from PyQt6.QtCore import QLibraryInfo, QTranslator
    from acouscope import i18n

    # 幂等同步：先卸载旧的、清引用（en_US / 未知语言亦走此卸载路径）
    old = getattr(app, _HOLDER_ATTR, None)
    if old is not None:
        app.removeTranslator(old)
        try:
            delattr(app, _HOLDER_ATTR)
        except Exception:
            setattr(app, _HOLDER_ATTR, None)

    qm_name = _QM_BY_LANG.get(i18n.get_language())
    if qm_name is None:
        return None
    try:
        trans_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        translator = QTranslator(app)
        if not translator.load(qm_name, trans_dir):
            _log.warning("Qt 中文翻译加载失败: %s", qm_name)
            return None
        app.installTranslator(translator)
        # 由 app 持有引用，防 Python GC 提前回收底层 C++ 对象
        setattr(app, _HOLDER_ATTR, translator)
        return translator
    except Exception as e:
        _log.warning("Qt 中文翻译安装失败: %s", e)
        return None
