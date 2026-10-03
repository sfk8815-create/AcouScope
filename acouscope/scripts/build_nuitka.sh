#!/bin/bash
# AcouScope Nuitka macOS arm64 构建脚本（T-903 打包链裁决实验 / T-903b 续，PyInstaller 备选候选）
# 用法：bash scripts/build_nuitka.sh
# 产物：dist-nuitka/AcouScope.app（可选 dist-nuitka/AcouScope-0.99.20260925-macOS-arm64.dmg）
# 幂等：每次运行先清理 dist-nuitka 构建目录再重建；与 dist/（PyInstaller，冻结）完全隔离
# 模型/FFmpeg 以数据文件模式 --include-data-dir 进包（禁编译进二进制）
# 构建期工具（nuitka/zstandard）装至 .venv site-packages（--target 显式定向；
# 该 venv 的 sysconfig purelib 被宿主环境重定向到只读工具目录，常规 pip install 会
# Permission denied，见 T-903 日志）
#
# 宿主解释器为 TRAE 重打包的「可移植 Homebrew Python」：
#   - sitecustomize.py 首行 "Homebrew" 标记 → 4.2.1 isHomebrewPython()=True，
#     但目录树无 Cellar 祖先 → getHomebrewInstallPath() 断言链崩溃（T-903 ITER3 实测）
#   - no_site==0 或 PYTHONHASHSEED!="0" 时 __main__ 自重启新进程，进程内 monkeypatch
#     丢失（T-903 ITER4 实测）
# T-903b 定案（架构师 2026-09-07 本机实证）：构建期 shim scripts/nuitka_shim.py 以
#   PYTHONHASHSEED=0 python -S scripts/nuitka_shim.py <nuitka 参数数组> 启动
# → needs_re_execution=False 单进程；shim 内 isHomebrewPython/isPyenvHomebrewPython
#   → False 打五模块（PythonFlavors + DllDependenciesMacOS/Standalone/Options/
#   TkinterPlugin 四个 from-import 副本），Nuitka 按普通 Python（Flavor: Unknown）
#   处理，Homebrew 加法分支（搜索路径/static-libpython broken 标记）全不进入，
#   getHomebrewInstallPath 不可达；-S 下 shim 从 sys.executable 显式推导 venv
#   site-packages（禁 realpath）+ 从 base_prefix 上溯工具前缀注入 tools
#   site-packages（运行时依赖），手工重建 sys.path。
# libpython 路径 shim（架构师 2026-09-07 实测定案，[2.5/5] 执行）：
#   宿主 framework 的 lib/libpython3.10.dylib 是 → ../Python 符号链接且
#   LC_ID_DYLIB=@loader_path/Python；ld 将依赖记录为绝对路径 $PREFIX/lib/Python
#   （不存在）→ 4.2.1 DLL 扫描期 os.path.exists 检查 FATAL（ITER1 实测）。修复：
#   构建前 ln -sf "$PREFIX/Python" "$PREFIX/lib/Python"（$PREFIX=sys.base_prefix），
#   构建后 rm -f 清理（trap EXIT 兜底）；禁改 $PREFIX 下其他文件。
#   Nuitka 将经符号链接解析的 $PREFIX/lib/Python 以 basename 拷入包内
#   Contents/MacOS/Python，主二进制依赖改写为 @executable_path/Python 自足。
# matplotlib mpl-data 断链 shim（架构师 2026-09-07 实测定案，[2.6/5] 执行）：
#   TRAE 系统 matplotlib 的 mpl-data/fonts/opentype 是断链（→ /tmp/build/dist/...
#   不存在）；4.2.1 copyDataFiles 对断链 open() 抛 FileNotFoundError（ITER3 实测
#   crash：IncludedDataFiles._handleDataFile→copyFileWithPermissions→shutil.copy2）。
#   沙箱禁改系统 Python → 构建前 cp -R mpl-data 至 mktemp 临时目录并 find 删断链，
#   Nuitka 加 --include-data-dir=$TMP_MPL=matplotlib/mpl-data（清洗副本显式进包，
#   布局不变）+ --noinclude-data-files=matplotlib/mpl-data/fonts/opentype（按
#   target filename 匹配精确禁掉自动 package-data 里的断链条目）；trap EXIT 删
#   临时目录。注意：需求说明原文的 --noinclude-package-data 在 4.2.1 不存在（实测
#   "error: no such option"），本替代为语义等价修正（源码实读+逐条匹配实测）：
#   - addIncludedDataFilesFromFileOptions（MainControl:1268，命令行早期相）先于
#     addIncludedDataFilesFromPackageOptions（:1269，自动 package-data）注册，
#     重复 dest 报 warning 并忽略后者 → 包内 mpl-data 内容取自清洗副本；
#   - 匹配语义（addIncludedDataFile:626）=fnmatch(dest,pattern)||isFilenameBelow
#     Path(pattern,dest)，按目标路径；宽模式 matplotlib/* 会连显式 include 一并
#     禁掉（禁），故用断链自身 dest 的精确模式（已逐路径实测：断链命中 True，
#     199 个清洗副本文件 False，他包 False）；
#   - getFileList（os.walk followlinks=False）不跟目录符号链接（fonts/Fonts→
#     /Library/Fonts、fonts/Supplemental→/System/... 在源树即被跳过，不膨胀包）；
#     源树断链文件符号链接恰 1 条（opentype，实测 200 枚举/1 断链），find 删断链
#     即全覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."   # → acouscope/ 项目根（.venv / src / dist-nuitka 所在层）

