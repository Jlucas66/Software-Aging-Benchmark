"""Relatorio descritivo de uma ou mais sessoes (so quando voce roda `python run.py report`).

Grava em <sessao>/relatorio/ (ou BenchmarkRuns/comparacao_<data>/ com varias sessoes):
    resumo.csv        uma linha por teste: medias, inicio x fim das metricas de aging, contexto
    processos_mais_ativos.csv   os outros processos que mais usaram CPU em cada teste
    <teste>.png       FPS, memoria do jogo, handles, VRAM, temperatura e clock ao longo do tempo
    comparacao.png    os testes lado a lado

A analise estatistica de tendencia (Mann-Kendall) fica em mann_kendall.py.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # gera arquivos PNG sem abrir janela
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .dataset import TestResult, find_sessions, load_session  # noqa: E402

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


def color_for(test_id: int) -> str:
    return SERIES[(int(test_id) - 1) % len(SERIES)]


def _xy(df: pd.DataFrame, col: str, smooth_min: float = 0):
    """(horas, valores) com um buraco entre execucoes, para a linha nao ligar um reinicio.
    smooth_min > 0: media movel de N minutos (calculada dentro de cada execucao)."""
    x = df["horas"].to_numpy(dtype=float)
    v = pd.to_numeric(df[col], errors="coerce")
    if smooth_min > 0 and len(df) > 2:
        step_s = float(df["horas"].diff().median() * 3600) or 5.0
        n = max(1, int(round(smooth_min * 60 / step_s)))
        v = v.groupby(df["execucao"]).transform(lambda s: s.rolling(n, min_periods=1, center=True).mean())
    y = v.to_numpy(dtype=float)
    if "execucao" in df and df["execucao"].nunique() > 1:
        idx = np.where(df["execucao"].diff().fillna(0).to_numpy() != 0)[0]
        x, y = np.insert(x, idx, np.nan), np.insert(y, idx, np.nan)
    return x, y


def _no_data(ax):
    ax.text(0.5, 0.5, "sem dados", transform=ax.transAxes, ha="center", va="center", color=MUTED)
    ax.tick_params(left=False, labelleft=False)
    ax.grid(False)


# ----------------------------------------------------------------------------- estatisticas

def _mean(s: pd.Series):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return round(float(s.mean()), 2) if not s.empty else None


def compute_stats(t: TestResult, warmup_min: float) -> dict:
    m = t.meta
    dlss = m.get("dlss") or {}
    row = {
        "plataforma": t.platform, "sessao": t.session, "id": t.id, "teste": t.name,
        "status": m.get("status"), "horas": m.get("horas"), "reinicios": m.get("reinicios", 0),
        "amostras": len(t.df), "modo_dlss": dlss.get("dlss_mode"), "modo_fg": dlss.get("dlssg_mode"),
    }
    df = t.df
    if df.empty:
        return row
    w = df[df["horas"] >= warmup_min / 60.0]
    if w.empty:
        w = df
    for col, name in (("fps", "fps_medio"), ("fps_exibido", "fps_exibido_medio"),
                      ("frametime_p99_ms", "frametime_p99_ms"), ("gpu_time_ms", "gpu_time_ms"),
                      ("render_thread_ms", "render_thread_ms"), ("proc_cpu_pct", "cpu_jogo_pct"),
                      ("outros_cpu_pct", "cpu_outros_processos_pct"), ("cpu_total_pct", "cpu_total_pct"),
                      ("cpu_nucleo_max_pct", "cpu_nucleo_max_pct"),
                      ("gpu_util_pct", "gpu_util_pct")):
        if col in w:
            row[name] = _mean(w[col])

    # Inicio x fim: media da primeira e da ultima janela (1 h, ou 10% do teste se ele for curto).
    # E so descritivo; a tendencia estatistica fica com o Mann-Kendall.
    span = float(w["horas"].max() - w["horas"].min())
    win = min(1.0, max(span * 0.1, 1e-6))
    first = w[w["horas"] <= w["horas"].min() + win]
    last = w[w["horas"] >= w["horas"].max() - win]
    for col in ("proc_private_mb", "proc_mem_mb", "proc_handles", "proc_threads", "vram_mb", "fps"):
        if col in w:
            a, b = _mean(first[col]), _mean(last[col])
            row[f"{col}_inicio"], row[f"{col}_fim"] = a, b

    if "gpu_temp_c" in w:
        row["temp_media_c"] = _mean(w["gpu_temp_c"])
        row["temp_max_c"] = round(float(pd.to_numeric(w["gpu_temp_c"], errors="coerce").max()), 1)
    if "gpu_clock_mhz" in w:
        row["clock_medio_mhz"] = _mean(w["gpu_clock_mhz"])
    if "gpu_power_w" in w:
        row["potencia_media_w"] = _mean(w["gpu_power_w"])
    for col, name in (("throttle_power", "pct_tempo_limite_potencia"), ("throttle_thermal", "pct_tempo_limite_termico")):
        if col in w:
            v = pd.to_numeric(w[col], errors="coerce").dropna()
            row[name] = round(100 * float(v.mean()), 1) if not v.empty else None
    return row


# ----------------------------------------------------------------------------- graficos

PANELS = [
    ("FPS", [("fps", "Renderizado"), ("fps_exibido", "Exibido (Frame Generation)")], "FPS"),
    ("Memória do jogo", [("proc_private_mb", "Privada (Private Bytes)"), ("proc_mem_mb", "Física (Working Set)")], "MB"),
    ("Handles abertos pelo jogo", [("proc_handles", None)], ""),
    ("VRAM usada", [("vram_mb", None)], "MB"),
    ("Uso de CPU", [("cpu_total_pct", "Total"), ("proc_cpu_pct", "Jogo"), ("outros_cpu_pct", "Outros processos")], "%"),
    ("Gargalo: CPU × GPU", [("cpu_nucleo_max_pct", "Núcleo de CPU mais ocupado"), ("gpu_util_pct", "Uso da GPU")], "%"),
    ("Temperatura da GPU", [("gpu_temp_c", None)], "°C"),
    ("Clock da GPU", [("gpu_clock_mhz", None)], "MHz"),
]


def plot_test(t: TestResult, warmup_min: float, out_png: Path) -> None:
    df = t.df
    fig, axes = plt.subplots(4, 2, figsize=(12, 12), sharex=True)
    for ax, (title, series, unit) in zip(axes.flat, PANELS):
        ax.set_title(title)
        ax.set_ylabel(unit)
        drawn = 0
        for k, (col, label) in enumerate(series):
            if col in df and pd.to_numeric(df[col], errors="coerce").notna().any():
                ax.plot(*_xy(df, col), color=SERIES[k], lw=0.6, alpha=0.25)            # cada amostra
                ax.plot(*_xy(df, col, smooth_min=5), color=SERIES[k], label=label)   # media de 5 min
                drawn += 1
        if not drawn:
            _no_data(ax)
        elif drawn > 1:
            ax.legend(loc="best")
        if warmup_min > 0:
            ax.axvspan(0, warmup_min / 60.0, color=GRID, alpha=0.5, lw=0)
    for ax in axes[-1]:
        ax.set_xlabel("Horas desde o início do teste")
    dlss = t.meta.get("dlss") or {}
    fig.suptitle(f"{t.name}  ·  {t.platform}  ·  {t.meta.get('status')}  ·  {t.meta.get('reinicios', 0)} reinício(s)"
                 f"  ·  DLSS {dlss.get('dlss_mode', '-')}, FG {dlss.get('dlssg_mode', '-')}",
                 x=0.01, ha="left", color=INK, fontsize=12, fontweight="bold")
    fig.text(0.01, 0.005, "Linha forte = média móvel de 5 min; clara = cada amostra. Faixa cinza = aquecimento "
             "(fora das médias). Linha interrompida = o jogo foi reaberto.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def plot_comparison(stats: pd.DataFrame, out_png: Path) -> None:
    stats = stats.copy()
    if "proc_private_mb_inicio" in stats:
        stats["mem_delta"] = stats["proc_private_mb_fim"] - stats["proc_private_mb_inicio"]
    metrics = [("fps_medio", "FPS médio (renderizado)"), ("mem_delta", "Memória privada do jogo: fim − início (MB)"),
               ("temp_media_c", "Temperatura média da GPU (°C)"), ("potencia_media_w", "Potência média da GPU (W)")]
    labels = stats["rotulo"]
    colors = [color_for(i) for i in stats["id"]]
    fig, axes = plt.subplots(2, 2, figsize=(12, 2.2 + 0.45 * len(stats) * 2))
    for ax, (col, title) in zip(axes.flat, metrics):
        ax.set_title(title)
        ax.grid(axis="y", visible=False)
        ax.set_axisbelow(True)
        if col not in stats or stats[col].isna().all():
            _no_data(ax)
            continue
        vals = stats[col].astype(float).fillna(0)
        bars = ax.barh(labels, vals, color=colors, height=0.6)
        ax.invert_yaxis()
        for b, v in zip(bars, vals):
            ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f" {v:.4g}", va="center", color=INK_2, fontsize=8)
        ax.margins(x=0.15)
        ax.axvline(0, color=AXIS, lw=0.8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def top_processes(tests: list[TestResult], n: int = 15) -> pd.DataFrame | None:
    """Os outros processos que mais usaram CPU durante cada teste (de <teste>_processos.csv)."""
    frames = []
    for t in tests:
        f = t.path.parent / t.meta.get("processos", f"{t.name}_processos.csv")
        if not f.exists() or f.stat().st_size == 0:
            continue
        p = pd.read_csv(f)
        if p.empty:
            continue
        p["cpu_pct"] = pd.to_numeric(p["cpu_pct"], errors="coerce")
        p["mem_mb"] = pd.to_numeric(p["mem_mb"], errors="coerce")
        snapshots = max(1, p["timestamp_utc"].nunique())
        g = p.groupby("processo").agg(
            cpu_soma=("cpu_pct", "sum"), cpu_max_pct=("cpu_pct", "max"), mem_max_mb=("mem_mb", "max"),
            vezes_registrado=("timestamp_utc", "nunique"), primeira_hora=("horas", "min"), ultima_hora=("horas", "max"))
        # media sobre o teste inteiro (minutos em que nao apareceu contam como ~0)
        g["cpu_media_pct"] = (g.pop("cpu_soma") / snapshots).round(2)
        g = g.sort_values(["cpu_media_pct", "mem_max_mb"], ascending=False).head(n).reset_index()
        g.insert(0, "teste", t.name)
        g.insert(0, "sessao", t.session)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else None


# ----------------------------------------------------------------------------- entrada

def generate(paths, warmup_min: float = 5.0, out_dir: Path | None = None, log=print) -> Path | None:
    if isinstance(paths, (str, Path)):
        paths = [paths]
    sessions = [s for p in paths for s in find_sessions(Path(p))]
    if not sessions:
        log(f"Nenhuma sessao (sessao.json) encontrada em {', '.join(map(str, paths))}")
        return None
    tests: list[TestResult] = []
    for s in sessions:
        tests.extend(load_session(s)[1])
    if not tests:
        log("Nenhum teste nas sessoes informadas.")
        return None

    out_dir = Path(out_dir) if out_dir else sessions[0] / "relatorio"
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = pd.DataFrame([compute_stats(t, warmup_min) for t in tests])
    many = len(sessions) > 1
    stats.insert(0, "rotulo", [f"{r.teste} ({r.plataforma}, {r.sessao})" if many else r.teste for r in stats.itertuples()])
    stats = stats.sort_values(["id", "plataforma", "sessao"]).reset_index(drop=True)
    stats.to_csv(out_dir / "resumo.csv", index=False, encoding="utf-8-sig")

    top = top_processes(tests)
    if top is not None:
        top.to_csv(out_dir / "processos_mais_ativos.csv", index=False, encoding="utf-8-sig")

    for t in tests:
        if not t.df.empty:
            name = f"{t.name}__{t.platform}__{t.session}.png" if many else f"{t.name}.png"
            plot_test(t, warmup_min, out_dir / name)
    if len(stats) > 1:
        plot_comparison(stats, out_dir / "comparacao.png")
    log(f"Relatorio gerado em {out_dir}")
    return out_dir