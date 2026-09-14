#!/usr/bin/env bash
#
# T-1058 fetch_ffmpeg.sh — 按需获取 macOS arm64 静态 ffmpeg
#
# 用途：AcouScope 仓库/安装包不含 ffmpeg 二进制（体积原因）。播放或导出
#       .mp3/.m4a 等非无损格式需要本地 ffmpeg。本脚本下载 → 校验 -> 安装到
#       acouscope/src/acouscope/resources/bin/ffmpeg 供 _get_ffmpeg_path() 三级回退命中。
#
# 特性：
#   * pin 版本 + 内置 sha256（zip 与二进制各一层校验）
#   * 已存在且二进制 sha256 一致 → 幂等跳过（退出 0）
#   * 网络失败 / 校验失败 / 解压失败 / 目录不可建 → 明确报错、非 0 退出并清理残留
#
set -euo pipefail

# ---- 常量（pin 的版本与哈希实测于 2026-09-14）----
# 源：OSXExperts.net static FFmpeg 8.0（Apple Silicon / arm64）
FFMPEG_ZIP_URL="https://www.osxexperts.net/ffmpeg80arm.zip"
FFMPEG_ZIP_SHA256="0d4efcaf6a098430a708e0af694a84792938921fa126162787ae98c6151d7a95"
FFMPEG_BIN_SHA256="77d2c853f431318d55ec02676d9b2f185ebfdddb9f7677a251fbe453affe025a"

# ---- 路径（由脚本位置推导,避免硬编码用户绝对路径）----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${SCRIPT_DIR}/../acouscope/src/acouscope/resources/bin"
TARGET="${TARGET_DIR}/ffmpeg"

TMP_DL="${TMPDIR:-/tmp}/ffmpeg80arm.zip.$$"
TMP_DIR="${TMPDIR:-/tmp}/ffmpeg_extract.$$"

cleanup() {
  rm -f "$TMP_DL"
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

say() { printf 'fetch_ffmpeg: %s\n' "$*"; }

# 幂等：目标已存在且二进制 sha256 一致 → 跳过
if [ -f "$TARGET" ] && [ -x "$TARGET" ]; then
  cur="$(shasum -a 256 "$TARGET" | awk '{print $1}')"
  if [ "$cur" = "$FFMPEG_BIN_SHA256" ]; then
    say "已存在且校验一致,跳过下载：$TARGET"
    exit 0
  fi
  say "已存在但二进制 sha256 不匹配（期望 ${FFMPEG_BIN_SHA256},实际 ${cur}）,将重新下载。"
fi

# 目标目录
if [ ! -d "$TARGET_DIR" ]; then
  if ! mkdir -p "$TARGET_DIR"; then
    say "错误：无法创建目标目录 $TARGET_DIR"
    exit 1
  fi
  say "已创建目标目录 $TARGET_DIR"
fi

# 下载
if ! curl -fsSL --retry 3 -o "$TMP_DL" "$FFMPEG_ZIP_URL"; then
  say "错误：下载失败 $FFMPEG_ZIP_URL"
  exit 1
fi

# 校验 zip sha256
dl="$(shasum -a 256 "$TMP_DL" | awk '{print $1}')"
if [ "$dl" != "$FFMPEG_ZIP_SHA256" ]; then
  say "错误：zip sha256 不匹配（期望 ${FFMPEG_ZIP_SHA256},实际 ${dl}）。已清理残留,退出非 0。"
  exit 1
fi
say "zip sha256 校验通过。"

# 解压
if ! mkdir -p "$TMP_DIR" || ! unzip -oq "$TMP_DL" -d "$TMP_DIR"; then
  say "错误：解压失败。"
  exit 1
fi
if [ ! -f "$TMP_DIR/ffmpeg" ]; then
  say "错误：压缩包内未找到 ffmpeg 二进制。"
  exit 1
fi

# 校验二进制 sha256（多一层防线,防 zip 内含被替换的二进制）
bdl="$(shasum -a 256 "$TMP_DIR/ffmpeg" | awk '{print $1}')"
if [ "$bdl" != "$FFMPEG_BIN_SHA256" ]; then
  say "错误：二进制 sha256 不匹配（期望 ${FFMPEG_BIN_SHA256},实际 ${bdl}）。已清理残留,退出非 0。"
  exit 1
fi

# 安装校验通过的二进制
if ! cp -f "$TMP_DIR/ffmpeg" "$TARGET" || ! chmod 755 "$TARGET"; then
  say "错误：安装到 $TARGET 失败。"
  exit 1
fi

trap - EXIT
rm -f "$TMP_DL"
rm -rf "$TMP_DIR"
say "安装完成：$TARGET"
say "提示：'brew install ffmpeg' 亦可作为替代来源。"