VENV_PY=".venv/bin/python"
VENV_SP=".venv/lib/python3.10/site-packages"
ENTRY="src/acouscope/__main__.py"
DIST_DIR="dist-nuitka"
APP="$DIST_DIR/AcouScope.app"
DMG="$DIST_DIR/AcouScope-0.99.20260925-macOS-arm64.dmg"
APP_VERSION="0.99.20260925"
SIGNED_APP_NAME="com.acouscope.app"
ICON="build/AcouScope.icns"

log() { echo "==> $*"; }

# 与 PyInstaller 流程一致：先退运行实例，避免 .app 文件被锁
if pgrep -x AcouScope >/dev/null 2>&1; then
    echo "==> 检测到 AcouScope 正在运行，先退出应用..."
    osascript -e 'quit app "AcouScope"' 2>/dev/null || true
    sleep 2
    pkill -x AcouScope 2>/dev/null || true
    sleep 1
fi

log "[0/5] venv 校验"
[ -x "$VENV_PY" ] || { echo "错误：$VENV_PY 不存在（应为 acouscope/.venv）"; exit 1; }
log "   python: $($VENV_PY -c 'import sys; print(sys.executable, sys.version.split()[0])')"
"$VENV_PY" -c "import PyQt6, numpy, pyqtgraph, onnxruntime" \
    || { echo "错误：运行时依赖不完整（PyQt6/numpy/pyqtgraph/onnxruntime）"; exit 1; }
[ -f "$ENTRY" ] || { echo "错误：入口 $ENTRY 不存在"; exit 1; }
[ -f scripts/nuitka_shim.py ] || { echo "错误：shim scripts/nuitka_shim.py 缺失"; exit 1; }
[ -d src/acouscope/resources/models ] || { echo "错误：模型目录缺失"; exit 1; }
[ -d src/acouscope/resources/bin ] || { echo "错误：bin 目录缺失"; exit 1; }
[ -f "$ICON" ] || { echo "错误：图标 $ICON 缺失"; exit 1; }

log "[1/5] 构建期工具（pip 安装，幂等；仅构建期，不进运行时依赖集）"
# 版本 pin 于首轮实装（2026-09-06：nuitka 4.2.1 / zstandard 0.25.0，tencent mirror）；
# 迭代升级时手工更新并记 jsonl
NUITKA_PIN="${NUITKA_PIN:-nuitka==4.2.1}"
ZSTD_PIN="${ZSTD_PIN:-zstandard==0.25.0}"
# 已装同版本则 pip 直接 satisfied（幂等）；--no-build-isolation 因宿主 sysconfig
# 异常导致构建隔离环境落点不可写（Permission denied 实测）
"$VENV_PY" -m pip install --disable-pip-version-check --no-build-isolation \
    --target "$VENV_SP" "$NUITKA_PIN" "$ZSTD_PIN"
