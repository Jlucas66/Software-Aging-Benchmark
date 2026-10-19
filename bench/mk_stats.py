"""Teste de Mann-Kendall, correcao de Hamed-Rao e inclinacao de Sen.

Implementacao propria (so numpy), conferida contra o pacote pyMannKendall
(Hussain & Mahmud, 2019) pelo script tests/validar_mann_kendall.py.

Foi escrita para series longas (48 h amostradas a cada 5 s = ~34.560 pontos):
  - a estatistica S e calculada em O(n^2) com operacoes vetorizadas, sem
    guardar a matriz de pares na memoria;
  - a inclinacao de Sen e exata ate EXACT_SEN_MAX_N pontos e, acima disso,
    estimada com uma amostra aleatoria (semente fixa) de pares.

Referencias
  Mann, H. B. (1945). Nonparametric tests against trend. Econometrica 13(3).
  Kendall, M. G. (1975). Rank Correlation Methods. Griffin.
  Hamed, K. H.; Rao, A. R. (1998). A modified Mann-Kendall trend test for
      autocorrelated data. Journal of Hydrology 204, 182-196.
  Sen, P. K. (1968). Estimates of the regression coefficient based on
      Kendall's tau. JASA 63, 1379-1389.
  Gilbert, R. O. (1987). Statistical Methods for Environmental Pollution
      Monitoring. Wiley. (intervalo de confianca da inclinacao de Sen)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist

import numpy as np

EXACT_SEN_MAX_N = 3000          # ate aqui: todos os n(n-1)/2 pares
SEN_SAMPLE_PAIRS = 4_000_000    # acima: amostra aleatoria de pares
MIN_POINTS = 10                 # abaixo disso a aproximacao normal nao e confiavel

_NORMAL = NormalDist()


def norm_ppf(p: float) -> float:
    return _NORMAL.inv_cdf(p)


def two_sided_p(z: float) -> float:
    """p-valor bicaudal. erfc mantem precisao para p muito pequenos (ex.: 1e-40)."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def trend_label(z: float, alpha: float) -> str:
    if not math.isfinite(z) or abs(z) <= norm_ppf(1 - alpha / 2):
        return "sem tendencia"
    return "crescente" if z > 0 else "decrescente"


# ----------------------------------------------------------------------------- blocos

def mk_score(x: np.ndarray) -> int:
    """S = soma de sinal(x_j - x_i) para todo i < j."""
    s = 0
    for i in range(len(x) - 1):
        d = x[i + 1:] - x[i]
        s += int(np.count_nonzero(d > 0)) - int(np.count_nonzero(d < 0))
    return s


def variance_s(x: np.ndarray) -> float:
    """Variancia de S sob H0, com correcao para empates."""
    n = float(len(x))
    _, tp = np.unique(x, return_counts=True)
    tp = tp.astype(np.float64)
    return (n * (n - 1) * (2 * n + 5) - float(np.sum(tp * (tp - 1) * (2 * tp + 5)))) / 18.0


def z_score(s: int, var_s: float) -> float:
    """Estatistica Z com correcao de continuidade."""
    if var_s <= 0 or s == 0:
        return 0.0
    return (s - 1) / math.sqrt(var_s) if s > 0 else (s + 1) / math.sqrt(var_s)


def rankdata_avg(a: np.ndarray) -> np.ndarray:
    """Postos com media para empates (equivalente a scipy.stats.rankdata)."""
    a = np.asarray(a)
    sorter = np.argsort(a, kind="mergesort")
    inv = np.empty(len(a), dtype=np.intp)
    inv[sorter] = np.arange(len(a))
    a_sorted = a[sorter]
    obs = np.r_[True, a_sorted[1:] != a_sorted[:-1]]
    dense = obs.cumsum()[inv]
    count = np.r_[np.nonzero(obs)[0], len(obs)]
    return 0.5 * (count[dense] + count[dense - 1] + 1)


def autocorrelation(x: np.ndarray) -> np.ndarray:
    """Autocorrelacao amostral (divisor n) em todos os lags, via FFT."""
    y = np.asarray(x, dtype=np.float64) - np.mean(x)
    n = len(y)
    size = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(y, n=size)
    acov = np.fft.irfft(f * np.conj(f), n=size)[:n] / n
    if acov[0] <= 0:
        return np.zeros(n)
    return acov / acov[0]


