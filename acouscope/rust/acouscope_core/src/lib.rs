//! acouscope_core -- T-1061a build-chain scaffold (trivial primitive, no heavy deps).
//! T-1062a R1: YIN 基元四函数原生化（逐位复刻 analysis/pyin.py :23-86）。
use pyo3::exceptions::{PyOverflowError, PyTypeError};
use pyo3::prelude::*;
use numpy::{PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray1, PyReadonlyArray2};

/// G2 primitive: deterministic integer addition (no float, no IO).
#[pyfunction]
fn sum_i64(a: i64, b: i64) -> i64 {
    a + b
}

/// A/B switch sentinel: neutral, deterministic, side-effect free.
#[pyfunction]
fn native_selfcheck() -> i64 {
    1997
}

// ---- T-1062a R1: YIN 基元四函数（手写 radix-2 FFT 复刻 numpy 的 FFT 互相关路径）----

/// 最小 >= v 的 2 的幂（对应 Python: 1 << ceil(log2(v))）。
fn next_pow2(v: usize) -> usize {
    let mut p = 1usize;
    while p < v {
        p <<= 1;
    }
    p
}

/// 就地 radix-2 Cooley-Tukey FFT（迭代 + 蝶形递推旋转因子）。归一化由调用方处理。
fn fft_inplace(re: &mut [f64], im: &mut [f64], inverse: bool) {
    let n = re.len();
    if n <= 1 {
        return;
    }
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j |= bit;
        if i > j {
            re.swap(i, j);
            im.swap(i, j);
        }
    }
    let mut len = 2usize;
    while len <= n {
        let ang = if inverse {
            2.0 * std::f64::consts::PI / len as f64
        } else {
            -2.0 * std::f64::consts::PI / len as f64
        };
        let (wlr, wli) = (ang.cos(), ang.sin());
        let half = len / 2;
        let mut i = 0usize;
        while i < n {
            let (mut wr, mut wi) = (1.0f64, 0.0f64);
            for k in 0..half {
                let a = i + k;
                let b = a + half;
                let xr = re[a];
                let xi = im[a];
                let yr = re[b] * wr - im[b] * wi;
                let yi = re[b] * wi + im[b] * wr;
                re[a] = xr + yr;
                im[a] = xi + yi;
                re[b] = xr - yr;
                im[b] = xi - yi;
                let nwr = wr * wlr - wi * wli;
                wi = wr * wli + wi * wlr;
                wr = nwr;
            }
            i += len;
        }
        len <<= 1;
    }
}

/// 实序列 x（取前 out_len 个，零填充至 nfft）的 rfft，返回 nfft/2+1 个复数（re/im 分列）。
fn rfft_padded(x: &[f64], out_len: usize, nfft: usize) -> (Vec<f64>, Vec<f64>) {
    let mut re = vec![0.0f64; nfft];
    let mut im = vec![0.0f64; nfft];
    for (dst, src) in re.iter_mut().zip(x.iter().take(out_len)) {
        *dst = *src;
    }
    fft_inplace(&mut re, &mut im, false);
    let m = nfft / 2 + 1;
    re.truncate(m);
    im.truncate(m);
    (re, im)
}

/// YIN 差分函数 d(tau), tau = 0..W（W = len(frame)//2），FFT 互相关法。
#[pyfunction]
fn difference_function<'py>(
    py: Python<'py>,
    frame: PyReadonlyArray1<'py, f64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let x = frame.as_array().to_vec();
    let n = x.len();
    if n == 0 {
        // 复刻 Python: 1 << int(np.ceil(np.log2(0))) => log2(0)=-inf => OverflowError
        return Err(PyOverflowError::new_err(
            "cannot convert float infinity to integer",
        ));
    }
    let w = n / 2;
    let nfft = next_pow2(n + w);
    let (fa_re, fa_im) = rfft_padded(&x, w, nfft);
    let (fb_re, fb_im) = rfft_padded(&x, n, nfft);
    let m = fa_re.len(); // nfft/2 + 1
    // prod = conj(fa) * fb
    let mut pr = vec![0.0f64; m];
    let mut pim = vec![0.0f64; m];
    for k in 0..m {
        pr[k] = fa_re[k] * fb_re[k] + fa_im[k] * fb_im[k];
        pim[k] = fa_re[k] * fb_im[k] - fa_im[k] * fb_re[k];
    }
    // irfft：重建 Hermitian 谱后做逆 FFT（含 1/N）
    let mut re = vec![0.0f64; nfft];
    let mut im = vec![0.0f64; nfft];
    for k in 0..m {
        re[k] = pr[k];
        im[k] = pim[k];
    }
    for k in 1..nfft / 2 {
        re[nfft - k] = pr[k];
        im[nfft - k] = -pim[k];
    }
    fft_inplace(&mut re, &mut im, true);
    let inv = 1.0 / nfft as f64;
    // power = [0.0] + cumsum(x*x)（顺序累加，与 np.cumsum 同序）
    let mut power = vec![0.0f64; n + 1];
    let mut acc = 0.0f64;
    for i in 0..n {
        acc += x[i] * x[i];
        power[i + 1] = acc;
    }
    let e_head = power[w] - power[0];
    let mut d = vec![0.0f64; w + 1];
    for t in 0..=w {
        let corr = re[t] * inv;
        let e_shift = power[w + t] - power[t];
        let v = e_head + e_shift - 2.0 * corr;
        // np.maximum(v, 0.0)：NaN 传播
        d[t] = if v.is_nan() || v > 0.0 { v } else { 0.0 };
    }
    Ok(PyArray1::from_vec(py, d))
}

/// 累计均值归一化 d'(tau) = d(tau) * tau / sum_{j=1..tau} d(j)（tau=0 处为 1）。
#[pyfunction]
fn cumulative_mean_normalized<'py>(
    py: Python<'py>,
    d: PyReadonlyArray1<'py, f64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let dv = d.as_array().to_vec();
    let w = dv.len();
    let mut dnorm = vec![1.0f64; w];
    if w > 1 {
        let mut acc = 0.0f64;
        for t in 1..w {
            acc += dv[t];
            let denom = if acc > 1e-20 { acc } else { 1e-20 };
            let tt = t as f64;
            dnorm[t] = dv[t] * tt / denom;
        }
    }
    Ok(PyArray1::from_vec(py, dnorm))
}

/// [tau_min, tau_max) 内 d' 的局部谷底索引（谷值 < 左邻 且 <= 右邻），返回 int64。
#[pyfunction]
fn local_minima<'py>(
    py: Python<'py>,
    dnorm: PyReadonlyArray1<'py, f64>,
    tau_min: i64,
    tau_max: i64,
) -> PyResult<Bound<'py, PyArray1<i64>>> {
    let dv = dnorm.as_array().to_vec();
    let size = dv.len() as i64;
    let lo = if tau_min > 1 { tau_min } else { 1 };
    let hi = if tau_max < size - 1 { tau_max } else { size - 1 };
    if hi - lo < 2 {
        return Ok(PyArray1::from_vec(py, Vec::<i64>::new()));
    }
    let mut out = Vec::new();
    for g in lo..hi {
        let gi = g as usize;
        if dv[gi] < dv[gi - 1] && dv[gi] <= dv[gi + 1] {
            out.push(g);
        }
    }
    Ok(PyArray1::from_vec(py, out))
}

