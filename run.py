"""Ponto de entrada do benchmark. Rode `python run.py --help` para ver os comandos.

Fluxo tipico:
    python run.py check                         # confere instalacao e caminhos
    python run.py build                         # compila o C++ (Editor fechado!)
    python run.py package                       # gera o .exe
    python run.py run --tests all --minutes 3   # validacao rapida dos 7 testes
    python run.py run --tests all --hours 48    # bateria completa
    python run.py report                        # graficos e resumo da ultima sessao
    python mann_kendall.py                      # teste de tendencia (software aging)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bench.config import Config, is_windows


def ok(msg):
    print(f"  [OK] {msg}")


def bad(msg):
    print(f"  [!!] {msg}")


def info(msg):
    print(f"  [..] {msg}")


# ----------------------------------------------------------------------------- comandos

def cmd_list(cfg: Config, args) -> int:
    for t in cfg.tests:
        print(f"\n{t.id}. {t.name}   features: {', '.join(t.features) or 'nenhuma'}")
        for k, v in t.cvars.items():
            print(f"     {k} = {v}")
    return 0


def cmd_check(cfg: Config, args) -> int:
    problems = 0

    def need(cond: bool, good: str, badmsg: str):
        nonlocal problems
        if cond:
            ok(good)
        else:
            bad(badmsg)
            problems += 1
        return cond

    print("\nPython e bibliotecas")
    need(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Use Python 3.10 ou mais novo")
    for mod, pkg in (("psutil", "psutil"), ("pynvml", "nvidia-ml-py"), ("pandas", "pandas"), ("matplotlib", "matplotlib")):
        need(importlib.util.find_spec(mod) is not None, pkg, f"{pkg} nao instalado -> pip install -r requirements.txt")

    print("\nGPU")
    from bench.monitor import GpuReader
    gpu = GpuReader(cfg.bench["monitor"].get("gpu_index", 0))
    if need(gpu.mode != "none", f"{gpu.name} | driver {gpu.driver} | leitura via {gpu.mode}",
            "Nenhuma GPU NVIDIA encontrada (NVML e nvidia-smi indisponiveis)"):
        s = gpu.read()
        info(f"agora: {s.get('gpu_temp_c')} C, {s.get('gpu_power_w')} W, clock {s.get('gpu_clock_mhz')} MHz, VRAM {s.get('vram_mb')} MB")

    # O jogo empacotado e o que roda os testes. Unreal, Content e plugins so sao necessarios
    # na maquina que compila (build/package); nas outras eles aparecem so como informacao.
    exe = cfg.game_exe()
    print("\nJogo empacotado")
    need(exe.exists(), f"Executavel: {exe}",
         f"Jogo nao encontrado em {exe} -> rode 'python run.py package' (Windows) ou copie a pasta do jogo")

    if not is_windows():
        print("\nProton (Linux)")
        from bench.proton import ProtonLauncher
        proton = ProtonLauncher(cfg.bench.get("linux"))
        for msg in proton.problems():
            bad(msg)
            problems += 1
        if not proton.problems():
            ok(f"{proton.launcher} + Proton {proton.proton_version()} ({proton.proton_path})")
            info(f"Prefixo do Wine: {proton.prefix} (criado na primeira execucao)")
        import glob
        nvngx = glob.glob("/usr/lib*/nvidia/wine/nvngx.dll") + glob.glob("/usr/lib*/*/nvidia/wine/nvngx.dll")
        if nvngx:
            ok(f"Biblioteca do DLSS do driver: {nvngx[0]}")
        else:
            info("Nao achei a nvngx.dll do driver NVIDIA. Se o DLSS aparecer como nao suportado, "
                 "instale o driver proprietario completo (o pacote que traz a pasta nvidia/wine)")
        return _finish_check(cfg, problems)

    compiling = not exe.exists()

    def note(cond: bool, good: str, badmsg: str):
        """Problema so na maquina que ainda vai compilar; nas outras, informacao."""
        if compiling:
            return need(cond, good, badmsg)
        ok(good) if cond else info(badmsg + " (so necessario para compilar)")
        return cond

    print("\nUnreal Engine")
    build_bat = cfg.engine_dir / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    note(build_bat.exists(), f"Engine em {cfg.engine_dir}", f"Engine nao encontrada em {cfg.engine_dir}")

    print("\nProjeto UE5Benchmark")
    proj = cfg.project_dir
    if note(cfg.uproject.exists(), f"Projeto: {cfg.uproject}", f"Benchmark.uproject nao encontrado em {proj}"):
        content = proj / "Content"
        note(content.exists() and any(content.rglob("*.umap")), "Pasta Content com o mapa",
             "Pasta Content vazia ou ausente (README, secao 5)")
        from bench.ue_build import REQUIRED_PLUGINS
        missing = [n for n in REQUIRED_PLUGINS if not (proj / "Plugins" / n / f"{n}.uplugin").exists()]
        note(not missing, "Plugin DLSS da NVIDIA em Plugins/", f"Faltam plugins: {', '.join(missing)} (README, secao 6)")
        try:
            enabled = {p.get("Name") for p in json.loads(cfg.uproject.read_text(encoding="utf-8-sig")).get("Plugins", [])
                       if p.get("Enabled")}
        except (OSError, ValueError):
            enabled = set()
        off = [n for n in REQUIRED_PLUGINS if n not in enabled]
        note(not off, "Plugins NVIDIA habilitados no .uproject", f"Plugins desabilitados no .uproject: {', '.join(off)}")
        ini = proj / "Config" / "DefaultEngine.ini"
        text = ini.read_text(encoding="utf-8-sig", errors="ignore") if ini.exists() else ""
        note("DefaultGraphicsRHI_DX12" in text, "DirectX 12 como RHI padrao", "DefaultEngine.ini sem DirectX 12")

    return _finish_check(cfg, problems)


def _finish_check(cfg: Config, problems: int) -> int:
    print("\nResultados")
    try:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        ok(f"Pasta de resultados: {cfg.output_dir}")
    except OSError as e:
        bad(f"Nao consegui criar {cfg.output_dir}: {e}")
        problems += 1

    print(f"\n{'Tudo certo.' if problems == 0 else f'{problems} problema(s) para resolver antes de rodar.'}")
    return 0 if problems == 0 else 1


def cmd_build(cfg: Config, args) -> int:
    from bench.ue_build import build_editor
    return build_editor(cfg, _console_logger())


def cmd_package(cfg: Config, args) -> int:
    from bench.ue_build import package_game
    return package_game(cfg, _console_logger())


def cmd_run(cfg: Config, args) -> int:
    from bench.runner import run_session

    tests = cfg.select_tests(args.tests)
    if args.minutes is not None:
        duration_s = args.minutes * 60
    elif args.hours is not None:
        duration_s = args.hours * 3600
    else:
        duration_s = float(cfg.bench["run"]["default_hours"]) * 3600
    if duration_s < 60:
        print("A duracao minima e 1 minuto.")
        return 1

    exe = cfg.game_exe()
    if not exe.exists():
        print(f"Executavel do jogo nao encontrado: {exe}\nRode 'python run.py package' ou ajuste 'game.exe' em config/bench.json.")
        return 1

    cooldown_s = float(cfg.bench["run"].get("cooldown_minutes", 10)) * 60
    total_s = duration_s * len(tests) + cooldown_s * (len(tests) - 1)
    end = datetime.now() + timedelta(seconds=total_s)
    print("\nPlano da sessao")
    for t in tests:
        print(f"  {t.id}. {t.name:<18} features: {', '.join(t.features) or 'nenhuma'}")
    print(f"\n  Duracao de cada teste : {duration_s / 3600:.2f} h ({duration_s / 60:.1f} min)")
    print(f"  Pausa entre testes    : {cooldown_s / 60:.0f} min")
    print(f"  Tempo total estimado  : {total_s / 3600:.1f} h  -> termina por volta de {end:%d/%m %H:%M}")
    print(f"  Amostragem            : a cada {cfg.bench['run']['sample_interval_s']} s")
    print(f"  Executavel            : {exe}")
    print(f"  Resultados em         : {cfg.output_dir}")
    if not args.yes:
        if input("\nComecar? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            return 1

    _, results = run_session(cfg, tests, duration_s)
    failed = [r for r in results if r.get("status") != "completo"]
    return 1 if failed or len(results) < len(tests) else 0


def cmd_report(cfg: Config, args) -> int:
    from bench.dataset import find_sessions
    from bench.report import generate
    warmup = args.warmup if args.warmup is not None else float(cfg.bench["report"].get("warmup_minutes", 5))
    if args.sessions:
        sessions = [Path(s) for s in args.sessions]
    else:
        found = find_sessions(cfg.output_dir)
        if not found:
            print(f"Nenhuma sessao em {cfg.output_dir}")
            return 1
        sessions = found if args.all_sessions else [max(found, key=lambda p: p.stat().st_mtime)]
    out_dir = None
    if len(sessions) > 1:
        out_dir = cfg.output_dir / f"comparacao_{datetime.now():%Y-%m-%d_%H-%M}"
    return 0 if generate(sessions, warmup, out_dir=out_dir) else 1


def _console_logger():
    import logging
    log = logging.getLogger("bench.console")
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def main() -> int:
    os.chdir(Path(__file__).resolve().parent)
    p = argparse.ArgumentParser(description="Benchmark de estresse de GPU com DLSS (UE5-Benchmark)")
    p.add_argument("--config", help="caminho alternativo para bench.json")
    p.add_argument("--tests-file", help="caminho alternativo para tests.json")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="mostra os testes e os cvars de cada um")
    sub.add_parser("check", help="confere instalacao, GPU, projeto e caminhos")
    sub.add_parser("build", help="compila o codigo C++ (feche o Editor antes)")
    sub.add_parser("package", help="gera o jogo empacotado (.exe)")

    r = sub.add_parser("run", help="executa uma bateria de testes")
    r.add_argument("--tests", default="all", help="'all' ou ids separados por virgula, ex.: 1,2,5")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--hours", type=float, help="duracao de cada teste em horas")
    g.add_argument("--minutes", type=float, help="duracao de cada teste em minutos")
    r.add_argument("--yes", action="store_true", help="nao pedir confirmacao")

    rep = sub.add_parser("report", help="gera resumo e graficos (padrao: sessao mais recente)")
    rep.add_argument("sessions", nargs="*", help="uma ou mais pastas de sessao (varias = comparacao entre elas)")
    rep.add_argument("--all-sessions", action="store_true", help="junta todas as sessoes da pasta de resultados")
    rep.add_argument("--warmup", type=float, help="minutos iniciais a descartar")

    args = p.parse_args()
    cfg = Config(Path(args.config) if args.config else None, Path(args.tests_file) if args.tests_file else None)
    handlers = {"list": cmd_list, "check": cmd_check, "build": cmd_build,
                "package": cmd_package, "run": cmd_run, "report": cmd_report}
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())