def pair_slopes(x: np.ndarray, t: np.ndarray, seed: int = 0):
    """Inclinacoes de todos os pares (ou de uma amostra deles).

    Devolve (por_indice, por_tempo, metodo). `por_indice` usa o espacamento entre
    amostras (necessario para a correcao de Hamed-Rao); `por_tempo` usa o tempo real.
    """
    n = len(x)
    if n <= EXACT_SEN_MAX_N:
        by_idx, by_t = [], []
        for i in range(n - 1):
            dx = x[i + 1:] - x[i]
            by_idx.append(dx / np.arange(1, n - i, dtype=np.float64))
            with np.errstate(divide="ignore", invalid="ignore"):
                by_t.append(dx / (t[i + 1:] - t[i]))
        si, st = np.concatenate(by_idx), np.concatenate(by_t)
        method = "exato"
    else:
        rng = np.random.default_rng(seed)
        i = rng.integers(0, n, SEN_SAMPLE_PAIRS)
        j = rng.integers(0, n, SEN_SAMPLE_PAIRS)
        keep = i != j
        lo, hi = np.minimum(i, j)[keep], np.maximum(i, j)[keep]
        dx = x[hi] - x[lo]
        si = dx / (hi - lo)
        with np.errstate(divide="ignore", invalid="ignore"):
            st = dx / (t[hi] - t[lo])
        method = f"amostra de {len(lo):,} pares".replace(",", ".")
    return si, st[np.isfinite(st)], method


# ----------------------------------------------------------------------------- teste

@dataclass
class MKResult:
    n: int
    s: int
    var_s: float
    tau: float
    # Mann-Kendall original
    z: float
    p: float
    trend: str
    # Mann-Kendall com correcao de Hamed-Rao (autocorrelacao)
    z_hr: float
    p_hr: float
    trend_hr: str
    hr_factor: float          # n/n* (>1 = autocorrelacao positiva infla a variancia)
    hr_significant_lags: int
    # Inclinacao de Sen (por unidade de t) e IC
    sen_slope: float
    sen_intercept: float
    sen_ci_low: float
    sen_ci_high: float
    sen_method: str
    alpha: float

    def to_dict(self) -> dict:
        return asdict(self)


def mann_kendall(x, t=None, alpha: float = 0.05, max_lag: int | None = None, seed: int = 0) -> MKResult:
    """Executa o teste de Mann-Kendall (original e Hamed-Rao) e a inclinacao de Sen.

    x: valores da serie, em ordem temporal (NaN sao removidos).
    t: tempo de cada valor (ex.: horas). Se omitido, usa 0, 1, 2, ...
    max_lag: maior lag considerado na correcao de Hamed-Rao (None = todos).
    """
    x = np.asarray(x, dtype=np.float64)
    t = np.arange(len(x), dtype=np.float64) if t is None else np.asarray(t, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(t)
    x, t = x[ok], t[ok]
    n = len(x)
    if n < MIN_POINTS:
        raise ValueError(f"serie com {n} pontos; o minimo e {MIN_POINTS}")

    s = mk_score(x)
    var_s = variance_s(x)
    tau = s / (0.5 * n * (n - 1))
    z = z_score(s, var_s)
    p = two_sided_p(z) if var_s > 0 else 1.0

    si, st, sen_method = pair_slopes(x, t, seed)
    slope_idx = float(np.median(si))
    slope_t = float(np.median(st)) if len(st) else float("nan")
    intercept_t = float(np.median(x) - np.median(t) * slope_t)

    # Hamed & Rao (1998): autocorrelacao dos postos da serie sem tendencia
    detrended = x - np.arange(1, n + 1) * slope_idx
    r = autocorrelation(rankdata_avg(detrended))
    lag = n if max_lag is None else min(n, int(max_lag) + 1)
    lags = np.arange(1, lag, dtype=np.float64)
    r_l = r[1:lag]
    bound = norm_ppf(1 - alpha / 2) / math.sqrt(n)
    significant = np.abs(r_l) > bound
    sni = float(np.sum((n - lags) * (n - lags - 1) * (n - lags - 2) * r_l * significant))
    hr_factor = 1.0 + 2.0 / (n * (n - 1.0) * (n - 2.0)) * sni
    if hr_factor > 0 and var_s > 0:
        var_hr = var_s * hr_factor
        z_hr = z_score(s, var_hr)
        p_hr = two_sided_p(z_hr)
    else:  # correcao invalida (fator <= 0): resultado nao interpretavel
        var_hr, z_hr, p_hr = float("nan"), float("nan"), float("nan")

    # IC da inclinacao de Sen (Gilbert, 1987), com a variancia corrigida quando valida
    var_ci = var_hr if math.isfinite(var_hr) else var_s
    n_pairs = n * (n - 1) / 2.0
    c = norm_ppf(1 - alpha / 2) * math.sqrt(max(var_ci, 0.0))
    q_low = min(max((n_pairs - c) / (2 * n_pairs), 0.0), 1.0)
    q_high = min(max((n_pairs + c) / (2 * n_pairs), 0.0), 1.0)
    ci_low, ci_high = (np.quantile(st, [q_low, q_high]) if len(st) else (float("nan"), float("nan")))

    return MKResult(
        n=n, s=s, var_s=var_s, tau=tau,
        z=z, p=p, trend=trend_label(z, alpha),
        z_hr=z_hr, p_hr=p_hr, trend_hr=trend_label(z_hr, alpha),
        hr_factor=hr_factor, hr_significant_lags=int(np.sum(significant)),
        sen_slope=slope_t, sen_intercept=intercept_t,
        sen_ci_low=float(ci_low), sen_ci_high=float(ci_high), sen_method=sen_method,
        alpha=alpha,
    )