/// 抛物线插值细化周期（亚采样精度），返回 Python float。
#[pyfunction]
fn parabolic_interpolate(dnorm: PyReadonlyArray1<'_, f64>, tau: i64) -> f64 {
    let dv = dnorm.as_array();
    let size = dv.len() as i64;
    // IM-28 (B) CMNDF 反倾斜：三点各除自身 tau 因子（与 Python 侧逐字同式）。
    if tau <= 1 || tau >= size - 1 {
        return tau as f64;
    }
    let t = tau as usize;
    let (a, b, c) = (
        dv[t - 1] / (tau - 1) as f64,
        dv[t] / tau as f64,
        dv[t + 1] / (tau + 1) as f64,
    );
    let denom = 2.0 * (a - 2.0 * b + c);
    if denom.abs() < 1e-12 {
        return tau as f64;
    }
    let mut delta = (a - c) / denom;
    if delta < -1.0 {
        delta = -1.0;
    } else if delta > 1.0 {
        delta = 1.0;
    }
    tau as f64 + delta
}

// ---- T-1062b R2: Beta CDF 三函数（R-2 路线 (b)：复刻 CPython m_lgamma）----
// 来源：CPython Modules/mathmodule.c（v3.10.20）的 m_lgamma / lanczos_sum / m_sinpi
//   及常量 pi / logpi / lanczos_g —— 逐字抄录其 C 实现为 Rust（纯 +-*/＋多项式，
//   无 extern 系统绑定、无 libm crate）⇒ 与 Python math.lgamma 逐位等价，
//   使 _beta_cdf/_beta_cdf_arr 与 math 版逐位一致（判据② 逐位档）。
// 注：v3.10.20 的 m_lgamma 无 __APPLE__ 特例分支（grep APPLE = 0 命中），故整函数照抄；
//   仅省略 C 版的 errno 副作用（本件为纯函数；非正参数的 ValueError 语义在 _beta_cdf(a,b>0) 不可达）。

const LANCZOS_N: usize = 13;
const LANCZOS_G: f64 = 6.024680040776729583740234375;
const LOGPI: f64 = 1.144729885849400174143427351353058711647;
const PI: f64 = 3.141592653589793238462643383279502884197;

const LANCZOS_NUM_COEFFS: [f64; LANCZOS_N] = [
    23531376880.410759688572007674451636754734846804940,
    42919803642.649098768957899047001988850926355848959,
    35711959237.355668049440185451547166705960488635843,
    17921034426.037209699919755754458931112671403265390,
    6039542586.3520280050642916443072979210699388420708,
    1439720407.3117216736632230727949123939715485786772,
    248874557.86205415651146038641322942321632125127801,
    31426415.585400194380614231628318205362874684987640,
    2876370.6289353724412254090516208496135991145378768,
    186056.26539522349504029498971604569928220784236328,
    8071.6720023658162106380029022722506138218516325024,
    210.82427775157934587250973392071336271166969580291,
    2.5066282746310002701649081771338373386264310793408,
];

/// 分母 = x*(x+1)*...*(x+LANCZOS_N-2)。
const LANCZOS_DEN_COEFFS: [f64; LANCZOS_N] = [
    0.0, 39916800.0, 120543840.0, 150917976.0, 105258076.0, 45995730.0, 13339535.0, 2637558.0,
    357423.0, 32670.0, 1925.0, 66.0, 1.0,
];

/// Lanczos 和 L_g(x)（正 x）：C 版 lanczos_sum 的逐字复刻（两分支求值顺序一致）。
fn lanczos_sum(x: f64) -> f64 {
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    if x < 5.0 {
        // C: for (i = LANCZOS_N; --i >= 0; ) ⇒ 自高次系数向低次（Horner）
        // ★ FMA 收缩：本机 CPython(3.10.20/arm64) 的 math.lgamma 由 clang -ffp-contract=on
        //   编译 ⇒ `num = num*x + coeff` 被收缩为 fma(num,x,coeff)；实测（823 采样点）
        //   唯 mul_add 版与 math.lgamma 逐位一致 ⇒ 用 mul_add 复现编译后行为。
        for i in (0..LANCZOS_N).rev() {
            num = num.mul_add(x, LANCZOS_NUM_COEFFS[i]);
            den = den.mul_add(x, LANCZOS_DEN_COEFFS[i]);
        }
    } else {
        for i in 0..LANCZOS_N {
            num = num / x + LANCZOS_NUM_COEFFS[i];
            den = den / x + LANCZOS_DEN_COEFFS[i];
        }
    }
    num / den
}

/// sin(pi*x)（仅有限参数）：C 版 m_sinpi 的逐字复刻（供 m_lgamma 负参数反射支）。
fn m_sinpi(x: f64) -> f64 {
    let y = x.abs() % 2.0; // fmod(fabs(x), 2.0)
    let n = (2.0 * y).round() as i32;
    let r = match n {
        0 => (PI * y).sin(),
        1 => (PI * (y - 0.5)).cos(),
        2 => (PI * (1.0 - y)).sin(),
        3 => -(PI * (y - 1.5)).cos(),
        4 => (PI * (y - 2.0)).sin(),
        _ => f64::NAN,
    };
    (1.0f64).copysign(x) * r
}

/// log|Gamma(x)|：CPython m_lgamma 的逐字复刻（纯函数，省略 C 版 errno 副作用）。
fn m_lgamma(x: f64) -> f64 {
    // special cases
    if !x.is_finite() {
        return if x.is_nan() { x } else { f64::INFINITY };
    }
    // integer arguments
    if x == x.floor() && x <= 2.0 {
        return if x <= 0.0 { f64::INFINITY } else { 0.0 };
    }
    let absx = x.abs();
    // tiny arguments: lgamma(x) ~ -log(fabs(x)) for small x
    if absx < 1e-20 {
        return -absx.ln();
    }
    // Lanczos' formula
    let mut r = lanczos_sum(absx).ln() - LANCZOS_G;
    // C: r += (absx-0.5) * (log(absx+lanczos_g-0.5) - 1) ⇒ 同一 FMA 收缩
    r = (absx - 0.5).mul_add((absx + LANCZOS_G - 0.5).ln() - 1.0, r);
    if x < 0.0 {
        // reflection formula for negative x
        r = LOGPI - m_sinpi(absx).abs().ln() - absx.ln() - r;
    }
    r
}

/// 正则化不完全 Beta 的连分式核（Lentz 加速收敛）：逐位复刻 `analysis/pyin.py:_betacf`。
#[pyfunction]
#[pyo3(signature = (a, b, x, max_iter = 300))]
fn _betacf(a: f64, b: f64, x: f64, max_iter: i64) -> f64 {
    let tiny = 1e-300;
    let (qab, qap, qam) = (a + b, a + 1.0, a - 1.0);
    let mut c = 1.0f64;
    let mut d = 1.0 - qab * x / qap;
    if d.abs() < tiny {
        d = tiny;
    }
    d = 1.0 / d;
    let mut h = d;
    let mut m = 1i64;
    while m <= max_iter {
        let mf = m as f64;
        let m2 = (2 * m) as f64;
        let mut aa = mf * (b - mf) * x / ((qam + m2) * (a + m2));
        d = 1.0 + aa * d;
        if d.abs() < tiny {
            d = tiny;
        }
        c = 1.0 + aa / c;
        if c.abs() < tiny {
            c = tiny;
        }
        d = 1.0 / d;
        h *= d * c;
        aa = -(a + mf) * (qab + mf) * x / ((a + m2) * (qap + m2));
        d = 1.0 + aa * d;
        if d.abs() < tiny {
            d = tiny;
        }
        c = 1.0 + aa / c;
        if c.abs() < tiny {
            c = tiny;
        }
        d = 1.0 / d;
        let delta = d * c;
        h *= delta;
        if (delta - 1.0).abs() < 3e-16 {
            break;
        }
        m += 1;
    }
    h
}

