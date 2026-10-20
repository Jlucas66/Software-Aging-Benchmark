"""Analise de software aging sobre os resultados do benchmark (teste de Mann-Kendall).

Le as pastas de resultado ja gravadas (nao depende do jogo nem do orquestrador),
prepara cada serie (descarta aquecimento, separa trechos entre reinicios, agrega por
janela de tempo) e aplica bench.mk_stats.mann_kendall em cada metrica.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .mk_stats import MIN_POINTS, mann_kendall

# Direcao esperada quando ha envelhecimento:
#   "aumento"  = a metrica piora quando cresce (memoria, tempo de frame)
#   "queda"    = a metrica piora quando cai (FPS)
#   None       = metrica de contexto (temperatura, clock...): explica a causa, nao e aging
METRICS = {
    "process_mem_mb":   ("engine", "MB",  "aumento", "Memória do processo do jogo"),
    "vram_used_mb":     ("system", "MB",  "aumento", "VRAM usada"),
    "ram_used_mb":      ("system", "MB",  "aumento", "RAM usada (sistema)"),
    "avg_frametime_ms": ("engine", "ms",  "aumento", "Tempo médio de frame"),
    "p99_frametime_ms": ("engine", "ms",  "aumento", "Tempo de frame (p99)"),
    "gpu_time_ms":      ("engine", "ms",  "aumento", "Tempo de GPU por frame"),
    "game_thread_ms":   ("engine", "ms",  "aumento", "Tempo da game thread"),
    "render_thread_ms": ("engine", "ms",  "aumento", "Tempo da render thread"),
    "avg_fps":          ("engine", "FPS", "queda",   "FPS médio"),
    "low1_fps":         ("engine", "FPS", "queda",   "FPS 1% low"),
    "dlssg_fps":        ("engine", "FPS", "queda",   "FPS exibido (Frame Generation)"),
    "gpu_temp_c":       ("system", "°C",  None,      "Temperatura da GPU"),
    "clock_sm_mhz":     ("system", "MHz", None,      "Clock SM da GPU"),
    "power_w":          ("system", "W",   None,      "Potência da GPU"),
    "gpu_util_pct":     ("system", "%",   None,      "Uso da GPU"),
    "cpu_util_pct":     ("system", "%",   None,      "Uso da CPU"),
}
PLOT_METRICS = ["process_mem_mb", "vram_used_mb", "avg_frametime_ms", "p99_frametime_ms"]
CONSOLE_METRICS = ["process_mem_mb", "vram_used_mb", "avg_frametime_ms", "p99_frametime_ms", "avg_fps", "dlssg_fps"]


@dataclass
class Params:
    window: str = "5min"          # "0" = sem agregacao
    warmup_min: float = 30.0      # descartado no inicio de cada trecho
    alpha: float = 0.05
    method: str = "hamed_rao"     # qual teste decide: "hamed_rao" ou "original"
    max_lag: int | None = None
    metrics: list[str] = field(default_factory=lambda: list(METRICS))

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class TestData:
    label: str
    session: str
    test_id: int
    test_name: str
    path: Path
    engine: pd.DataFrame | None
    system: pd.DataFrame | None
    t0: pd.Timestamp | None
    segments: list[tuple[pd.Timestamp, pd.Timestamp]]
    restarts: int


# ----------------------------------------------------------------------------- leitura

def _read(path: Path, time_col: str = "timestamp_utc") -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_csv(path)
    if df.empty or time_col not in df:
        return None
    df[time_col] = pd.to_datetime(df[time_col], utc=True, format="ISO8601")
    return df.sort_values(time_col).reset_index(drop=True)


def find_test_dirs(path: Path) -> list[Path]:
    """Aceita a pasta de um teste, de uma sessao ou uma pasta com varias sessoes."""
    path = Path(path)
    found = set()
    for pattern in ("summary.json", "*/summary.json", "*/*/summary.json"):
        found.update(p.parent for p in path.glob(pattern))
    return sorted(found)


def split_segments(times: pd.Series, gap_s: float | None = None):
    """Separa em trechos continuos (um reinicio do jogo deixa um buraco nas amostras)."""
    if times is None or len(times) == 0:
        return []
    dt = times.diff().dt.total_seconds()
    if gap_s is None:
        median = float(dt.median()) if len(dt) > 1 and dt.notna().any() else 5.0
        gap_s = max(60.0, 10.0 * median)
    breaks = list(np.where(dt > gap_s)[0])
    starts = [0] + breaks
    ends = [b - 1 for b in breaks] + [len(times) - 1]
    return [(times.iloc[s], times.iloc[e]) for s, e in zip(starts, ends)]


def load_test(test_dir: Path, label: str) -> TestData:
    summary = json.loads((test_dir / "summary.json").read_text(encoding="utf-8"))
    engine = _read(test_dir / "engine_samples.csv")
    system = _read(test_dir / "system_samples.csv")
    starts = [d["timestamp_utc"].iloc[0] for d in (engine, system) if d is not None]
    # Os trechos vem das amostras do jogo: o monitor de sistema continua gravando
    # enquanto o jogo esta fechado entre um crash e a reabertura.
    reference = engine if engine is not None else system
    segments = split_segments(reference["timestamp_utc"]) if reference is not None else []
    return TestData(
        label=label, session=test_dir.parent.name, test_id=int(summary.get("test_id", 0)),
        test_name=summary.get("test_name", test_dir.name), path=test_dir,
        engine=engine, system=system, t0=min(starts) if starts else None,
        segments=segments, restarts=max(0, len(segments) - 1),
    )


# ----------------------------------------------------------------------------- preparo

def prepare_series(df: pd.DataFrame, column: str, segments, t0, params: Params, time_col="timestamp_utc"):
    """Devolve lista de (rotulo_trecho, horas, valores) ja sem aquecimento e agregada."""
    out = []
    values = pd.to_numeric(df[column], errors="coerce")
    data = pd.DataFrame({"t": df[time_col], "v": values}).dropna()
    for k, (start, end) in enumerate(segments, start=1):
        cut = start + pd.Timedelta(minutes=params.warmup_min)
        seg = data[(data["t"] >= cut) & (data["t"] <= end)]
        if seg.empty:
            continue
        if params.window not in ("0", "", "none", "nenhuma"):
            seg = (seg.set_index("t")["v"].resample(params.window, origin="start").mean()
                   .dropna().reset_index())
            seg.columns = ["t", "v"]
        hours = (seg["t"] - t0).dt.total_seconds().to_numpy() / 3600.0
        out.append((f"trecho {k}", hours, seg["v"].to_numpy(dtype=float)))
    return out


def _row_base(test: TestData, metric: str, unit: str, direction, desc: str, segment: str):
    return {
        "rotulo": test.label, "sessao": test.session, "teste_id": test.test_id, "teste": test.test_name,
        "trecho": segment, "metrica": metric, "descricao": desc, "unidade": unit,
        "tipo": "contexto" if direction is None else ("envelhecimento" if direction else "personalizada"),
        "reinicios_no_teste": test.restarts,
    }


def analyze_one(hours: np.ndarray, values: np.ndarray, params: Params, direction) -> dict:
    if len(values) < MIN_POINTS:
        return {"n": len(values), "sinal_de_envelhecimento": "dados insuficientes"}
    r = mann_kendall(values, hours, alpha=params.alpha, max_lag=params.max_lag)
    decision = r.trend_hr if params.method == "hamed_rao" else r.trend
    if params.method == "hamed_rao" and not math.isfinite(r.z_hr):
        decision = "correcao invalida"
    span_h = float(hours.max() - hours.min())
    start_value = r.sen_intercept + r.sen_slope * float(hours.min())
    total = r.sen_slope * span_h
    pct = 100.0 * total / abs(start_value) if abs(start_value) > 1e-9 else float("nan")

    if direction is None:
        signal = "contexto"
    elif direction == "":
        signal = "-"
    elif decision == "sem tendencia":
        signal = "nao"
    elif decision in ("crescente", "decrescente"):
        worse = (direction == "aumento" and decision == "crescente") or (direction == "queda" and decision == "decrescente")
        signal = "sim" if worse else "nao (melhora)"
    else:
        signal = "indeterminado"

    return {
        "n": r.n, "horas_analisadas": round(span_h, 3), "S": r.s, "tau": r.tau,
        "z_original": r.z, "p_original": r.p, "tendencia_original": r.trend,
        "z_hamed_rao": r.z_hr, "p_hamed_rao": r.p_hr, "tendencia_hamed_rao": r.trend_hr,
        "fator_hamed_rao": r.hr_factor, "lags_significativos": r.hr_significant_lags,
        "tendencia_decisao": decision,
        "sen_por_hora": r.sen_slope, "sen_ic_inferior": r.sen_ci_low, "sen_ic_superior": r.sen_ci_high,
        "sen_intercepto": r.sen_intercept, "sen_metodo": r.sen_method,
        "valor_inicial_sen": start_value, "variacao_total": total, "variacao_pct": pct,
        "sinal_de_envelhecimento": signal,
    }


def analyze_test(test: TestData, params: Params) -> tuple[list[dict], dict]:
    """Analisa todas as metricas de um teste. Devolve (linhas, series_para_grafico)."""
    rows, plot_data = [], {}
    if test.t0 is None:
        return rows, plot_data
    for metric in params.metrics:
        if metric not in METRICS:
            continue
        source, unit, direction, desc = METRICS[metric]
        df = test.engine if source == "engine" else test.system
        if df is None or metric not in df:
            continue
        numeric = pd.to_numeric(df[metric], errors="coerce")
        if numeric.notna().sum() == 0 or (numeric.fillna(0) == 0).all():
            continue  # sem dados (ex.: FPS do Frame Generation num teste sem FG)
        parts = prepare_series(df, metric, test.segments, test.t0, params)
        if not parts:
            continue
        hours = np.concatenate([p[1] for p in parts])
        values = np.concatenate([p[2] for p in parts])
        full = _row_base(test, metric, unit, direction, desc, "completo")
        full.update(analyze_one(hours, values, params, direction))
        rows.append(full)
        seg_rows = []
        if len(parts) > 1:  # houve reinicio: analisa cada trecho tambem
            for name, h, v in parts:
                row = _row_base(test, metric, unit, direction, desc, name)
                row.update(analyze_one(h, v, params, direction))
                rows.append(row)
                seg_rows.append(row)
        plot_data[metric] = (parts, full, seg_rows)
    return rows, plot_data


def analyze_csv(path: Path, time_col: str, columns: list[str], label: str, params: Params):
    """Analisa um CSV qualquer (ex.: o seu proprio script de monitoramento)."""
    df = pd.read_csv(path)
    if time_col not in df:
        raise SystemExit(f"Coluna de tempo '{time_col}' nao existe em {path.name}. Colunas: {', '.join(df.columns)}")
    if pd.api.types.is_numeric_dtype(df[time_col]):  # segundos desde o inicio
        df[time_col] = pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(df[time_col], unit="s")
    else:
        df[time_col] = pd.to_datetime(df[time_col], utc=True, format="mixed")
    df = df.sort_values(time_col).reset_index(drop=True)
    segments = split_segments(df[time_col])
    t0 = df[time_col].iloc[0]
    fake = TestData(label=label, session=path.parent.name, test_id=0, test_name=path.stem, path=path.parent,
                    engine=None, system=None, t0=t0, segments=segments, restarts=max(0, len(segments) - 1))
    rows = []
    for col in columns:
        if col not in df:
            print(f"  aviso: coluna '{col}' nao existe em {path.name}")
            continue
        parts = prepare_series(df, col, segments, t0, params, time_col=time_col)
        if not parts:
            continue
        row = _row_base(fake, col, "", "", col, "completo")
        row.update(analyze_one(np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts]), params, ""))
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------- saidas

def comparison_table(results: pd.DataFrame) -> pd.DataFrame | None:
    """Uma linha por (teste, metrica) e colunas lado a lado para cada rotulo (ex.: windows x linux)."""
    full = results[results["trecho"] == "completo"]
    if full["rotulo"].nunique() < 2:
        return None
    keep = ["tendencia_decisao", "p_hamed_rao", "p_original", "sen_por_hora", "variacao_pct", "sinal_de_envelhecimento"]
    pivot = full.pivot_table(index=["teste_id", "teste", "metrica", "unidade"], columns="rotulo",
                             values=keep, aggfunc="first")
    pivot.columns = [f"{rot}_{col}" for col, rot in pivot.columns]
    ordered = sorted(pivot.columns, key=lambda c: (c.split("_", 1)[0], keep.index(c.split("_", 1)[1])))
    return pivot[ordered].reset_index()


def fmt_p(p) -> str:
    if p is None or (isinstance(p, float) and not math.isfinite(p)):
        return "n/d"
    return "<1e-300" if p == 0 else (f"{p:.3f}" if p >= 0.001 else f"{p:.1e}")


def console_summary(results: pd.DataFrame, params: Params) -> str:
    lines = []
    full = results[results["trecho"] == "completo"]
    p_col = "p_hamed_rao" if params.method == "hamed_rao" else "p_original"

    def fmt_row(name: str, r) -> str:
        if r["sinal_de_envelhecimento"] == "dados insuficientes":
            return f"   {name:<18} dados insuficientes (n={r['n']})"
        return (f"   {name:<18} {r['tendencia_decisao']:<14} p={fmt_p(r[p_col]):<8} "
                f"Sen={r['sen_por_hora']:+.4g} {r['unidade']}/h ({r['variacao_pct']:+.2f}% em {r['horas_analisadas']:.1f} h)"
                f"  -> envelhecimento: {r['sinal_de_envelhecimento']}")

    for (label, test_id, test), grp in full.groupby(["rotulo", "teste_id", "teste"], sort=True):
        restarts = int(grp["reinicios_no_teste"].iloc[0])
        lines.append(f"\n[{label}] {test}" + (
            f"  (atencao: {restarts} reinicio(s); o reinicio zera a memoria, entao o resultado"
            f" de cada trecho e o mais confiavel)" if restarts else ""))
        segs = results[(results["rotulo"] == label) & (results["teste"] == test) & (results["trecho"] != "completo")]
        for metric in CONSOLE_METRICS + [m for m in grp["metrica"] if m not in CONSOLE_METRICS and METRICS.get(m, (0, 0, 1))[2] == "aumento"]:
            r = grp[grp["metrica"] == metric]
            if r.empty:
                continue
            lines.append(fmt_row(metric, r.iloc[0]))
            if restarts and metric in CONSOLE_METRICS:
                for _, sr in segs[segs["metrica"] == metric].iterrows():
                    lines.append("  " + fmt_row(f"  {sr['trecho']}", sr))
        clock = grp[grp["metrica"] == "clock_sm_mhz"]
        temp = grp[grp["metrica"] == "gpu_temp_c"]
        if not clock.empty and clock.iloc[0]["tendencia_decisao"] == "decrescente":
            lines.append(f"   ! clock SM em queda ({clock.iloc[0]['variacao_pct']:+.2f}%): perda de FPS pode ser termica/potencia, nao aging.")
        if not temp.empty and temp.iloc[0]["tendencia_decisao"] == "crescente":
            lines.append(f"   ! temperatura da GPU subindo ({temp.iloc[0]['variacao_total']:+.1f} °C no periodo).")
    return "\n".join(lines)


def plot_test(test: TestData, plot_data: dict, out_png: Path, params: Params) -> None:
    from .report import INK, MUTED, SERIES, plt  # mesmo estilo dos outros graficos
    metrics = [m for m in PLOT_METRICS if m in plot_data]
    if not metrics:
        return
    cols = 2
    rows_n = math.ceil(len(metrics) / cols)
    fig, axes = plt.subplots(rows_n, cols, figsize=(12, 3.6 * rows_n), squeeze=False)
    p_key = "p_hamed_rao" if params.method == "hamed_rao" else "p_original"
    for ax, metric in zip(axes.flat, metrics):
        parts, res, seg_rows = plot_data[metric]
        _, unit, _, desc = METRICS[metric]
        for k, (_, h, v) in enumerate(parts):
            ax.plot(h, v, color=SERIES[0], lw=1.2, label="Média por janela" if k == 0 else None)
        # Sem reinicio: uma reta de Sen. Com reinicio: uma reta por trecho (o reinicio
        # zera o estado do jogo, entao uma reta unica atravessando o salto engana).
        fits = [(res, parts[0][1].min(), parts[-1][1].max())] if not seg_rows else \
               [(r, h.min(), h.max()) for r, (_, h, _) in zip(seg_rows, parts)]
        drawn = False
        for r, h0, h1 in fits:
            if math.isfinite(r.get("sen_por_hora", float("nan"))):
                hh = np.array([h0, h1])
                ax.plot(hh, r["sen_intercepto"] + r["sen_por_hora"] * hh, color=SERIES[1], lw=1.6,
                        ls="--", label=None if drawn else "Inclinação de Sen")
                drawn = True
        ax.set_title(f"{desc} ({unit})", pad=16)
        if not seg_rows and math.isfinite(res.get("sen_por_hora", float("nan"))):
            info = (f"{res['tendencia_decisao']} · p={fmt_p(res[p_key])} · "
                    f"Sen {res['sen_por_hora']:+.3g} {unit}/h · {res['variacao_pct']:+.2f}% no período")
        elif seg_rows:
            info = "por trecho: " + " | ".join(
                f"{r.get('tendencia_decisao', 'n/d')} {r.get('sen_por_hora', float('nan')):+.3g} {unit}/h" for r in seg_rows)
        else:
            info = "dados insuficientes"
        ax.text(0.0, 1.015, info, transform=ax.transAxes, va="bottom", ha="left", fontsize=8, color=MUTED)
        ax.set_xlabel("Horas desde o início do teste")
        ax.legend(loc="best")
    for ax in list(axes.flat)[len(metrics):]:
        ax.set_visible(False)
    method = "Hamed-Rao" if params.method == "hamed_rao" else "original"
    fig.suptitle(f"{test.label} · {test.test_name} · Mann-Kendall ({method}), janela {params.window}, "
                 f"aquecimento {params.warmup_min:g} min descartado", x=0.01, ha="left", color=INK,
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out_png, dpi=130)
    plt.close(fig)