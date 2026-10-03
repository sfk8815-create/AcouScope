#!/bin/bash
# fetch_ollama.sh — AcouScope 内置 Ollama 引擎整套资产：下载 / sha256 硬校验 / 解压落位
#
# 用法:
#   ./scripts/fetch_ollama.sh [平台] [目标目录]
#     平台        darwin-arm64（先行，官方 tgz 为 universal2，arm64/x64 均可运行）
#                 windows-amd64 / linux-amd64 预留位（未开放，属后续任务）
#     目标目录    默认 <repo>/acouscope/src/acouscope/resources/bin/ollama
#
# 裁决 B（项目负责人 2026-09-09）：assets 整套不入 git（.gitignore），由本脚本在
# 开发机/构建机落位；仅 BUNDLE_INFO.txt 登记文件例外入库。
#
# ⚠ 整套同目录铁律：ollama serve 按 @loader_path 在同目录找 llama-server /
#   libllama* / libggml* / libmtmd* / mlx_metal_v3 / mlx_metal_v4，禁止单独替换
#   或删除其中任何文件——升级/回滚必须整套替换。本脚本落位前会整体重建目标目录。
#
# sha256 与官方 releases/download/v0.33.3/sha256sum.txt 比对后写入（2026-09-09
# 实测核对，禁臆造；升级版本时须重新从官方 sha256sum.txt 抄录并同步 BUNDLE_INFO）。

set -euo pipefail

# sha256 工具（macOS=shasum，Linux=sha256sum）；须定义于调用前（脚本顺序执行）
_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    sha256sum "$1" | cut -d' ' -f1
  fi
}

OLLAMA_VERSION="0.33.3"
BASE_URL="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}"

case "${1:-darwin-arm64}" in
  darwin-arm64)
    ASSET="ollama-darwin.tgz"
    SHA256="342db03df80bb9db84ff64246031bd5f70c09b59ff52fa5cc9aaae3476cc4a9d"
    ;;
  *)
    echo "错误: 暂不支持平台 '${1}'（当前仅 darwin-arm64；其余平台属后续任务）" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${2:-${SCRIPT_DIR}/../src/acouscope/resources/bin/ollama}"

echo "[1/5] 目标目录: ${TARGET}"
rm -rf "${TARGET}"
mkdir -p "${TARGET}"

echo "[2/5] 下载 ${BASE_URL}/${ASSET}（已缓存且校验一致则复用）"
# 缓存候选：$TMPDIR 与 /tmp 都找（macOS TMPDIR 为 /var/folders/...，历史缓存常在 /tmp）
TGZ=""
for d in "${TMPDIR:-/tmp}" "/tmp"; do
  if [ -f "${d}/${ASSET}" ] && [ "$(_sha256 "${d}/${ASSET}")" = "${SHA256}" ]; then
    TGZ="${d}/${ASSET}"
    break
  fi
done
if [ -n "${TGZ}" ]; then
  echo "  缓存命中: ${TGZ}"
else
  TGZ="${TMPDIR:-/tmp}/${ASSET}"
  curl -fL --retry 3 -o "${TGZ}.part" "${BASE_URL}/${ASSET}"
  ACTUAL="$(_sha256 "${TGZ}.part")"
  if [ "${ACTUAL}" != "${SHA256}" ]; then
    echo "错误: sha256 不一致，弃用（禁强用）" >&2
    echo "  期望: ${SHA256}" >&2
    echo "  实际: ${ACTUAL}" >&2
    rm -f "${TGZ}.part"
    exit 3
  fi
  mv "${TGZ}.part" "${TGZ}"
fi

echo "[3/5] 最终校验 sha256"
ACTUAL="$(_sha256 "${TGZ}")"
[ "${ACTUAL}" = "${SHA256}" ] || { echo "错误: sha256 不一致" >&2; exit 3; }
echo "  ${SHA256}  ✓"

echo "[4/5] 解压落位（tar 原样：保留执行位与 symlink，平铺 57 项）"
tar -xzf "${TGZ}" -C "${TARGET}"
for bin in ollama llama-server llama-quantize; do
  if [ -f "${TARGET}/${bin}" ]; then
    chmod +x "${TARGET}/${bin}"
  else
    echo "错误: 解压后缺关键文件 ${bin}" >&2
    exit 4
  fi
done

echo "[5/5] 生成 BUNDLE_INFO.txt + 关键结构自检"
cat > "${TARGET}/BUNDLE_INFO.txt" <<EOF
AcouScope 内置 Ollama 引擎资产（T-317 落位 · 裁决 B：不入 git）
================================================================

版本：        ollama v${OLLAMA_VERSION}（官方 release，macOS universal2，arm64 可用）
来源：        ${BASE_URL}/${ASSET}
tgz sha256：  ${SHA256}
              （与官方 releases/download/v${OLLAMA_VERSION}/sha256sum.txt 同源比对一致）
下载日期：    $(date +%F)
落位方式：    scripts/fetch_ollama.sh darwin-arm64（下载 + sha256 硬校验 + 解压落位，可复用）
入库方式：    本目录整套不入 git（.gitignore；仅本登记文件例外入库）

⚠ 整套同目录铁律：ollama serve 按 @loader_path 相对路径在同目录查找
  llama-server / libllama* / libggml* / libmtmd* / mlx_metal_v3 / mlx_metal_v4。
  禁止单独替换或删除其中任何一个文件——整套同目录才可 serve。
  升级/回滚必须整套替换（bundled 为出厂只读基准，版本随 AcouScope 发版焊死；
  用户级引擎升级/回滚属后续独立任务 T-319）。

关键内容清单（tar 原样，保持执行位与 symlink）：
  ollama / llama-server / llama-quantize（可执行）
  libllama* / libggml* / libmtmd* dylib（含版本号实体 + 多级 symlink）
  mlx_metal_v3/ 与 mlx_metal_v4/（各含 mlx.metallib + libmlx/libjaccl/libollama_xgrammar）
  GO_LICENSE / LLAMA_CPP_LICENSE / MLX_LICENSE / XGRAMMAR_LICENSE 等全套许可文本
EOF
for d in mlx_metal_v3 mlx_metal_v4; do
  [ -d "${TARGET}/${d}" ] || { echo "错误: 缺 ${d}/ 目录" >&2; exit 4; }
done

echo "完成：${TARGET}/ollama v${OLLAMA_VERSION}（$(du -sh "${TARGET}" | cut -f1)）"
echo "冒烟（手工执行，不入 pytest）: ${TARGET}/ollama --version"