/// Beta(a, b) 分布 CDF = I_x(a, b)：逐位复刻 `analysis/pyin.py:_beta_cdf`
/// （端点 + m_lgamma 前因式 + 对称分支）。
#[pyfunction]
fn _beta_cdf(x: f64, a: f64, b: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    if x >= 1.0 {
        return 1.0;
    }
    let ln_front = m_lgamma(a + b) - m_lgamma(a) - m_lgamma(b) + a * x.ln() + b * (1.0 - x).ln();
    let front = ln_front.exp();
    if x < (a + 1.0) / (a + b + 2.0) {
        return front * _betacf(a, b, x, 300) / a;
    }
    1.0 - front * _betacf(b, a, 1.0 - x, 300) / b
}

/// Beta CDF 的逐元素版本：逐位复刻 `analysis/pyin.py:_beta_cdf_arr`
/// （标量循环；返回 float64 一维数组）。
#[pyfunction]
fn _beta_cdf_arr<'py>(
    py: Python<'py>,
    xs: PyReadonlyArray1<'py, f64>,
    a: f64,
    b: f64,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let out: Vec<f64> = xs.as_array().iter().map(|&v| _beta_cdf(v, a, b)).collect();
    Ok(PyArray1::from_vec(py, out))
}

// ---- T-1062c R3: pYIN 单帧候选层 pyin_frame（逐字复刻 analysis/pyin.py:180-246）----
// 组合纪律：仅调用本 crate 的 R1/R2 基元（Rust 版，同 crate 内直接调用），
//   禁经 PyO3 回调 Python 侧同名函数。
// 逐字复刻项（含 AT-1007 刀口「次谐波幽灵抑制」分支 + v2 补三句）：
//   · local_minima(dnorm, tau_min, tau_max + 1) 第三参 +1
//   · total = probs.sum() 在过滤环之前（不裁 total）
//   · candidates.sort(key=-prob) 为 Python 稳定排序 ⇒ 用 sort_by（非 sort_unstable_by）

/// `np.round` 的银行家舍入（round-half-to-even），逐位对齐 numpy 语义。
fn np_round(v: f64) -> f64 {
    let f = v.floor();
    let d = v - f;
    if d > 0.5 {
        f + 1.0
    } else if d < 0.5 {
        f
    } else if f % 2.0 == 0.0 {
        f
    } else {
        f + 1.0
    }
}

/// `np.maximum` 的标量语义（NaN 传播）。
fn np_maximum(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else if a > b {
        a
    } else {
        b
    }
}

/// `np.minimum` 的标量语义（NaN 传播）。
fn np_minimum(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else if a < b {
        a
    } else {
        b
    }
}

/// `np.clip(x, lo, hi)` 的标量语义（NaN 传播：clip(NaN) = NaN）。
fn np_clip(x: f64, lo: f64, hi: f64) -> f64 {
    if x.is_nan() {
        x
    } else if x < lo {
        lo
    } else if x > hi {
        hi
    } else {
        x
    }
}

