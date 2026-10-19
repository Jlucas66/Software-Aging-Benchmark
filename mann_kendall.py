"""Analise de software aging com o teste de Mann-Kendall, aplicada DEPOIS dos testes.

Nao altera nada nos resultados: so le as pastas de sessao e grava a analise numa
pasta nova.

Exemplos
--------
# Comparar Windows x Linux (cada --sessao pode ser uma sessao, um teste ou uma
# pasta com varias sessoes; o texto antes do '=' e o rotulo usado nas tabelas)
python mann_kendall.py --sessao windows=C:/BenchmarkRuns --sessao linux=D:/resultados_linux

# Uma sessao so
python mann_kendall.py --sessao windows=C:/BenchmarkRuns/sessao_2026-10-20_14-00-00

# Um CSV qualquer (ex.: o seu proprio script de monitoramento)
python mann_kendall.py --csv meu_monitor.csv --coluna-tempo timestamp --colunas ram_mb,vram_mb

Opcoes de metodo: --janela, --aquecimento, --alfa, --metodo, --max-lag (veja --help).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from bench.aging import (METRICS, Params, analyze_csv, analyze_test, comparison_table,
                         console_summary, find_test_dirs, load_test, plot_test)


def parse_session_arg(value: str) -> tuple[str, Path]:
    if "=" in value:
        label, path = value.split("=", 1)
        return label.strip(), Path(path.strip())
    p = Path(value)
    return p.name, p


def main() -> int:
    ap = argparse.ArgumentParser(description="Teste de Mann-Kendall para software aging sobre os resultados do benchmark",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    src = ap.add_argument_group("entrada")
    src.add_argument("--sessao", action="append", default=[], metavar="ROTULO=PASTA",
                     help="pasta de resultados (pode repetir: uma por plataforma)")
    src.add_argument("--csv", type=Path, help="analisar um CSV qualquer em vez das sessoes")
    src.add_argument("--coluna-tempo", default="timestamp", help="(com --csv) coluna de data/hora ou de segundos")
    src.add_argument("--colunas", default="", help="(com --csv) colunas a analisar, separadas por virgula")
    src.add_argument("--rotulo", default="csv", help="(com --csv) rotulo nas tabelas")

    met = ap.add_argument_group("metodo")
    met.add_argument("--janela", default="5min",
                     help="agregacao antes do teste: media por janela (ex.: 1min, 5min, 15min, 1h) ou 0 = sem agregacao [5min]")
    met.add_argument("--aquecimento", type=float, default=30.0,
                     help="minutos descartados no inicio de cada trecho [30]")
    met.add_argument("--alfa", type=float, default=0.05, help="nivel de significancia [0.05]")
    met.add_argument("--metodo", choices=["hamed_rao", "original"], default="hamed_rao",
                     help="qual variante decide a tendencia (as duas sao sempre calculadas) [hamed_rao]")
    met.add_argument("--max-lag", type=int, default=None, help="maior lag na correcao de Hamed-Rao [todos]")
    met.add_argument("--metricas", default="", help=f"metricas a analisar, separadas por virgula [todas: {', '.join(METRICS)}]")

    ap.add_argument("--saida", type=Path, help="pasta de saida [./analises/mann_kendall_<data>]")
    ap.add_argument("--sem-graficos", action="store_true", help="nao gerar os PNGs")
    args = ap.parse_args()

    if not args.sessao and not args.csv:
        ap.error("informe --sessao ROTULO=PASTA (uma ou mais) ou --csv ARQUIVO")

    params = Params(window=str(args.janela), warmup_min=args.aquecimento, alpha=args.alfa,
                    method=args.metodo, max_lag=args.max_lag)
    if args.metricas:
        params.metrics = [m.strip() for m in args.metricas.split(",") if m.strip()]
        unknown = [m for m in params.metrics if m not in METRICS]
        if unknown and not args.csv:
            ap.error(f"metricas desconhecidas: {', '.join(unknown)}. Opcoes: {', '.join(METRICS)}")

    out = args.saida or Path.cwd() / "analises" / f"mann_kendall_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    rows = []
    if args.csv:
        cols = [c.strip() for c in args.colunas.split(",") if c.strip()]
        if not cols:
            ap.error("com --csv, informe --colunas")
        print(f"Analisando {args.csv} ...")
        rows = analyze_csv(args.csv, args.coluna_tempo, cols, args.rotulo, params)
    else:
        for value in args.sessao:
            label, path = parse_session_arg(value)
            dirs = find_test_dirs(path)
            if not dirs:
                print(f"  aviso: nenhum teste (summary.json) encontrado em {path}")
                continue
            for d in dirs:
                test = load_test(d, label)
                print(f"  [{label}] {test.session}/{test.test_name}: {len(test.segments)} trecho(s)")
                test_rows, plot_data = analyze_test(test, params)
                rows.extend(test_rows)
                if plot_data and not args.sem_graficos:
                    gdir = out / "graficos"
                    gdir.mkdir(exist_ok=True)
                    plot_test(test, plot_data, gdir / f"{label}__{test.session}__{test.test_name}.png", params)

    if not rows:
        print("Nada para analisar.")
        return 1

    results = pd.DataFrame(rows)
    results.to_csv(out / "mann_kendall_resultados.csv", index=False, encoding="utf-8-sig")
    comp = comparison_table(results)
    if comp is not None:
        comp.to_csv(out / "comparacao_entre_rotulos.csv", index=False, encoding="utf-8-sig")
    (out / "parametros.json").write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "entradas": args.sessao or [str(args.csv)],
        **params.to_dict(),
        "observacao": "S, Z e p do Mann-Kendall original e com correcao de Hamed & Rao (1998); "
                      "inclinacao de Sen (1968) por hora com IC de Gilbert (1987).",
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.csv:
        print(console_summary(results, params))
    else:
        print(results[["metrica", "n", "tendencia_decisao", "p_hamed_rao", "p_original", "sen_por_hora", "variacao_pct"]].to_string(index=False))
    print(f"\nResultados em: {out}  ({time.monotonic() - started:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
