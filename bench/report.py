"""Gera graficos e tabela-resumo a partir de uma sessao de testes.

Para cada teste:  <teste>/grafico_teste.png  (FPS, temperatura, potencia e clock ao longo do tempo)
Para a sessao:    resumo.csv, comparacao.png, fps_distribuicao.png, fps_ao_longo_do_tempo.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # gera arquivos PNG sem abrir janela
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# Paleta categorica (ordem fixa: o teste N sempre tem a mesma cor em todos os graficos)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 9, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 8, "lines.linewidth": 1.4,
    "font.size": 9,
})


def _break_gaps(df: pd.DataFrame, col: str):
    """Devolve (x, y) com NaN nos buracos (ex.: jogo reiniciado), para a linha nao ligar os pontos."""
    x = df["hours"].to_numpy(dtype=float)
    y = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    if len(x) < 3:
        return x, y
    dx = pd.Series(x).diff()
    gap = dx > 3 * dx.median()
    if not gap.any():
        return x, y
    import numpy as np
    idx = np.where(gap.to_numpy())[0]
    return np.insert(x, idx, np.nan), np.insert(y, idx, np.nan)


def color_for(test_id: int) -> str:
    return SERIES[(int(test_id) - 1) % len(SERIES)]


# ----------------------------------------------------------------------------- leitura

def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, format="ISO8601")
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def _read_presentmon(folder: Path) -> pd.DataFrame | None:
    rows = []
    for f in sorted(folder.glob("pm_*.csv")):
        try:
            pm = pd.read_csv(f, usecols=lambda c: c in ("MsBetweenDisplayChange", "MsBetweenPresents", "FrameType"))
        except Exception:
            continue
        col = "MsBetweenDisplayChange" if "MsBetweenDisplayChange" in pm else "MsBetweenPresents"
        if col not in pm:
            continue
        ms = pd.to_numeric(pm[col], errors="coerce")
        ms = ms[ms > 0]
        if ms.empty:
            continue
        rows.append({
            "timestamp_utc": pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC"),
            "displayed_fps": 1000.0 / ms.mean(),
            "displayed_low1_fps": 1000.0 / ms.quantile(0.99),
        })
    return pd.DataFrame(rows) if rows else None


def load_test(test_dir: Path, warmup_min: float) -> dict | None:
    summary_path = test_dir / "summary.json"
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    eng = _read_csv(test_dir / "engine_samples.csv")
    sysd = _read_csv(test_dir / "system_samples.csv")
    pm = _read_presentmon(test_dir / "presentmon")

    t0_candidates = [d["timestamp_utc"].iloc[0] for d in (eng, sysd) if d is not None]
    if not t0_candidates:
        return {"summary": summary, "engine": None, "system": None, "presentmon": pm, "dir": test_dir}
    t0 = min(t0_candidates)
    cut = t0 + pd.Timedelta(minutes=warmup_min)
    for d in (eng, sysd, pm):
        if d is not None:
            d["hours"] = (d["timestamp_utc"] - t0).dt.total_seconds() / 3600.0
            d["after_warmup"] = d["timestamp_utc"] >= cut
    return {"summary": summary, "engine": eng, "system": sysd, "presentmon": pm, "dir": test_dir}


# ----------------------------------------------------------------------------- estatisticas

def _mean(df, col):
    if df is None or col not in df:
        return None
    s = pd.to_numeric(df.loc[df["after_warmup"], col], errors="coerce").dropna()
    return round(float(s.mean()), 2) if not s.empty else None


def _mean_positive(df, col):
    """Media so dos valores > 0 (ex.: FPS exibido do Frame Generation, que e 0 com o FG desligado)."""
    if df is None or col not in df:
        return None
    s = pd.to_numeric(df.loc[df["after_warmup"], col], errors="coerce")
    s = s[s > 0]
    return round(float(s.mean()), 2) if not s.empty else None


def _max(df, col):
    if df is None or col not in df:
        return None
    s = pd.to_numeric(df.loc[df["after_warmup"], col], errors="coerce").dropna()
    return round(float(s.max()), 2) if not s.empty else None


def compute_stats(t: dict) -> dict:
    s, eng, sysd, pm = t["summary"], t["engine"], t["system"], t["presentmon"]
    row = {
        "teste": s["test_name"], "id": s["test_id"], "status": s.get("status"),
        "horas": round(s.get("wall_elapsed_s", 0) / 3600, 2), "reinicios": s.get("restarts", 0),
        "fps_medio": _mean(eng, "avg_fps"), "fps_1pct_low": _mean(eng, "low1_fps"),
        "frametime_ms": _mean(eng, "avg_frametime_ms"), "frametime_p99_ms": _mean(eng, "p99_frametime_ms"),
        "gpu_time_ms": _mean(eng, "gpu_time_ms"),
        "fps_exibido_dlssg": _mean_positive(eng, "dlssg_fps"),
        "fps_exibido_presentmon": _mean(pm, "displayed_fps"),
        "gpu_util_pct": _mean(sysd, "gpu_util_pct"), "vram_mb": _mean(sysd, "vram_used_mb"),
        "temp_media_c": _mean(sysd, "gpu_temp_c"), "temp_max_c": _max(sysd, "gpu_temp_c"),
        "potencia_media_w": _mean(sysd, "power_w"), "potencia_max_w": _max(sysd, "power_w"),
        "clock_sm_medio_mhz": _mean(sysd, "clock_sm_mhz"), "cpu_util_pct": _mean(sysd, "cpu_util_pct"),
    }
    if row["fps_medio"] and row["potencia_media_w"]:
        row["fps_por_watt"] = round(row["fps_medio"] / row["potencia_media_w"], 3)
    if sysd is not None:
        w = sysd[sysd["after_warmup"]]
        if "energy_j" in w and pd.to_numeric(w["energy_j"], errors="coerce").notna().sum() > 1:
            e = pd.to_numeric(w["energy_j"], errors="coerce").dropna()
            row["energia_kwh"] = round((e.iloc[-1] - e.iloc[0]) / 3.6e6, 3)
        tr = w["throttle_reasons"].fillna("").astype(str) if "throttle_reasons" in w else pd.Series(dtype=str)
        if len(tr) and tr.str.len().sum() > 0:
            row["pct_limitado_potencia"] = round(100 * tr.str.contains("power").mean(), 1)
            row["pct_limitado_temperatura"] = round(100 * tr.str.contains("thermal").mean(), 1)
    return row


# ----------------------------------------------------------------------------- graficos

def plot_test(t: dict, out_png: Path) -> None:
    s, eng, sysd, pm = t["summary"], t["engine"], t["system"], t["presentmon"]
    panels = [
        ("FPS", eng, [("avg_fps", "FPS médio (renderizado)", SERIES[0]), ("low1_fps", "1% low", SERIES[1])], "FPS"),
        ("Temperatura da GPU", sysd, [("gpu_temp_c", None, SERIES[0])], "°C"),
        ("Potência da GPU", sysd, [("power_w", None, SERIES[0])], "W"),
        ("Clock SM da GPU", sysd, [("clock_sm_mhz", None, SERIES[0])], "MHz"),
    ]
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 10), sharex=True)
    for ax, (title, df, series, unit) in zip(axes, panels):
        ax.set_title(title)
        ax.set_ylabel(unit)
        if df is None:
            ax.text(0.5, 0.5, "sem dados", transform=ax.transAxes, ha="center", color=MUTED)
            continue
        for col, label, color in series:
            if col in df:
                ax.plot(*_break_gaps(df, col), color=color, label=label)
        if title == "FPS" and df is not None and "dlssg_fps" in df and (pd.to_numeric(df["dlssg_fps"], errors="coerce") > 0).any():
            ax.plot(*_break_gaps(df, "dlssg_fps"), color=SERIES[3], label="FPS exibido (Frame Generation)")
        if title == "FPS" and pm is not None:
            ax.scatter(pm["hours"], pm["displayed_fps"], s=18, color=SERIES[2], label="FPS exibido (PresentMon)", zorder=3)
        if title == "FPS":
            ax.legend(loc="lower left", bbox_to_anchor=(0.08, 0.98), ncol=3)
        warm = df.loc[~df["after_warmup"], "hours"]
        if not warm.empty:
            ax.axvspan(0, warm.max(), color=GRID, alpha=0.5, lw=0)
    axes[-1].set_xlabel("Horas desde o início do teste (faixa cinza = aquecimento, fora das estatísticas)")
    fig.suptitle(f"{s['test_name']}  ·  {s.get('status')}  ·  {s.get('restarts', 0)} reinício(s)",
                 x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def plot_comparison(stats: pd.DataFrame, out_png: Path) -> None:
    metrics = [("fps_medio", "FPS médio (renderizado)"), ("potencia_media_w", "Potência média (W)"),
               ("temp_media_c", "Temperatura média (°C)"), ("fps_por_watt", "Eficiência (FPS por watt)")]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    colors = [color_for(i) for i in stats["id"]]
    for ax, (col, title) in zip(axes.flat, metrics):
        ax.set_title(title)
        ax.grid(axis="y", visible=False)
        ax.set_axisbelow(True)
        if col not in stats or stats[col].isna().all():
            ax.text(0.5, 0.5, "sem dados", transform=ax.transAxes, ha="center", color=MUTED)
            continue
        vals = stats[col].fillna(0)
        bars = ax.barh(stats["teste"], vals, color=colors, height=0.6)
        ax.invert_yaxis()
        for b, v in zip(bars, vals):
            ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f" {v:g}", va="center", color=INK_2, fontsize=8)
        ax.margins(x=0.15)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def plot_distribution(tests: list[dict], out_png: Path) -> None:
    data, labels, colors = [], [], []
    for t in tests:
        eng = t["engine"]
        if eng is None:
            continue
        data.append(pd.to_numeric(eng.loc[eng["after_warmup"], "avg_fps"], errors="coerce").dropna())
        labels.append(t["summary"]["test_name"])
        colors.append(color_for(t["summary"]["test_id"]))
    if not data:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    bp = ax.boxplot(data, vert=False, patch_artist=True, showfliers=False, widths=0.5)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.85)
        patch.set_edgecolor(SURFACE)
    for med in bp["medians"]:
        med.set_color(INK)
    ax.set_axisbelow(True)
    ax.set_yticks(range(1, len(labels) + 1), labels)
    ax.invert_yaxis()
    ax.set_title("Distribuição do FPS médio por amostra (após aquecimento)")
    ax.set_xlabel("FPS")
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def plot_timeline(tests: list[dict], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    plotted = False
    for t in tests:
        eng = t["engine"]
        if eng is None:
            continue
        # media movel de 5 min para enxergar tendencia (degradacao termica etc.)
        fps = pd.to_numeric(eng["avg_fps"], errors="coerce")
        window = max(1, int(300 / max(1.0, eng["elapsed_s"].diff().median() or 5)))
        smooth = eng.assign(_fps=fps.rolling(window, min_periods=1).mean())
        ax.plot(*_break_gaps(smooth, "_fps"), color=color_for(t["summary"]["test_id"]), label=t["summary"]["test_name"])
        plotted = True
    if not plotted:
        plt.close(fig)
        return
    ax.set_title("FPS ao longo do tempo (média móvel de 5 min)")
    ax.set_xlabel("Horas desde o início de cada teste")
    ax.set_ylabel("FPS")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------- entrada

def generate(session_dirs, warmup_min: float = 5.0, log=print, out_dir: Path | None = None) -> Path | None:
    """Gera o relatorio. `session_dirs` pode ser uma pasta de sessao ou uma lista delas
    (para comparar testes rodados em sessoes diferentes, ex.: um teste de 48h por vez)."""
    if isinstance(session_dirs, (str, Path)):
        session_dirs = [Path(session_dirs)]
    session_dirs = [Path(d) for d in session_dirs]
    out_dir = Path(out_dir) if out_dir else session_dirs[0]
    out_dir.mkdir(parents=True, exist_ok=True)

    tests = []
    for sd in session_dirs:
        for d in sorted(p for p in sd.iterdir() if p.is_dir()):
            t = load_test(d, warmup_min)
            if t:
                tests.append(t)
    if not tests:
        log(f"Nenhum teste encontrado em {', '.join(map(str, session_dirs))}")
        return None
    tests.sort(key=lambda t: (t["summary"]["test_id"], t["summary"].get("started_utc", "")))
    # mesmo teste repetido em sessoes diferentes: diferencia pelo nome da sessao
    names = [t["summary"]["test_name"] for t in tests]
    for t in tests:
        if names.count(t["summary"]["test_name"]) > 1:
            t["summary"]["test_name"] += f" ({t['dir'].parent.name.replace('sessao_', '')})"

    for t in tests:
        plot_test(t, t["dir"] / "grafico_teste.png")

    stats = pd.DataFrame([compute_stats(t) for t in tests])
    stats.to_csv(out_dir / "resumo.csv", index=False, encoding="utf-8-sig")
    plot_comparison(stats, out_dir / "comparacao.png")
    plot_distribution(tests, out_dir / "fps_distribuicao.png")
    plot_timeline(tests, out_dir / "fps_ao_longo_do_tempo.png")
    log(f"Relatorio gerado em {out_dir} (resumo.csv + graficos PNG)")
    return out_dir / "resumo.csv"