/// `np.ndarray.sum()` 的 pairwise 求和复刻（n<8 顺序；n<=128 八路展开；
/// 否则二分递归），逐位对齐 numpy 的浮点求和次序
/// （numpy/core/src/umath/loops_utils.h.src，PW_BLOCKSIZE = 128）。
fn pairwise_sum(a: &[f64]) -> f64 {
    const PW_BLOCKSIZE: usize = 128;
    let n = a.len();
    if n < 8 {
        let mut res = 0.0f64;
        for v in a {
            res += *v;
        }
        return res;
    }
    if n <= PW_BLOCKSIZE {
        let mut r = [0.0f64; 8];
        r.copy_from_slice(&a[0..8]);
        let mut i = 8usize;
        while i < n - (n % 8) {
            for k in 0..8 {
                r[k] += a[i + k];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n {
            res += a[i];
            i += 1;
        }
        return res;
    }
    let mut n2 = n / 2;
    n2 -= n2 % 8;
    pairwise_sum(&a[..n2]) + pairwise_sum(&a[n2..])
}

/// 单帧概率化 YIN（pYIN 候选层），返回 `(candidates, voiced_prob)`。
/// 逐字复刻 `analysis/pyin.py::pyin_frame`（含刀口分支全部分支）。
#[pyfunction]
#[pyo3(signature = (frame, sr, fmin = 40.0, fmax = 2000.0, beta_mean = 0.15, beta_a = 2.0))]
fn pyin_frame(
    frame: numpy::PyReadonlyArray1<'_, f64>,
    sr: f64,
    fmin: f64,
    fmax: f64,
    beta_mean: f64,
    beta_a: f64,
) -> (Vec<(f64, f64)>, f64) {
    let x: Vec<f64> = frame.as_array().iter().copied().collect();
    Python::attach(|py| {
        // d = difference_function(frame)
        let frame_arr = PyArray1::from_vec(py, x);
        let d = difference_function(py, frame_arr.readonly())
            .expect("difference_function failed");
        // dnorm = cumulative_mean_normalized(d)
        let dnorm = cumulative_mean_normalized(py, d.readonly())
            .expect("cumulative_mean_normalized failed");
        let dnorm_v: Vec<f64> = dnorm.readonly().as_array().iter().copied().collect();
        let size = dnorm_v.len() as i64;
        // tau_min = max(2, int(sr / fmax)) · tau_max = min(dnorm.size - 2, int(sr / fmin))
        let tau_min = std::cmp::max(2i64, (sr / fmax) as i64);
        let tau_max = std::cmp::min(size - 2, (sr / fmin) as i64);
        if tau_max <= tau_min + 2 {
            return (Vec::new(), 0.0);
        }
        // minima = local_minima(dnorm, tau_min, tau_max + 1)  ← 第三参 +1（逐字）
        let mut minima: Vec<i64> = local_minima(py, dnorm.readonly(), tau_min, tau_max + 1)
            .expect("local_minima failed")
            .readonly()
            .as_array()
            .to_vec();
        if minima.is_empty() {
            return (Vec::new(), 0.0);
        }
        // ---- 次谐波幽灵抑制（AT-07-3 刀口分支 · 逐字复刻）----
        // deep = local_minima(dnorm, 2, dnorm.size - 2); deep = deep[dnorm[deep] < 0.1]
        let deep: Vec<i64> = local_minima(py, dnorm.readonly(), 2, size - 2)
            .expect("local_minima failed")
            .readonly()
            .as_array()
            .iter()
            .copied()
            .filter(|&g| dnorm_v[g as usize] < 0.1)
            .collect();
        if !deep.is_empty() && sr / (deep[0] as f64) > fmax {
            let tau1 = parabolic_interpolate(dnorm.readonly(), deep[0]);
            if tau1 > 0.0 && sr / tau1 > fmax {
                // k = np.round(minima / tau1); tol = np.maximum(1.0, 0.02 * minima)
                // ghost = |minima - k*tau1| <= tol; minima = minima[~ghost]
                minima.retain(|&m| {
                    let mf = m as f64;
                    let k = np_round(mf / tau1);
                    let tol = np_maximum(1.0, 0.02 * mf);
                    !((mf - k * tau1).abs() <= tol)
                });
                if minima.is_empty() {
                    return (Vec::new(), 0.0);
                }
            }
        }
        // vals = dnorm[minima]; running_min = np.minimum.accumulate(vals)
        // upper = concat(([1.0], running_min[:-1]))
        let vals: Vec<f64> = minima.iter().map(|&g| dnorm_v[g as usize]).collect();
        let mut running_min = Vec::with_capacity(vals.len());
        let mut acc = f64::INFINITY;
        for &v in &vals {
            acc = np_minimum(acc, v);
            running_min.push(acc);
        }
        let mut upper = Vec::with_capacity(vals.len());
        upper.push(1.0);
        upper.extend_from_slice(&running_min[..running_min.len() - 1]);
        let b_param = beta_a * (1.0 - beta_mean) / beta_mean;
        let cdf_u = _beta_cdf_arr(py, PyArray1::from_slice(py, &upper).readonly(), beta_a, b_param)
            .expect("_beta_cdf_arr failed");
        let cdf_v = _beta_cdf_arr(py, PyArray1::from_slice(py, &vals).readonly(), beta_a, b_param)
            .expect("_beta_cdf_arr failed");
        let cu: Vec<f64> = cdf_u.readonly().as_array().iter().copied().collect();
        let cv: Vec<f64> = cdf_v.readonly().as_array().iter().copied().collect();
        // probs = clip(where(upper > vals, cdf(upper) - cdf(vals), 0.0), 0.0, 1.0)
        let mut probs = Vec::with_capacity(vals.len());
        for i in 0..vals.len() {
            let p = if upper[i] > vals[i] { cu[i] - cv[i] } else { 0.0 };
            probs.push(np_clip(p, 0.0, 1.0));
        }
        // total = float(probs.sum())  ← 在过滤环之前取全部 probs（逐字）
        let total = pairwise_sum(&probs);
        let mut candidates: Vec<(f64, f64)> = Vec::new();
        for i in 0..minima.len() {
            let p = probs[i];
            if p <= 0.0 {
                continue;
            }
            let tau_f = parabolic_interpolate(dnorm.readonly(), minima[i]);
            if tau_f <= 0.0 {
                continue;
            }
            let f0 = sr / tau_f;
            if fmin <= f0 && f0 <= fmax {
                candidates.push((f0, p));
            }
        }
        // candidates.sort(key=lambda t: -t[1]) —— Python 稳定排序 ⇒ sort_by（保 tau 升序）
        candidates.sort_by(|a, b| {
            let (ka, kb) = (-a.1, -b.1);
            if ka < kb {
                std::cmp::Ordering::Less
            } else if ka > kb {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Equal
            }
        });
        // return candidates, min(total, 1.0)
        (candidates, if 1.0 < total { 1.0 } else { total })
    })
}

// ---- T-1062d R4: pYIN 整段逐帧候选层 pyin_candidates（逐字复刻 analysis/pyin.py:253-287）----

/// 整段信号逐帧概率化 YIN（pYIN 帧间循环层），返回 `(times, cand_lists, voiced)`。
/// 逐字复刻 `analysis/pyin.py::pyin_candidates`；★ 帧内必须复用同 crate 的 Rust 版
/// `pyin_frame`（禁重写帧内逻辑、禁经 PyO3 回调 Python）。
#[pyfunction]
#[pyo3(signature = (signal, sr, frame_size = 2048, hop_length = 256, fmin = 40.0, fmax = 2000.0, beta_mean = 0.15))]
fn pyin_candidates(
    py: Python<'_>,
    signal: numpy::PyReadonlyArray1<'_, f64>,
    sr: f64,
    frame_size: usize,
    hop_length: usize,
    fmin: f64,
    fmax: f64,
    beta_mean: f64,
) -> PyResult<(Py<PyArray1<f64>>, Vec<Vec<(f64, f64)>>, Py<PyArray1<f64>>)> {
    let x = signal.as_array();
    let n = x.len();
    // 退化分支（pyin.py:272-273）：空 ndarray + 空 list + 空 ndarray（N-5 防抄错）
    if n < frame_size {
        // 空 float64 ndarray（等价 np.array([])）×2 ＋ 中间空 list（N-5）
        let e0 = PyArray1::<f64>::from_vec(py, Vec::new()).unbind();
        let e1 = PyArray1::<f64>::from_vec(py, Vec::new()).unbind();
        return Ok((e0, Vec::new(), e1));
    }
    // n_frames = 1 + (size - frame_size) // hop_length（pyin.py:274 · 整数除法）
    let n_frames = 1 + (n - frame_size) / hop_length;
    let data = x.as_slice().expect("PyReadonlyArray1 is C-contiguous");
    let mut times = Vec::with_capacity(n_frames);
    let mut cand_lists: Vec<Vec<(f64, f64)>> = Vec::with_capacity(n_frames);
    let mut voiced: Vec<f64> = Vec::with_capacity(n_frames);
    for i in 0..n_frames {
        let start = i * hop_length;
        // times[i] = (i*hop + frame_size//4)/sr（pyin.py:275 · 帧中心语义 · 整数除法）
        times.push((start + frame_size / 4) as f64 / sr);
        // 帧 i = signal[i*hop : i*hop + frame_size]（pyin.py:276-280 as_strided 等价窗口）
        let frame = PyArray1::from_slice(py, &data[start..start + frame_size]);
        // ★ 帧内复用 Rust 版 pyin_frame（beta_a 走默认 2.0 · 逐字对齐 pyin.py:284）
        let (cands, vp) = pyin_frame(frame.readonly(), sr, fmin, fmax, beta_mean, 2.0);
        cand_lists.push(cands);
        voiced.push(vp);
    }
    Ok((
        PyArray1::from_vec(py, times).unbind(),
        cand_lists,
        PyArray1::from_vec(py, voiced).unbind(),
    ))
}

// ---- T-1062e R5: PitchHMM 网格层原生化（逐字复刻 analysis/pitch_hmm.py）----
//   hmm_grid        ← PitchHMM.__init__ 的网格/带权构造（:56-71）
//   hmm_observation ← PitchHMM.observation 单帧观测概率（:76-87）
// 复刻纪律（禁「优化」）：
//   · grid_freqs 步长由 n_bps 决定（pitch_hmm.py:62 逐字 = arange(n_pitch)/(12*n_bps)）
//     ⇒ 禁硬编码 5.0、禁用 n_pitch/69 反推（N-2）
//   · 带权 w 先 /= w.sum() 再取 log（次序不可倒，§一-3）
//   · observation 的 s 必须【顺序左折累加】，禁 pairwise_sum（§一-5 陷阱① · N-3）
//   · k 用 np_round（银行家舍入）后 clamp [0, n_pitch-1]（§一-5 陷阱②）
//   · 2^(k/denom) 必须走系统 libm pow：Rust 的 f64::powf 生成 llvm.pow，
//     LLVM 会把 pow(2.0, x) 折叠为 exp2(x) ⇒ 与 numpy 的 2.0**x（libm pow）
//     在 k=55 差 1 ULP（实测）。extern "C" pow 对 LLVM 不透明 ⇒ 禁折叠。

extern "C" {
    /// 系统 libm `pow`（不透明符号，防 LLVM 把 pow(2.0, x) 折叠成 exp2）。
    fn pow(x: f64, y: f64) -> f64;
}

/// `PitchHMM.__init__` 的网格/带权构造，返回 `(grid_freqs, log_w, log_self, log_cross)`。
/// 逐字复刻 `pitch_hmm.py:56-71`（★ 不含 n_pitch/n_state 标量，那些由 Python 侧赋值）。
#[pyfunction]
fn hmm_grid(
    py: Python<'_>,
    min_freq: f64,
    n_pitch: usize,
    n_bps: usize,
    transition_width: usize,
    self_trans: f64,
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<f64>>, f64, f64)> {
    // grid_freqs[k] = min_freq * 2^(k / (12 * n_bps))，k=0..n_pitch-1（:61-63）
    let denom = 12.0 * n_bps as f64;
    // 底数经 black_box 变为对 LLVM 不透明，阻止 pow(2.0, x)→exp2(x) 折叠，
    // 强制走系统 libm pow（与 numpy 的 2.0**x 逐位一致）。
    let two = std::hint::black_box(2.0f64);
    let grid: Vec<f64> = (0..n_pitch)
        .map(|k| {
            // SAFETY: 系统 libm pow 对有限 f64 无副作用
            min_freq * unsafe { pow(two, k as f64 / denom) }
        })
        .collect();
    // 带内三角权重（:65-69）：radius = width // 2 · offsets = -radius..=radius
    let radius = (transition_width / 2) as isize;
    let mut w: Vec<f64> = (-radius..=radius)
        .map(|d| (radius + 1 - d.abs()) as f64)
        .collect();
    // ★ 先归一化（w /= w.sum()）再取 log —— 次序不可倒
    // w.sum() 为 np.ndarray.sum ⇒ 复刻用 pairwise_sum（禁令仅针对 observation 的 s）
    let total = pairwise_sum(&w);
    for v in w.iter_mut() {
        // 逐字对齐 OFF 侧次序：先 w_i / sum（除法舍入），再取 log
        *v = (*v / total).ln();
    }
    // _log_self / _log_cross（:70-71）
    let log_self = self_trans.ln();
    let log_cross = (1.0 - self_trans).ln();
    Ok((
        PyArray1::from_vec(py, grid).unbind(),
        PyArray1::from_vec(py, w).unbind(),
        log_self,
        log_cross,
    ))
}

/// `PitchHMM.observation` 单帧观测概率，返回 `obs (n_state,)`。
/// 逐字复刻 `pitch_hmm.py:76-87`。★ `s` 用顺序左折累加（禁 pairwise_sum）。
#[pyfunction]
fn hmm_observation(
    py: Python<'_>,
    cands: Vec<(f64, f64)>,
    n_pitch: usize,
    n_state: usize,
    yin_trust: f64,
    min_freq: f64,
) -> PyResult<Py<PyArray1<f64>>> {
    let mut obs = vec![0.0f64; n_state];
    // s = float(sum(p for _, p in cands)) —— 顺序累加（:77）
    let mut s = 0.0f64;
    for &(_, p) in cands.iter() {
        s += p;
    }
    if s > 0.0 && !cands.is_empty() {
        let prob_really = yin_trust * s;
        for &(f0, p) in cands.iter() {
            // k = int(round(60 * log2(max(f0,1e-9)/min_freq)))（:81 · 银行家舍入）
            let kf = np_round(60.0 * (f0.max(1e-9) / min_freq).log2());
            let mut k = kf as isize;
            // k = min(max(k, 0), n_pitch - 1)（:82）
            if k < 0 {
                k = 0;
            }
            if k > n_pitch as isize - 1 {
                k = n_pitch as isize - 1;
            }
            obs[k as usize] += p * (prob_really / s);
        }
        // obs[n_pitch:] = (1 - prob_really) / n_pitch（:84）
        let unv = (1.0 - prob_really) / n_pitch as f64;
        for slot in obs[n_pitch..].iter_mut() {
            *slot = unv;
        }
    } else {
        // obs[n_pitch:] = 1.0 / n_pitch（:86）
        let unv = 1.0 / n_pitch as f64;
        for slot in obs[n_pitch..].iter_mut() {
            *slot = unv;
        }
    }
    Ok(PyArray1::from_vec(py, obs).unbind())
}

/// `PitchHMM._viterbi_step` 单帧带状递推，返回 `(new, bp_d, bp_v)`。
/// 逐字复刻 `pitch_hmm.py:113-141`（★ T-1062f R6）。
/// 复刻纪律（§二-1 甲~丁）：
///   · `best`/`padded` 初值 -inf · `shifted > best` 用【严格大于】（平手保留先出现的 d）
///   · `bp_d`/`bp_v` dtype int8 · `new = stack + obs_log` 不取 max
///   · :137/:139 的 bp_v 整行覆写用 `>=`（平手取 0 = 源有声行）· 禁省
///   · 形状校验：delta_log/obs_log 必须 (2, n_pitch)，不符 ⇒ TypeError
#[pyfunction]
fn hmm_viterbi_step(
    py: Python<'_>,
    delta_log: PyReadonlyArray2<'_, f64>,
    obs_log: PyReadonlyArray2<'_, f64>,
    n_pitch: usize,
    radius: usize,
    log_w: PyReadonlyArray1<'_, f64>,
    log_self: f64,
    log_cross: f64,
) -> PyResult<(Py<PyArray2<f64>>, Py<PyArray2<i8>>, Py<PyArray2<i8>>)> {
    let n = n_pitch;
    let r = radius;
    let dlog = delta_log.as_array();
    let olog = obs_log.as_array();
    // （甲）形状校验：(2, n_pitch)
    if dlog.shape() != [2, n] || olog.shape() != [2, n] {
        return Err(PyTypeError::new_err(
            "delta_log/obs_log must have shape (2, n_pitch)",
        ));
    }
    let dlog = dlog.as_slice().expect("C-contiguous");
    let olog = olog.as_slice().expect("C-contiguous");
    let lwv = log_w.as_array();
    let lw = lwv.as_slice().expect("C-contiguous");
    let neg_inf = f64::NEG_INFINITY;
    // :123-125 best / bp_d / bp_v
    let mut best = vec![neg_inf; 2 * n];
    let mut bp_d = vec![0i8; 2 * n];
    let mut bp_v = vec![0i8; 2 * n];
    // :126-127 padded (2, n+2r) 初值 -inf，中段 = delta_log
    let pw = n + 2 * r;
    let mut padded = vec![neg_inf; 2 * pw];
    for v in 0..2 {
        padded[v * pw + r..v * pw + r + n].copy_from_slice(&dlog[v * n..v * n + n]);
    }
    // :129-134 带状递推（行主序展平，v*n+p ≡ 2n 平面索引）
    for k in 0..(2 * r + 1) {
        let d = k as isize - r as isize;
        let w = lw[k];
        for v in 0..2 {
            let base = (v * pw) as isize;
            for p in 0..n {
                let shifted = padded[(base + r as isize + d + p as isize) as usize] + w;
                let i = v * n + p;
                if shifted > best[i] {
                    best[i] = shifted;
                    bp_d[i] = d as i8; // :133 bp_v[upd]=0 占位，必被下方整行覆写 ⇒ 省略
                }
            }
        }
    }
    // :136-139 voicing 组合（>= 平手取 0）
    let mut cand = vec![neg_inf; 2 * n];
    for p in 0..n {
        let b0 = best[p];
        let b1 = best[n + p];
        cand[p] = (b0 + log_self).max(b1 + log_cross);
        bp_v[p] = if b0 + log_self >= b1 + log_cross { 0 } else { 1 };
        cand[n + p] = (b0 + log_cross).max(b1 + log_self);
        bp_v[n + p] = if b0 + log_cross >= b1 + log_self { 0 } else { 1 };
    }
    // :140 new = stack([cand_v, cand_u]) + obs_log（不取 max）
    for i in 0..2 * n {
        cand[i] += olog[i];
    }
    let new_rows = vec![cand[..n].to_vec(), cand[n..].to_vec()];
    let bpd_rows = vec![bp_d[..n].to_vec(), bp_d[n..].to_vec()];
    let bpv_rows = vec![bp_v[..n].to_vec(), bp_v[n..].to_vec()];
    let new = PyArray2::from_vec2(py, &new_rows)
        .map_err(|e| PyTypeError::new_err(format!("new shape: {e}")))?;
    let bp_d_arr = PyArray2::from_vec2(py, &bpd_rows)
        .map_err(|e| PyTypeError::new_err(format!("bp_d shape: {e}")))?;
    let bp_v_arr = PyArray2::from_vec2(py, &bpv_rows)
        .map_err(|e| PyTypeError::new_err(format!("bp_v shape: {e}")))?;
    Ok((new.unbind(), bp_d_arr.unbind(), bp_v_arr.unbind()))
}

/// `PitchHMM.decode` 的全序列支（`fixed_lag is None`），返回 `(f0_hz, voiced, states)`。
/// 逐字复刻 `pitch_hmm.py:150-244` 中 R6 面（★ T-1062f R6 · 不碰 fixed_lag 环缓面）。
/// 组合纪律：复用 `hmm_observation`（R5）＋ `hmm_viterbi_step`（同 crate 直调）。
/// 陷阱：argmax/min 平手取首个 · divmod 截断 · :242 空候选守卫（无 ⇒ min(empty) 错值）
/// · 返回 dtype f64/bool/i64 逐一对齐。
#[pyfunction]
fn hmm_decode_full(
    py: Python<'_>,
    cand_lists: Vec<Vec<(f64, f64)>>,
    n_pitch: usize,
    n_state: usize,
    yin_trust: f64,
    min_freq: f64,
    grid_freqs: PyReadonlyArray1<'_, f64>,
    radius: usize,
    log_w: PyReadonlyArray1<'_, f64>,
    log_self: f64,
    log_cross: f64,
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<bool>>, Py<PyArray1<i64>>)> {
    let n = n_pitch;
    let n_frames = cand_lists.len();
    // :151-155 退化：n_frames==0 ⇒ 空 f64/bool/i64
    if n_frames == 0 {
        let e0 = PyArray1::<f64>::from_vec(py, Vec::new()).unbind();
        let e1 = PyArray1::<bool>::from_vec(py, Vec::new()).unbind();
        let e2 = PyArray1::<i64>::from_vec(py, Vec::new()).unbind();
        return Ok((e0, e1, e2));
    }
    let gridv = grid_freqs.as_array();
    let grid = gridv.as_slice().expect("C-contiguous");
    // :157-163 首帧观测 → delta (2, n)（obs 的 [0..n] 有声、[n..] 清音）
    let obs0 = hmm_observation(py, cand_lists[0].clone(), n, n_state, yin_trust, min_freq)?;
    let obs0 = obs0.bind(py).readonly().as_array().to_vec();
    let mut delta_rows = vec![vec![0.0f64; n], vec![0.0f64; n]];
    for p in 0..n {
        delta_rows[0][p] = if obs0[p] > 0.0 { obs0[p].ln() } else { f64::NEG_INFINITY };
        delta_rows[1][p] = if obs0[n + p] > 0.0 { obs0[n + p].ln() } else { f64::NEG_INFINITY };
    }
    // :165-166 全序列指针缓冲
    let mut all_bp_d = vec![vec![vec![0i8; n]; 2]; n_frames];
    let mut all_bp_v = vec![vec![vec![0i8; n]; 2]; n_frames];
    // :197-212 递推（全序列支：只存指针）
    for t in 1..n_frames {
        let obs = hmm_observation(py, cand_lists[t].clone(), n, n_state, yin_trust, min_freq)?;
        let obs = obs.bind(py).readonly().as_array().to_vec();
        let mut obs_rows = vec![vec![0.0f64; n], vec![0.0f64; n]];
        for p in 0..n {
            obs_rows[0][p] = if obs[p] > 0.0 { obs[p].ln() } else { f64::NEG_INFINITY };
            obs_rows[1][p] = if obs[n + p] > 0.0 { obs[n + p].ln() } else { f64::NEG_INFINITY };
        }
        let dl = PyArray2::from_vec2(py, &delta_rows).map_err(PyTypeError::new_err)?;
        let ol = PyArray2::from_vec2(py, &obs_rows).map_err(PyTypeError::new_err)?;
        let (new, bpd, bpv) = hmm_viterbi_step(
            py, dl.readonly(), ol.readonly(), n, radius,
            log_w.clone(), log_self, log_cross,
        )?;
        delta_rows = new.bind(py).readonly().as_array().rows().into_iter().map(|r| r.to_vec()).collect();
        all_bp_d[t] = bpd.bind(py).readonly().as_array().rows().into_iter().map(|r| r.to_vec()).collect();
        all_bp_v[t] = bpv.bind(py).readonly().as_array().rows().into_iter().map(|r| r.to_vec()).collect();
    }
    // :222-234 全序列回溯（argmax 平手取首：先行最大、再列最大）
    let m0 = argmax_first(&delta_rows[0]);
    let m1 = argmax_first(&delta_rows[1]);
    let v_row = if delta_rows[1][m1] > delta_rows[0][m0] { 1 } else { 0 };
    let p_idx = argmax_first(&delta_rows[v_row]);
    let mut cur = (v_row * n + p_idx) as i64;
    let mut path = vec![0i64; n_frames];
    for t in (0..n_frames).rev() {
        path[t] = cur;
        if t > 0 {
            let v = (cur / n as i64) as usize; // divmod 截断（cur >= 0）
            let p = (cur % n as i64) as usize;
            let d = all_bp_d[t][v][p] as i64;
            let sv = all_bp_v[t][v][p] as i64;
            cur = sv * n as i64 + (p as i64 + d);
        }
    }
    // :235-244 输出段（含 :242 空候选守卫）
    let mut f0_out = vec![f64::NAN; n_frames];
    let mut voiced_out = vec![false; n_frames];
    let mut state_out = vec![-1i64; n_frames];
    for t in 0..n_frames {
        let st = path[t];
        state_out[t] = st;
        if st < n as i64 {
            voiced_out[t] = true;
            let gf = grid[st as usize];
            let cands = &cand_lists[t];
            if !cands.is_empty() {
                // min(cands, key=|c[0]-grid|) 平手取首个
                let mut best_i = 0usize;
                let mut best_k = (cands[0].0 - gf).abs();
                for (i, c) in cands.iter().enumerate() {
                    let k = (c.0 - gf).abs();
                    if k < best_k {
                        best_k = k;
                        best_i = i;
                    }
                }
                f0_out[t] = cands[best_i].0;
            }
        }
    }
    Ok((
        PyArray1::from_vec(py, f0_out).unbind(),
        PyArray1::from_vec(py, voiced_out).unbind(),
        PyArray1::from_vec(py, state_out).unbind(),
    ))
}

/// np.argmax 语义：返回首个最大值索引（平手取首）。
fn argmax_first(a: &[f64]) -> usize {
    let mut bi = 0usize;
    let mut bv = a[0];
    for (i, &v) in a.iter().enumerate().skip(1) {
        if v > bv {
            bv = v;
            bi = i;
        }
    }
    bi
}

/// `backtrack` 复刻：`continue`（非 break）· 先取 `d` 再更新 `p` · `p` 更新后才取 `v`
/// · 返回标量状态号 `v * n_pitch + p`（★ T-1062g R7）。
fn lag_backtrack(
    t_target: usize,
    start_v: usize,
    start_p: i64,
    window: &[(Vec<i8>, Vec<i8>)],
    n: usize,
) -> i64 {
    let mut v = start_v;
    let mut p = start_p;
    for i in (0..window.len()).rev() {
        if (t_target as i64) - (i as i64 + 1) < 0 {
            continue; // ★ 不是 break：跳过时 v/p 保持上一轮值
        }
        let idx = v * n + p as usize;
        let d = window[i].0[idx] as i64;
        let src_v = window[i].1[idx] as usize;
        p = p + d;
        v = src_v;
    }
    (v * n) as i64 + p
}

/// `emit` 复刻（★ 单一共用 helper 覆盖循环/收尾两调用点 · N-3④）：
/// 含 `if cands:` 空候选守卫（无守卫 ⇒ min(empty) panic）· min 平手取首个。
#[allow(clippy::too_many_arguments)]
fn lag_emit(
    t: usize,
    end_v: usize,
    end_p: i64,
    window: &[(Vec<i8>, Vec<i8>)],
    n: usize,
    grid: &[f64],
    cands: &[(f64, f64)],
    f0_out: &mut [f64],
    voiced_out: &mut [bool],
    state_out: &mut [i64],
) {
    let st = lag_backtrack(t, end_v, end_p, window, n);
    state_out[t] = st;
    if st < n as i64 {
        voiced_out[t] = true;
        let gf = grid[st as usize];
        if !cands.is_empty() {
            let mut best_i = 0usize;
            let mut best_k = (cands[0].0 - gf).abs();
            for (i, c) in cands.iter().enumerate() {
                let k = (c.0 - gf).abs();
                if k < best_k {
                    best_k = k;
                    best_i = i;
                }
            }
            f0_out[t] = cands[best_i].0;
        }
    }
}

/// `int(np.argmax(delta.max(axis=1)))` → `int(np.argmax(delta[v_row]))`（平手取首）。
fn delta_argmax(delta_rows: &[Vec<f64>]) -> (usize, i64) {
    let m0 = argmax_first(&delta_rows[0]);
    let m1 = argmax_first(&delta_rows[1]);
    let v_row = if delta_rows[1][m1] > delta_rows[0][m0] { 1 } else { 0 };
    (v_row, argmax_first(&delta_rows[v_row]) as i64)
}

/// `PitchHMM.decode` 的 `fixed_lag` 在线回溯支（★ T-1062g R7 · 不碰 R6 全序列面）。
/// 逐字复刻 `pitch_hmm.py` 的 `ring`/`backtrack`/`emit`/收尾（★ 符号锚定位）。
/// 组合纪律：复用 `hmm_observation`（R5）＋ `hmm_viterbi_step`（R6 · 同 crate 直调 · 禁重写）。
/// ★★ 收尾语义（N-2）：`ring[t:]` 是【绝对帧号】对 Python list 的切片 ⇒ `n_frames > 2·lag`
/// 时尾段起点 `t0 = n_frames - lag > len(ring)` ⇒ 切片恒空 ⇒ 尾帧全取末帧 argmax 态
/// （★ 禁实现成「语义正确的滑窗」· states 面逐位是唯一判据）。
/// 退化：`n_frames == 0` ⇒ 空 f64/bool/i64（N-1②）· `fixed_lag >= n_frames` 须与 OFF 逐位一致。
#[pyfunction]
fn hmm_decode_lag(
    py: Python<'_>,
    cand_lists: Vec<Vec<(f64, f64)>>,
    n_pitch: usize,
    n_state: usize,
    yin_trust: f64,
    min_freq: f64,
    grid_freqs: PyReadonlyArray1<'_, f64>,
    radius: usize,
    log_w: PyReadonlyArray1<'_, f64>,
    log_self: f64,
    log_cross: f64,
    fixed_lag: usize,
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<bool>>, Py<PyArray1<i64>>)> {
    let n = n_pitch;
    let n_frames = cand_lists.len();
    let lag = fixed_lag;
    // 退化：n_frames==0 ⇒ 空 f64/bool/i64
    if n_frames == 0 {
        let e0 = PyArray1::<f64>::from_vec(py, Vec::new()).unbind();
        let e1 = PyArray1::<bool>::from_vec(py, Vec::new()).unbind();
        let e2 = PyArray1::<i64>::from_vec(py, Vec::new()).unbind();
        return Ok((e0, e1, e2));
    }
    let gridv = grid_freqs.as_array();
    let grid = gridv.as_slice().expect("C-contiguous");
    // 首帧观测 → delta (2, n)
    let obs0 = hmm_observation(py, cand_lists[0].clone(), n, n_state, yin_trust, min_freq)?;
    let obs0 = obs0.bind(py).readonly().as_array().to_vec();
    let mut delta_rows = vec![vec![0.0f64; n], vec![0.0f64; n]];
    for p in 0..n {
        delta_rows[0][p] = if obs0[p] > 0.0 { obs0[p].ln() } else { f64::NEG_INFINITY };
        delta_rows[1][p] = if obs0[n + p] > 0.0 { obs0[n + p].ln() } else { f64::NEG_INFINITY };
    }
    // ring：(bp_d, bp_v) 展平 (2n) 环形缓冲，容量 lag（★ 超即 pop_front）
    let mut ring: Vec<(Vec<i8>, Vec<i8>)> = Vec::new();
    let mut f0_out = vec![f64::NAN; n_frames];
    let mut voiced_out = vec![false; n_frames];
    let mut state_out = vec![-1i64; n_frames];
    for t in 1..n_frames {
        let obs = hmm_observation(py, cand_lists[t].clone(), n, n_state, yin_trust, min_freq)?;
        let obs = obs.bind(py).readonly().as_array().to_vec();
        let mut obs_rows = vec![vec![0.0f64; n], vec![0.0f64; n]];
        for p in 0..n {
            obs_rows[0][p] = if obs[p] > 0.0 { obs[p].ln() } else { f64::NEG_INFINITY };
            obs_rows[1][p] = if obs[n + p] > 0.0 { obs[n + p].ln() } else { f64::NEG_INFINITY };
        }
        let dl = PyArray2::from_vec2(py, &delta_rows).map_err(PyTypeError::new_err)?;
        let ol = PyArray2::from_vec2(py, &obs_rows).map_err(PyTypeError::new_err)?;
        let (new, bpd, bpv) = hmm_viterbi_step(
            py, dl.readonly(), ol.readonly(), n, radius,
            log_w.clone(), log_self, log_cross,
        )?;
        delta_rows = new.bind(py).readonly().as_array().rows().into_iter().map(|r| r.to_vec()).collect();
        let bpd_flat: Vec<i8> = bpd.bind(py).readonly().as_array().rows().into_iter().flat_map(|r| r.to_vec()).collect();
        let bpv_flat: Vec<i8> = bpv.bind(py).readonly().as_array().rows().into_iter().flat_map(|r| r.to_vec()).collect();
        ring.push((bpd_flat, bpv_flat));
        if ring.len() > lag {
            ring.remove(0); // ring.pop(0)
        }
        if t >= lag {
            let (v_row, p_idx) = delta_argmax(&delta_rows);
            lag_emit(t - lag, v_row, p_idx, &ring, n, grid, &cand_lists[t - lag],
                     &mut f0_out, &mut voiced_out, &mut state_out);
        }
    }
    // 收尾：v_row/p_idx 取【末帧】delta；窗口 = ring[t:]（绝对帧号切 list · N-2）
    let (v_row, p_idx) = delta_argmax(&delta_rows);
    let t0 = n_frames.saturating_sub(lag);
    for t in t0..n_frames {
        let win: &[(Vec<i8>, Vec<i8>)] = if t < ring.len() { &ring[t..] } else { &[] };
        lag_emit(t, v_row, p_idx, win, n, grid, &cand_lists[t],
                 &mut f0_out, &mut voiced_out, &mut state_out);
    }
    Ok((
        PyArray1::from_vec(py, f0_out).unbind(),
        PyArray1::from_vec(py, voiced_out).unbind(),
        PyArray1::from_vec(py, state_out).unbind(),
    ))
}

// ---------------------------------------------------------------------------
// R8 追加：尾段硬门控 helper（内部复用 rms_frames_impl · 禁 PyO3 回调）
// ---------------------------------------------------------------------------
fn rms_frames_impl(signal: &[f64], frame_size: usize, hop: usize) -> Vec<f64> {
    if signal.len() < frame_size {
        return Vec::new();
    }
    let n_fr = 1 + (signal.len() - frame_size) / hop;
    let mut out = Vec::with_capacity(n_fr);
    for i in 0..n_fr {
        let start = i * hop;
        let end = start + frame_size;
        let mut s = 0.0f64;
        for j in start..end {
            s += signal[j] * signal[j];
        }
        let mean = s / (frame_size as f64);
        out.push(mean.sqrt());
    }
    out
}

#[pyfunction]
fn rms_frames<'py>(
    py: Python<'py>,
    signal: PyReadonlyArray1<'py, f64>,
    frame_size: usize,
    hop: usize,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let sig = signal.as_slice()?;
    let rms = rms_frames_impl(sig, frame_size, hop);
    Ok(PyArray1::from_vec(py, rms))
}

#[pyfunction]
fn pyin_hard_gate<'py>(
    py: Python<'py>,
    res_f0: PyReadonlyArray1<'py, f64>,
    res_voiced: PyReadonlyArray1<'py, bool>,
    cands: Vec<Vec<(f64, f64)>>,
    signal: PyReadonlyArray1<'py, f64>,
    frame_size: usize,
    hop: usize,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let f0 = res_f0.as_slice()?;
    let voiced = res_voiced.as_slice()?;
    let sig = signal.as_slice()?;
    let n = f0.len();
    let mut out = Vec::with_capacity(n);
    // 硬门控 0: voiced & isfinite
    for i in 0..n {
        if voiced[i] && f0[i].is_finite() {
            out.push(f0[i]);
        } else {
            out.push(f64::NAN);
        }
    }
    // 硬门控 1: 空候选帧强 NaN
    for (i, c) in cands.iter().enumerate() {
        if i < n && c.is_empty() {
            out[i] = f64::NAN;
        }
    }
    // 硬门控 2: 帧 RMS < 峰值 10% 强 NaN
    let rms = rms_frames_impl(sig, frame_size, hop);
    if !rms.is_empty() {
        let rmax = rms.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        if rmax > 0.0 {
            for i in 0..rms.len() {
                if i < n && rms[i] < 0.10 * rmax {
                    out[i] = f64::NAN;
                }
            }
        }
    }
    Ok(PyArray1::from_vec(py, out))
}

