#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-only
// 项目同款许可证头（Python 首行写法）：# SPDX-License-Identifier: GPL-3.0-only
//
// T09 24-bit WAV 跨语言独立验证（开发期跨语言验证件，不是 Python 运行时依赖）。
// 用法： node verify_wav24_node.mjs <path.wav>
//
//   路①：Node 内置 fs 手工解析 RIFF / "fmt " / "data"，断言 PCM/单声道/24-bit，
//         把每帧 3 字节小端符号扩展成 int32 数组。
//   路②：从 NODE_PATH 加载 wavefile@11 的 WaveFile 读同一文件，校验位深 24，
//         用 getSamples() 换算成 int24 与路①逐样本比较。
//   成功：stdout 输出单行 JSON（PASS=true）；wavefile 不可用：打印
//         WAVEFILE_UNAVAILABLE 并退出 2；maxDelta>1：退出 3。

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const INT24_SCALE = 8388608; // 2 ** 23

function die(message, code) {
  // 失败信息走 stderr，保证成功路径 stdout 是唯一一行 JSON
  process.stderr.write(message + '\n');
  process.exit(code);
}

// ---------------------------------------------------------------------------
// 路①：原生 fs 解析 RIFF / WAVE
// ---------------------------------------------------------------------------
function readRiff24(buffer) {
  if (buffer.length < 12 ||
      buffer.toString('ascii', 0, 4) !== 'RIFF' ||
      buffer.toString('ascii', 8, 12) !== 'WAVE') {
    die('NOT_RIFF_WAVE', 4);
  }
  let off = 12;
  let fmt = null;
  let data = null;
  while (off + 8 <= buffer.length) {
    const id = buffer.toString('ascii', off, off + 4);
    const size = buffer.readUInt32LE(off + 4);
    const body = off + 8;
    if (body + size > buffer.length) {
      die('TRUNCATED_CHUNK', 4);
    }
    if (id === 'fmt ') {
      if (size < 16) die('SHORT_FMT_CHUNK', 4);
      fmt = {
        audioFormat: buffer.readUInt16LE(body),
        numChannels: buffer.readUInt16LE(body + 2),
        sampleRate: buffer.readUInt32LE(body + 4),
        byteRate: buffer.readUInt32LE(body + 8),
        blockAlign: buffer.readUInt16LE(body + 12),
        bitsPerSample: buffer.readUInt16LE(body + 14),
      };
    } else if (id === 'data') {
      data = { offset: body, size };
      break;
    }
    // RIFF chunk 以偶数字节对齐
    off = body + size + (size % 2);
  }
  if (!fmt) die('MISSING_FMT_CHUNK', 4);
  if (!data) die('MISSING_DATA_CHUNK', 4);
  // 硬断言：audioFormat=1 (PCM)、numChannels=1、bitsPerSample=24
  if (fmt.audioFormat !== 1 || fmt.numChannels !== 1 || fmt.bitsPerSample !== 24) {
    die('FMT_ASSERT_FAILED ' + JSON.stringify(fmt), 4);
  }
  const frames = Math.floor(data.size / 3);
  const samples = new Int32Array(frames);
  for (let i = 0; i < frames; i++) {
    const p = data.offset + i * 3;
    let v = buffer[p] | (buffer[p + 1] << 8) | (buffer[p + 2] << 16);
    if (v >= (1 << 23)) v -= (1 << 24); // 3 字节小端符号扩展
    samples[i] = v;
  }
  return { fmt, frames, samples };
}

// ---------------------------------------------------------------------------
// 路②：从 NODE_PATH 加载 wavefile@11（加载失败禁静默通过）
// ---------------------------------------------------------------------------
function loadWaveFile() {
  // 只在 NODE_PATH 列出的目录里解析，父链上的任何同名包都不参与，
  // 保证负对照（NODE_PATH 指向空目录）必然 MODULE_NOT_FOUND。
  const searchPaths = String(process.env.NODE_PATH || '')
    .split(path.delimiter)
    .filter(Boolean);
  let resolved;
  try {
    resolved = require.resolve('wavefile', { paths: searchPaths });
  } catch (err) {
    process.stdout.write('WAVEFILE_UNAVAILABLE ' + (err.code || err.message) + '\n');
    process.exit(2);
  }
  try {
    const mod = require(resolved);
    return mod.WaveFile || mod.default || mod;
  } catch (err) {
    process.stdout.write('WAVEFILE_UNAVAILABLE ' + (err.code || err.message) + '\n');
    process.exit(2);
  }
}

function wavefileInt24(WaveFile, buffer) {
  const wave = new WaveFile(buffer);
  // wavefile@11 把位深放在 fmt.bitsPerSample / 顶层 bitDepth；
  // fmt.bitDepth 为兼容字段（部分版本提供）。三者任一为 24 即通过。
  const depth = wave.fmt.bitDepth != null
    ? wave.fmt.bitDepth
    : (wave.bitDepth != null ? wave.bitDepth : wave.fmt.bitsPerSample);
  if (Number(depth) !== 24) {
    die('WAVEFILE_BITDEPTH_NOT_24 ' + String(depth), 3);
  }
  const raw = wave.getSamples();
  const flat = Array.isArray(raw[0]) ? raw[0] : raw;
  // wavefile@11 对 24-bit PCM 的 getSamples() 返回 int24 整数；若某后端
  // 返回 [-1,1] 归一化浮点，则按 2**23 还原成 int24。
  let peak = 0;
  for (let i = 0; i < flat.length; i++) {
    const a = Math.abs(flat[i]);
    if (a > peak) peak = a;
  }
  const scale = peak <= 1.0 + 1e-9 ? INT24_SCALE : 1;
  const int24 = new Int32Array(flat.length);
  for (let i = 0; i < flat.length; i++) {
    int24[i] = Math.round(flat[i] * scale);
  }
  return { depth: Number(depth), int24 };
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
const wavPath = process.argv[2];
if (!wavPath) die('USAGE: node verify_wav24_node.mjs <path.wav>', 4);

const buffer = fs.readFileSync(wavPath);
const a = readRiff24(buffer);
const WaveFile = loadWaveFile();
const b = wavefileInt24(WaveFile, buffer);

if (a.frames !== b.int24.length) {
  die('FRAME_COUNT_MISMATCH ' + a.frames + ' vs ' + b.int24.length, 3);
}
let maxDelta = 0;
for (let i = 0; i < a.frames; i++) {
  const d = Math.abs(a.samples[i] - b.int24[i]);
  if (d > maxDelta) maxDelta = d;
}
if (maxDelta > 1) {
  die('MAX_DELTA_EXCEEDS_1LSB ' + maxDelta, 3);
}

process.stdout.write(JSON.stringify({
  bitsPerSample: a.fmt.bitsPerSample,
  sampleRate: a.fmt.sampleRate,
  frames: a.frames,
  wavefileBitDepth: b.depth,
  maxDelta,
  PASS: true,
}) + '\n');
