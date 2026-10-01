# SPDX-License-Identifier: GPL-3.0-only
"""T-507b 守卫测试：右面板填充「视图参数检查器」+ AI 释图入口。

覆盖：aiRequested 信号 / 五组只读标签格式 / reset 回占位 /
右面板容器化（right_panel.set_content）/ 选区同步 /
aiRequested → 抽屉承载 AIInterpretDialog（T-507a 路径）。

fixture 参照 tests/test_view_stack.py：
qapp（conftest 会话级）+ window + monkeypatch 门控 + HOME=tmp_path
+ 合成音频，window 不 show()，QT_QPA_PLATFORM=offscreen。
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.ai_interpret import AIInterpretDialog
from acouscope.ui.widgets.panels import InspectorPanel

# 批4d：抽屉实现整档删除（`_v099_drawer_*` 注册族随之失去实现）
_DRAWER_PY = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"
)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控）。"""


    # 设置写入指向临时目录，避免污染用户配置
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


class TestInspectorPanelUnit:
    """单元用例：直接实例化 InspectorPanel（不依赖主窗口）。"""

    def test_ai_button_emits_signal(self, qapp):
        panel = InspectorPanel()
        fired = []
        panel.aiRequested.connect(lambda: fired.append(1))  # 信号无参
        panel.btn_ai.click()
        assert len(fired) == 1

    def test_selection_labels(self, qapp):
        panel = InspectorPanel()
        panel.set_selection((1.0, 2.5))
        text = panel.lbl_selection.text()
        assert "1.000" in text
        assert "2.500" in text
        assert "1.500" in text  # 时长 = hi - lo
        panel.set_selection(None)
        assert panel.lbl_selection.text() == "无"

    def test_analysis_scope_and_playback(self, qapp):
        # CB-016-3：检查器分析范围改为数值化 set_analysis_scope(position, frame_size)
        panel = InspectorPanel()
        panel.set_analysis_scope(1.234, 0.046)
        aw = panel.lbl_analysis.text()
        assert "1.234" in aw
        assert "0.046" in aw
        assert "–" not in aw  # 无 region 二元组残留语义
        panel.set_playback(1.234, 5.0)
        pb = panel.lbl_playback.text()
        assert "1.234" in pb
        assert "5.000" in pb

    def test_reset_clears(self, qapp):
        panel = InspectorPanel()
        panel.set_selection((0.0, 1.0))
        panel.set_view_name("FFT 频谱")
        panel.reset()
        assert panel.lbl_view.text() == "—"
        assert panel.lbl_selection.text() == "无"
        assert panel.lbl_playback.text() == "0.000 / 0.000 s"


class TestInspectorPanelIntegration:
    """集成用例：window fixture（已加载 20 s 合成音频）。"""

    def test_right_panel_contains_inspector(self, window):
        assert window.inspector_panel is not None
        assert isinstance(window.inspector_panel, InspectorPanel)
        # 已装入右面板内容区
        assert window.inspector_panel.parent() is not None

    def test_selection_syncs(self, window):
        window._on_selection_changed((1.0, 2.5))
        assert "1.000" in window.inspector_panel.lbl_selection.text()

    def test_ai_requested_switches_right_content(self, window, qapp):
        window.inspector_panel.aiRequested.emit()
        qapp.processEvents()
        # 右栏「AI 释图」内容激活：宿主页选中、面板实例装入宿主（每次新建，T-1012）
        assert isinstance(window._ai_panel, AIInterpretDialog)
        assert window.right_content.currentWidget() is window._ai_host
        assert window._ai_panel.parent() is window._ai_host
        assert window.right_content.widget(1) is window._ai_host
        # 不再创建右抽屉（AI 改由右栏承载，T-1010/T-1012；批4d 抽屉实现整档删除）
        assert not hasattr(window, "_v099_drawer_640")
        assert not _DRAWER_PY.exists()
        # 清理：关闭 AI 面板（触发 closeEvent，防 worker 泄漏）
        window._ai_panel.close()


class TestInspectorGroupTitlesI18n:
    """CB-001 #12：分组小标题走 i18n（三语齐全，非中文字面量硬编码）。
    T-327 Pε 追加第 6 组「选区统计」（inspector.stats）。"""

    _KEYS = (
        "inspector.view",
        "inspector.selection",
        "inspector.analysis",
        "inspector.playback",
        "inspector.audio",
        "inspector.stats",
    )

    def test_i18n_keys_exist_in_three_languages(self):
        from acouscope.i18n import _STRINGS

        for key in self._KEYS:
            entry = _STRINGS.get(key)
            assert entry is not None, f"i18n 缺 key: {key}"
            for lang in ("en_US", "zh_CN", "zh_TW"):
                assert entry.get(lang), f"{key} 缺 {lang}"

    def test_titles_follow_language(self, qapp):
        import acouscope.i18n as i18n
        from acouscope.i18n import tr
        from PyQt6.QtWidgets import QLabel

        def titles(panel):
            # 分组小标题未作为属性暴露（_group 只返回值标签），按 objectName 取
            return [
                lbl.text()
                for lbl in panel.findChildren(QLabel, "inspectorGroupTitle")
            ]

        prev = i18n.get_language()
        try:
            i18n.set_language("zh_CN")
            p_zh = InspectorPanel()
            zh_titles = titles(p_zh)
            assert zh_titles == [tr(k) for k in self._KEYS]
            assert zh_titles[0] == "当前视图"

            i18n.set_language("en_US")
            p_en = InspectorPanel()
            en_titles = titles(p_en)
            assert en_titles == [tr(k) for k in self._KEYS]
            # 同一 key 在不同语言下取值不同 → 证明走的是 i18n 而非字面量
            assert en_titles[0] != zh_titles[0]
        finally:
            i18n.set_language(prev)