/// A Python module implemented in Rust. The name of this function must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn acouscope_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sum_i64, m)?)?;
    m.add_function(wrap_pyfunction!(native_selfcheck, m)?)?;
    m.add_function(wrap_pyfunction!(difference_function, m)?)?;
    m.add_function(wrap_pyfunction!(cumulative_mean_normalized, m)?)?;
    m.add_function(wrap_pyfunction!(local_minima, m)?)?;
    m.add_function(wrap_pyfunction!(parabolic_interpolate, m)?)?;
    m.add_function(wrap_pyfunction!(_betacf, m)?)?;
    m.add_function(wrap_pyfunction!(_beta_cdf, m)?)?;
    m.add_function(wrap_pyfunction!(_beta_cdf_arr, m)?)?;
    m.add_function(wrap_pyfunction!(pyin_frame, m)?)?;
    m.add_function(wrap_pyfunction!(pyin_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(hmm_grid, m)?)?;
    m.add_function(wrap_pyfunction!(hmm_observation, m)?)?;
    m.add_function(wrap_pyfunction!(hmm_viterbi_step, m)?)?;
    m.add_function(wrap_pyfunction!(hmm_decode_full, m)?)?;
    m.add_function(wrap_pyfunction!(hmm_decode_lag, m)?)?;
    m.add_function(wrap_pyfunction!(rms_frames, m)?)?;
    m.add_function(wrap_pyfunction!(pyin_hard_gate, m)?)?;
    m.add_function(wrap_pyfunction!(resample_chunk_native, m)?)?;
    Ok(())
}

