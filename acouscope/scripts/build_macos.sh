#!/bin/bash
# AcouScope macOS arm64 一键打包脚本
# 用法：bash scripts/build_macos.sh
# 产物：dist/AcouScope.app + dist/AcouScope-0.98.20160830-macOS-arm64.dmg

set -e
cd "$(dirname "$0")/.."

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
    dist/AcouScope-0.98.20160830-macOS-arm64.dmg
rm -rf dist/dmg_staging

echo "==> [3/3] 完成"
du -sh dist/AcouScope.app dist/AcouScope-0.98.20160830-macOS-arm64.dmg
