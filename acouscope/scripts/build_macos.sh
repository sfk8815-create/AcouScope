#!/bin/bash
# AcouScope macOS arm64 一键打包脚本
# 用法：bash scripts/build_macos.sh
# 产物：dist/AcouScope.app + dist/AcouScope-<pyproject version>-macOS-arm64.dmg

set -e
cd "$(dirname "$0")/.."

# ── 版本「单源化」（T-1043b）：唯一真值来源 = pyproject.toml 的 version ──────
# 与 AcouScope.spec 读取同一文件、同一正则；禁止在本脚本内写死版本号。
VERSION="$(.venv/bin/python - <<'PY'
import re
import sys

text = open("pyproject.toml", encoding="utf-8").read()
match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
if not match:
    sys.exit("无法从 pyproject.toml 解析 version（版本单源化失败）")
print(match.group(1))
PY
)"
[ -n "$VERSION" ] || { echo "错误：版本号为空"; exit 1; }
DMG_NAME="AcouScope-${VERSION}-macOS-arm64.dmg"
echo "==> 版本（真值来源 pyproject.toml）：$VERSION → $DMG_NAME"

# 运行中的 AcouScope 会锁定 dist 内文件导致删除失败，先退出
if pgrep -x AcouScope >/dev/null 2>&1; then
    echo "==> 检测到 AcouScope 正在运行，先退出应用..."
    osascript -e 'quit app "AcouScope"' 2>/dev/null || true
    sleep 2
    pkill -x AcouScope 2>/dev/null || true
    sleep 1
fi

echo "==> [1/3] PyInstaller 构建 .app"
# 注意：rm 失败不能直接终止脚本（set -e），否则走不到重试逻辑
rm -rf dist build/pyi_work 2>/dev/null || true
for i in 1 2 3 4 5; do
    [ ! -d dist ] && break
    echo "   dist 被占用，等待重试 ($i/5)..."
    sleep 2
    rm -rf dist 2>/dev/null || true
done
if [ -d dist ]; then
    echo "错误：dist 仍被占用，占用进程如下："
    lsof +D dist 2>/dev/null | head -5
    echo "请退出上述进程（或重启 Finder）后重试"
    exit 1
fi
PYINSTALLER_CONFIG_DIR="$PWD/build/pyi_cache" .venv/bin/python -m PyInstaller \
    AcouScope.spec --noconfirm --clean \
    --workpath build/pyi_work --distpath dist

echo "==> [2/3] 创建 DMG"
rm -rf dist/dmg_staging
mkdir -p dist/dmg_staging
cp -R dist/AcouScope.app dist/dmg_staging/
ln -s /Applications dist/dmg_staging/Applications
hdiutil create -volname "AcouScope" \
    -srcfolder dist/dmg_staging -ov -format UDZO \
    "dist/${DMG_NAME}"
rm -rf dist/dmg_staging

echo "==> [3/3] 完成"
du -sh dist/AcouScope.app "dist/${DMG_NAME}"