// ---- T-1063: player._resample_chunk 原生化（线性插值 · 逐字复刻 numpy linspace+interp）----

/// `player.AudioPlayer._resample_chunk` 的 Rust 端实现。
/// 逐字复刻 `np.linspace(0, n-1, m)`（先除式 + 末点强制）+ `np.interp`（slope 式）。
/// 入参 data 恒 f64（Python 侧 .astype(np.float64) 确保）；出参 f64（Python 侧 .astype(data.dtype) 降回）。
#[pyfunction]
fn resample_chunk_native<'py>(
    py: Python<'py>,
    data: PyReadonlyArray1<'py, f64>,
    target_length: usize,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let x = data.as_slice()?;
    let n = x.len();
    let m = target_length;
    // 守卫 1: m == n → 原样复制（对齐 player.py:258）
    if m == n {
        return Ok(PyArray1::from_vec(py, x.to_vec()));
    }
    // 守卫 2: m == 0 → 空数组；n == 0 且 m > 0 → 长度 m 的零向量
    // （对齐 player.py:260-261 np.zeros(target_length, dtype=data.dtype)）
    if m == 0 {
        return Ok(PyArray1::from_vec(py, Vec::<f64>::new()));
    }
    if n == 0 {
        return Ok(PyArray1::from_vec(py, vec![0.0f64; m]));
    }
    // 守卫 3: m == 1 → [data[0]]
    // （np.linspace(0,n-1,1) = [0.0] → np.interp([0.0], arange(n), data) = [data[0]]）
    if m == 1 {
        return Ok(PyArray1::from_vec(py, vec![x[0]]));
    }
    // 守卫 4: n == 1 → 全部 xq=0 → np.interp 恒返回 data[0]
    // （主路径会 clamp floor(0)=0 到 [0,n-2]=[0,-1] → min>max panic）
    if n == 1 {
        return Ok(PyArray1::from_vec(py, vec![x[0]; m]));
    }
    // 主路径：delta = (n-1)/(m-1) 先除式（R-2 · 令文 v2 钉死）
    let n_minus_1 = (n - 1) as f64;
    let m_minus_1 = (m - 1) as f64;
    let delta = n_minus_1 / m_minus_1;
    let mut out = Vec::with_capacity(m);
    for i in 0..m {
        // xq[i] = delta * i；最后一点强制 = n-1（先乘式在 n=2001/m=2048 等非逐位）
        let xq = if i == m - 1 {
            n_minus_1
        } else {
            delta * i as f64
        };
        // np.interp 端点快捷：xq 恰好等于 xp 端点时直接返回端点值
        // （斜率式 d[n-2] + 1*(d[n-1]-d[n-2]) 浮点上可能 1 ULP 偏离 d[n-1]）
        if xq == n_minus_1 {
            out.push(x[n - 1]);
            continue;
        }
        if xq == 0.0 {
            out.push(x[0]);
            continue;
        }
        // np.interp slope 式：k = floor(xq)，clamp 到 [0, n-2]（xq ∈ (0, n-1) ⇒ 无越界）
        let kf = xq.floor();
        let k = (kf as isize).clamp(0, (n - 2) as isize) as usize;
        let frac = xq - k as f64;
        let y = x[k] + frac * (x[k + 1] - x[k]);
        out.push(y);
    }
    Ok(PyArray1::from_vec(py, out))
}