log "   $($VENV_PY -m pip show nuitka 2>/dev/null | awk '/^Version/{print "nuitka="$2}')"
log "   $($VENV_PY -m pip show zstandard 2>/dev/null | awk '/^Version/{print "zstandard="$2}')"

log "[2/5] 清理 dist-nuitka（幂等重建）"
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

log "[2.5/5] libpython 路径 shim（架构师 2026-09-07 实测定案）"
# TRAE 可移植 Python framework 的 libpython 二进制在 $PREFIX/Python（framework
# 二进制，Mach-O arm64 shared library，LC_ID_DYLIB=@loader_path/Python），而
# lib/libpython3.10.dylib 只是指向 ../Python 的符号链接 → ld 记录依赖为绝对路径
# $PREFIX/lib/Python（不存在）→ 4.2.1 DLL 扫描 FATAL。临时符号链接补齐常规布局：
# $PREFIX/lib/Python → $PREFIX/Python；构建后 rm 清理（trap EXIT 兜底）。
# 铁律：仅新增此一个符号链接，禁改 $PREFIX 下其他文件。
HOST_PREFIX="$("$VENV_PY" -c 'import sys; print(sys.base_prefix)')"
case "$HOST_PREFIX" in
    */Frameworks/Python.framework/Versions/*) ;;
    *) echo "错误：base_prefix 非预期 framework 布局：$HOST_PREFIX（shim 守卫）"; exit 1 ;;
esac
[ -f "$HOST_PREFIX/Python" ] || { echo "错误：$HOST_PREFIX/Python 缺失（shim 守卫）"; exit 1; }
[ -d "$HOST_PREFIX/lib" ] || { echo "错误：$HOST_PREFIX/lib 缺失（shim 守卫）"; exit 1; }
# 兜底清理（无论成功/失败退出路径都执行；幂等 rm -f；后续 [2.6/5] 的 trap 会
# 重建为含本步在内的统一清理，本 trap 仅为 [2.5/5] 自身失败路径兜底）
cleanup_all_shims() { rm -f "$HOST_PREFIX/lib/Python"; }
trap cleanup_all_shims EXIT
ln -sf "$HOST_PREFIX/Python" "$HOST_PREFIX/lib/Python"
log "   ln -sf \$PREFIX/Python -> \$PREFIX/lib/Python（临时，trap EXIT 清理）"
log "   $HOST_PREFIX/lib/Python → $(readlink "$HOST_PREFIX/lib/Python")"

log "[2.6/5] matplotlib mpl-data 断链 shim（架构师 2026-09-07 实测定案）"
# 见文件头注释：断链 open() FATAL 的修复 = 清洗副本 + 数据文件模式显式进包。
MPL_DIR="$("$VENV_PY" -c 'import matplotlib,os;print(os.path.dirname(matplotlib.__file__))')"
[ -d "$MPL_DIR/mpl-data" ] || { echo "错误：$MPL_DIR/mpl-data 缺失（shim 守卫）"; exit 1; }
TMP_MPL_PARENT="$(mktemp -d)"
cleanup_all_shims() { rm -rf "${TMP_MPL_PARENT:-}"; rm -f "$HOST_PREFIX/lib/Python"; }
trap cleanup_all_shims EXIT   # 统一兜底（覆盖 [2.5/5] 的 trap）：两 shim 产物同清
TMP_MPL="$TMP_MPL_PARENT/mpl-data"
cp -R "$MPL_DIR/mpl-data" "$TMP_MPL"
find "$TMP_MPL" -type l ! -exec test -e {} \; -delete
log "   源断链（沙箱禁改，仅记录）："
find "$MPL_DIR/mpl-data" -type l ! -exec test -e {} \; -print | sed 's/^/     /' || true
log "   清洗后 $TMP_MPL 残留符号链接数：$(find "$TMP_MPL" -type l | wc -l | tr -d ' ')"
log "   du -sk 清洗后副本：$(du -sk "$TMP_MPL" | awk '{print $1}') KB"

# Nuitka flag 依据 4.2.1 --help 实读（2026-09-06）：
#   --macos-create-app-bundle  隐含 standalone，app bundle 模式（对应 spec BUNDLE/console=False）
#   --macos-app-console-mode=disable  无控制台（对应 spec console=False）
#   --macos-app-name / --macos-app-icon / --macos-app-version（0.99.20260925，
#     对齐 pyproject 现行版本；spec 内 0.98.20160830 为 PyInstaller 冻结路径的历史值）
#   --macos-signed-app-name  ad-hoc 签名身份/bundle id（对应 spec bundle_identifier）
#   --macos-app-protected-resource  麦克风权限文案（对应 spec NSMicrophoneUsageDescription）
#   --macos-app-macos-min-version=12.0（对应 spec LSMinimumSystemVersion）
#   NSHighResolutionCapable 由 Nuitka app bundle 默认置位（构建后 Info.plist 复核）
#   --static-libpython=no  宿主为 TRAE 重打包的 Homebrew Python framework（布局非常规，
#     4.2.1 静态 libpython 自动探测 FATAL；no=动态链 libpython，dist 随附 dylib）
# 模型/FFmpeg 显式 --include-data-dir（数据文件模式，保持目录结构，禁编译进二进制）
# --include-package=acouscope：等价 PyInstaller spec 的 collect_submodules("acouscope")
#   （本项目控制器/分析器/UI 存在动态引用，必须全量收集）
# --nofollow-import-to：等价 spec excludes（numba/llvmlite/scipy 未使用/有纯 numpy 回退，
#   tkinter 未使用）
# 缓存：4.2.1 无 --cache-dir（实测 no such option），用默认 ~/.cache/Nuitka（用户级）

export PYTHONPATH="src"
NUITKA_ARGS=(
    --standalone
    --follow-imports
    --macos-create-app-bundle
    --macos-app-console-mode=disable
    --macos-target-arch=arm64
    --macos-app-name="AcouScope"
    --macos-app-icon="$ICON"
    --macos-signed-app-name="$SIGNED_APP_NAME"
    --macos-app-version="$APP_VERSION"
    --macos-app-macos-min-version=12.0
    --static-libpython=no
    --enable-plugin=pyqt6
    --macos-app-protected-resource="NSMicrophoneUsageDescription:AcouScope 需要访问麦克风以录制音频进行分析。"
    --include-package=acouscope
    --include-package=acouscope_core
    --include-data-dir=src/acouscope/resources/models=acouscope/resources/models
    --include-data-dir=src/acouscope/resources/bin=acouscope/resources/bin
    --include-data-dir=src/acouscope/resources/icons=acouscope/resources/icons
    --include-data-files=src/acouscope/resources/jinyun_logo.svg=acouscope/resources/jinyun_logo.svg
    # matplotlib 断链 shim：精确禁掉自动 package-data 里的断链条目（4.2.1 按
    # target filename 匹配；禁宽模式 matplotlib/*——会连本行显式 include 一并禁掉）
    --noinclude-data-files=matplotlib/mpl-data/fonts/opentype
    # 清洗副本显式进包（早期相先注册，重复 dest 以清洗副本为准）
    --include-data-dir="$TMP_MPL=matplotlib/mpl-data"
    --output-dir="$DIST_DIR"
    --nofollow-import-to=numba
    --nofollow-import-to=llvmlite
    --nofollow-import-to=scipy
    --nofollow-import-to=tkinter
    --remove-output
    "$ENTRY"
)

log "[3/5] Nuitka standalone 构建（arm64 app bundle；编译 10-40 分钟，高 CPU 属正常）"
# T-903b 定案：shim 单进程启动（-S + PYTHONHASHSEED=0，needs_re_execution=False，
# patch 全程有效）。nuitka 参数以位置参数数组展开直传（无 env 中转，天然规避
# bash 3.2「export 与同名数组变量冲突静默失效」坑；如需 env 传递，键名须与数组
# 异名，如 NUITKA_ARGV vs NUITKA_ARGS——T-903 ITER4 实测教训）。
# -S 下 shim 内手工重建 sys.path：venv_sp（nuitka/zstandard）从 sys.executable
# 推导（禁 realpath）+ tools_sp（运行时依赖）自 base_prefix 上溯工具前缀。
PYTHONHASHSEED=0 "$VENV_PY" -S scripts/nuitka_shim.py "${NUITKA_ARGS[@]}"

# --output-dir 下产物即为 $APP（--macos-app-name=AcouScope）；兜底：产物名不符则按 *.app 唯一性重命名
if [ ! -d "$APP" ]; then
    ALT=$(ls -d "$DIST_DIR"/*.app 2>/dev/null | head -1 || true)
    [ -n "$ALT" ] && [ -d "$ALT" ] || {
        echo "错误：未找到 Nuitka 产物 .app（dist-nuitka/ 下无 .app）"; exit 1; }
    log "   产物名不符预期：$ALT → $APP"
    mv "$ALT" "$APP"
fi

log "[3.5/5] 包内 libpython 复核（shim 布局自足性，只读验证）"
# 架构师定案布局（源码实读 DllDependenciesMacOS/Standalone 4.2.1 推导）：
#   依赖 $PREFIX/lib/Python 经符号链接解析 → basename 拷入 Contents/MacOS/Python，
#   fixupBinaryDLLPathsMacOS 将主二进制依赖改写为 @executable_path/Python。
# 无需 post-build 改写/迁移/重签（Nuitka signDistributionMacOS 已 ad-hoc 签名）。
APP_EXE="$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
[ -x "$APP_EXE" ] || { echo "错误：包内可执行 $APP_EXE 缺失"; exit 1; }
if [ -f "$APP/Contents/MacOS/Python" ]; then
    log "   libpython 已在包内（经符号链接解析拷入）：Contents/MacOS/Python"
else
    log "   [WARN] 包内未见 Contents/MacOS/Python（deviations 记录）"
fi
log "   otool -L 复核（主二进制 libpython 依赖应无宿主绝对路径）："
otool -L "$APP_EXE" | grep -i "python" | sed 's/^/     /'
log "   codesign 状态："
codesign -dv "$APP" 2>&1 | sed 's/^/     /' | head -5

log "[3.7/5] Qt framework 布局重建（架构师 2026-09-07 实测定案）"
# Nuitka 4.2.1 pyqt6 插件不保留 .framework 布局（_isUsingMacOSFrameworks()
# 对 PyQt6 硬编码 False，PySidePyQtPlugin.py:219），Qt 6.11 静态初始化期
# CFBundleCopyBundleURL 遍历 .framework 失败 → NULL+8 SIGSEGV（crash report
# __CFCheckCFInfoPACSignature → CFBundleCopyBundleURL → QLibraryInfoPrivate::paths
# → QLoggingRegistry::instance → _GLOBAL__sub_I_qdarwinpermissionplugin_location.mm）。
# 修复：构建后将扁平 Qt dylib 重组为 .framework/Versions/A 布局 + 两级符号链接
# （Versions/Current→A、framework/Qt→Versions/Current/Qt）+ MacOS/Qt→framework/Qt
# 兼容符号链接（旧扁平 @executable_path/QtCore 引用仍可用）。
MACOS_DIR="$APP/Contents/MacOS"
QT_REBUILT=0
for qt_lib in "$MACOS_DIR"/Qt[A-Z]*; do
    [ -f "$qt_lib" ] || continue
    # 跳过 .so 文件（PyQt6 编译模块，非 Qt dylib）
    case "$qt_lib" in
        *.so|*.py) continue ;;
    esac
    # 跳过非 Mach-O（符号链接或数据文件）
    file "$qt_lib" 2>/dev/null | grep -q "Mach-O" || continue
    qt_name=$(basename "$qt_lib")
    fw_dir="$MACOS_DIR/${qt_name}.framework"
    # 幂等：已重建则跳过
    [ -d "$fw_dir/Versions/A" ] && continue
    mkdir -p "$fw_dir/Versions/A"
    mv "$qt_lib" "$fw_dir/Versions/A/$qt_name"
    # 注意：不创建 Versions/Current 和 framework/Qt 顶层符号链接
    # 架构师 2026-09-07 实测：codesign --force -s - 检测到 framework 顶层符号链接
    # 与 PyQt6 shallow framework 布局不一致 → "bundle format unrecognized" 拒签。
    # PyQt6 安装源（shallow 布局：Resources/+Versions/A/，无顶层符号链接）反而
    # 可被 codesign 识别为 bundle。dyld 经 @rpath/Qt.framework/Versions/A/Qt 解析。
    # 顶层 MacOS/Qt 兼容符号链接（@executable_path/Qt 旧式引用）改为直接指向
    # Versions/A/Qt，避开 framework 内符号链接又不破坏兼容性。
    (cd "$MACOS_DIR" && ln -s "${qt_name}.framework/Versions/A/${qt_name}" "$qt_name")
    # 拷贝 PyQt6 源 framework 的 Resources/（Info.plist + PrivacyInfo.xcprivacy）
    # 架构师 2026-09-07 实测：codesign 要求 framework bundle 含 Resources/Info.plist
    # 且 CFBundlePackageType=FMWK；缺 Resources → "bundle format unrecognized" 拒签。
    # 源在 PyQt6/Qt6/lib/<Qt>.framework/Resources，从 sys.path 推导或硬编码。
    PYQT6_LIB="$(python -c 'import PyQt6, os; print(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "lib"))' 2>/dev/null || true)"
    if [ -n "$PYQT6_LIB" ] && [ -d "$PYQT6_LIB/${qt_name}.framework/Resources" ]; then
        cp -R "$PYQT6_LIB/${qt_name}.framework/Resources" "$fw_dir/Resources"
    else
        # fallback：生成最小 Info.plist（FMWK 类型）
        mkdir -p "$fw_dir/Resources"
        cat > "$fw_dir/Resources/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
        <key>CFBundleDevelopmentRegion</key>
        <string>English</string>
        <key>CFBundleExecutable</key>
        <string>${qt_name}</string>
        <key>CFBundleIdentifier</key>
        <string>org.qt-project.${qt_name}</string>
        <key>CFBundleInfoDictionaryVersion</key>
        <string>6.0</string>
        <key>CFBundlePackageType</key>
        <string>FMWK</string>
        <key>CFBundleSignature</key>
        <string>????</string>
        <key>CFBundleVersion</key>
        <string>6.11.2</string>
        <key>CFBundleShortVersionString</key>
        <string>6.11</string>
        <key>CSResourcesFileMapped</key>
        <true/>
</dict>
</plist>
PLIST
    fi
    # 更新 install name 为 framework 式路径（@rpath 让 dyld 沿 rpath 解析）
    install_name_tool -id "@rpath/${qt_name}.framework/Versions/A/$qt_name" \
        "$fw_dir/Versions/A/$qt_name" 2>/dev/null || true
    # 单独签 framework（必做：mv 后签名失效；bundle 重签会嵌套签子组件）
    codesign --force -s - "$fw_dir" 2>/dev/null || true
    QT_REBUILT=$((QT_REBUILT + 1))
done
log "   重建 $QT_REBUILT 个 Qt framework（扁平→.framework/Versions/A + Resources + 兼容符号链接）"
# 添加 @executable_path 到主二进制 rpath（确保兼容符号链接可解析）
install_name_tool -add_rpath @executable_path "$APP_EXE" 2>/dev/null || true
# 重签（必做）：install_name_tool/mv 使 ad-hoc 签名失效 → 内核 code-signing monitor
# 启动即 SIGKILL（实测 'Killed: 9' + codesign -v 'invalid signature'，crash report
# 113909：dyld start 早期 __main__ 被杀）。bundle 签名会连带重签嵌套代码。
codesign --force -s - "$APP" 2>/dev/null \
    || { echo "错误：Qt 布局重建后重签失败"; exit 1; }
log "   重签后 codesign 验证：$(codesign -v "$APP" 2>&1 && echo OK || echo FAILED)"

log "[4/5] 体积实测（du -sk 逐级）"
du -sk "$APP"
du -sk "$APP"/Contents/*

log "[5/5] 可选 DMG（失败不阻塞主流程，deviations 记录）"
if ! {
    rm -rf "$DIST_DIR/dmg_staging"
    mkdir -p "$DIST_DIR/dmg_staging"
    cp -R "$APP" "$DIST_DIR/dmg_staging/"
    ln -s /Applications "$DIST_DIR/dmg_staging/Applications"
    hdiutil create -volname "AcouScope" -srcfolder "$DIST_DIR/dmg_staging" \
        -ov -format UDZO "$DMG"
    rm -rf "$DIST_DIR/dmg_staging"
    du -sk "$DMG"
  }; then
    echo "   [WARN] DMG 构建失败（不阻塞；deviations 记录）"
fi

log "完成：$APP"
