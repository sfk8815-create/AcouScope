# SPDX-License-Identifier: GPL-3.0-only
"""T-903b 构建期 shim：-S + PYTHONHASHSEED=0 单进程内跑 Nuitka 4.2.1。

背景（T-903 四迭代教训 + 架构师 2026-09-07 本机实证，禁偏离）：
- 宿主是 TRAE 重打包的「可移植 Homebrew Python」：
  <framework>/Versions/3.10/lib/python3.10/sitecustomize.py 首行含 "Homebrew"
  标记 → isHomebrewPython()=True，但目录树无 Cellar 祖先 → 4.2.1
  getHomebrewInstallPath() 断言链崩溃（AssertionError 实测）。
- 4.2.1 __main__.main()：sys.flags.no_site==0 或 PYTHONHASHSEED!="0" 即
  reExecuteNuitka 自启新进程（monkeypatch 丢失）。以 -S + PYTHONHASHSEED=0
  启动则 needs_re_execution=False（Python 3.10 无 3.11 frozen 检查），单进程。
- 正确 patch 目标：isHomebrewPython/isPyenvHomebrewPython → False（五模块：
  PythonFlavors 本体 + 4 个 from-import 副本模块）。源码实读：全部 4 个调用点
  （freezer/Standalone.py:605、freezer/DllDependenciesMacOS.py:94、
  options/Options.py:1975、plugins/standard/TkinterPlugin.py:186/236）的
  Homebrew 分支均为「仅增加搜索路径/标记 static-libpython broken」的加法逻辑；
  置 False 后 Nuitka 按普通 Python（Flavor: Unknown）处理，getHomebrewInstallPath
  不可达（禁再用其假路径绕法）。
- -S 下 site.py/sitecustomize 不运行：venv 检测不执行（sys.prefix 退化 framework
  路径），且 TRAE 可移植布局的 tools site-packages（运行时依赖 PyQt6/numpy/
  onnxruntime 所在）也不再被注入 → 必须手工重建 sys.path：
  * venv_sp 从 sys.executable 显式推导（禁 realpath！venv python 是指向 framework
    的符号链接，realpath 会解析掉 venv）；
  * tools_sp 从 sys.base_prefix 上溯含 lib+opt 的工具前缀推导（与 sitecustomize
    的布局约定一致，双保险）。

libpython 路径 FATAL（「failed to find path $PREFIX/lib/Python」）的修复不在本
shim 内：由 build_nuitka.sh [2.5/5] 以临时符号链接 $PREFIX/lib/Python →
$PREFIX/Python（构建后 rm 清理，trap EXIT 兜底）补齐常规布局（架构师
2026-09-07 实测定案）。本文件不触宿主系统、不做 staging/scons/PostProcessing
拦截（ITER1 旧方案已废弃）。

用法：PYTHONHASHSEED=0 python -S scripts/nuitka_shim.py <nuitka 参数...>
     （参数由 build_nuitka.sh 以位置参数传入；本文件仅构建期生效）
"""

import os
import sys

# ── 契约断言：单进程前提（不满足直接退出，禁 re-exec 分支） ──────────────────
if sys.flags.no_site != 1:
    sys.exit("T-903b shim: 必须以 -S（no_site=1）启动（否则 Nuitka 自重启丢 patch）")
if os.environ.get("PYTHONHASHSEED") != "0":
    sys.exit('T-903b shim: 必须设 PYTHONHASHSEED=0（否则 Nuitka 自重启丢 patch）')

_ver = "%d.%d" % sys.version_info[:2]

# ── sys.path 重建（-S 无 site）─────────────────────────────────────────────
# 1) venv site-packages（nuitka/zstandard 构建工具所在）：
#    从 sys.executable 推导，禁 realpath（venv python 是符号链接，realpath 会
#    解析到 framework 而丢 venv 层）。
#    .venv/bin/python → ../lib/python3.10/site-packages
venv_sp = os.path.join(
    os.path.dirname(os.path.dirname(sys.executable)),
    "lib",
    "python" + _ver,
    "site-packages",
)

# 2) 工具 site-packages（运行时依赖所在，TRAE 可移植布局）：
#    从 sys.base_prefix 上溯至含 lib+opt 的工具前缀（…/vm/tools），
#    与 TRAE sitecustomize.py 的布局约定一致（<tools>/lib/pythonX.Y/site-packages）。
tools_sp = None
_p = os.path.abspath(sys.base_prefix)
while _p and _p != os.path.dirname(_p):
    if os.path.isdir(os.path.join(_p, "lib")) and os.path.isdir(os.path.join(_p, "opt")):
        tools_sp = os.path.join(_p, "lib", "python" + _ver, "site-packages")
        break
    _p = os.path.dirname(_p)
if tools_sp is None:
    sys.exit("T-903b shim: 未能从 base_prefix 上溯工具前缀（lib+opt 布局约定失配）")

for _sp in (venv_sp, tools_sp):
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

if not os.path.isdir(venv_sp):
    sys.exit("T-903b shim: venv site-packages 缺失: " + venv_sp)

# ── patch 五模块：isHomebrewPython/isPyenvHomebrewPython → False ───────────
import nuitka.PythonFlavors as _pf  # noqa: E402

_pf.isHomebrewPython = lambda: False
_pf.isPyenvHomebrewPython = lambda: False

# from-import 副本（4 模块各自持有名字绑定，须逐个覆盖）
for _mod_name in (
    "nuitka.freezer.DllDependenciesMacOS",
    "nuitka.freezer.Standalone",
    "nuitka.options.Options",
    "nuitka.plugins.standard.TkinterPlugin",
):
    _mod = __import__(_mod_name, fromlist=["*"])
    for _name in ("isHomebrewPython", "isPyenvHomebrewPython"):
        if hasattr(_mod, _name):
            setattr(_mod, _name, lambda: False)

# ── patch options-nanny: PyQt6 macOS error → warning ──────────────────────
# Nuitka 4.2.1 options-nanny（OptionsNannyPlugin.py）在 standard.nuitka-package.
# config.yml:5272-5274 标记 PyQt6 on macOS 为 support_info='error' → sysexit。
# 架构师 2026-09-07 实读确认：PyQt6 在 Nuitka macOS 下确有已知限制（Qt 线程），
# 但本项目不使用 Qt 线程，构建可用。降级为 warning 不阻塞构建。
import nuitka.plugins.standard.OptionsNannyPlugin as _onp  # noqa: E402

_orig_csv = _onp.NuitkaPluginOptionsNanny._checkSupportedVersion


def _patched_csv(self, full_name, support_info, description, condition):
    if support_info == "error" and str(full_name) == "PyQt6":
        support_info = "warning"
    return _orig_csv(self, full_name, support_info, description, condition)


_onp.NuitkaPluginOptionsNanny._checkSupportedVersion = _patched_csv

# ── 自检：宿主探测确实被 patch 命中（未 patch 时 isHomebrewPython()=True 实测）──
import nuitka.PythonFlavors as _pf2  # noqa: E402,F811

if _pf2.isHomebrewPython() is not False:
    sys.exit("T-903b shim: patch 未生效（isHomebrewPython() != False）")

# ── 转调 Nuitka 入口（单进程，无 re-exec）─────────────────────────────────
sys.argv = ["nuitka"] + sys.argv[1:]

from nuitka.__main__ import main as _nuitka_main  # noqa: E402

_nuitka_main()
