"""Confere bench/mk_stats.py contra o pacote pyMannKendall (Hussain & Mahmud, 2019).

Uso (opcional, so para validar a implementacao):
    pip install pymannkendall
    python tests/validar_mann_kendall.py
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.mk_stats import mann_kendall  # noqa: E402

try:
    import pymannkendall as pmk
except ImportError:
    sys.exit("Instale o pacote de referencia: pip install pymannkendall")


def series(rng, n, slope, phi, ties):
    e = np.zeros(n)
    for i in range(1, n):  # ruido AR(1): autocorrelacao como numa serie real
        e[i] = phi * e[i - 1] + rng.normal()
    x = slope * np.arange(n) + e
    return np.round(x, 1) if ties else x


def close(a, b, rel=1e-9, abs_=1e-12):
    if (isinstance(a, float) and math.isnan(a)) and (isinstance(b, float) and math.isnan(b)):
        return True
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


rng = np.random.default_rng(42)
cases = [(n, slope, phi, ties) for n in (30, 200, 800) for slope in (0.0, 0.01, -0.05)
         for phi in (0.0, 0.6) for ties in (False, True)]
failures = 0
for n, slope, phi, ties in cases:
    x = series(rng, n, slope, phi, ties)
    ours = mann_kendall(x, alpha=0.05)
    ref_o = pmk.original_test(x, alpha=0.05)
    ref_h = pmk.hamed_rao_modification_test(x, alpha=0.05)
    checks = {
        "S": (ours.s, ref_o.s), "VarS": (ours.var_s, ref_o.var_s), "Tau": (ours.tau, ref_o.Tau),
        "Z": (ours.z, ref_o.z), "p": (ours.p, ref_o.p),
        "Z_HR": (ours.z_hr, ref_h.z), "p_HR": (ours.p_hr, ref_h.p),
        "Sen": (ours.sen_slope, ref_o.slope), "Intercepto": (ours.sen_intercept, ref_o.intercept),
    }
    bad = [k for k, (a, b) in checks.items() if not close(float(a), float(b), rel=1e-7, abs_=1e-9)]
    trend_map = {"increasing": "crescente", "decreasing": "decrescente", "no trend": "sem tendencia"}
    if ours.trend != trend_map[ref_o.trend] or ours.trend_hr != trend_map[ref_h.trend]:
        bad.append("tendencia")
    status = "OK " if not bad else "ERRO"
    failures += bool(bad)
    print(f"{status} n={n:<4} inclinacao={slope:<6} phi={phi:<4} empates={ties!s:<5} "
          f"p={ours.p:.3e} p_HR={ours.p_hr:.3e} {'' if not bad else 'divergem: ' + ', '.join(bad)}")

print(f"\n{len(cases) - failures}/{len(cases)} casos identicos ao pyMannKendall.")
sys.exit(1 if failures else 0)
