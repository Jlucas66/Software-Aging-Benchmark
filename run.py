"""Ponto de entrada do benchmark. Rode `python run.py --help` para ver os comandos.

Fluxo tipico:
    python run.py check                     # confere instalacao e caminhos
    python run.py apply                     # copia o codigo C++ para o projeto Unreal
    python run.py build                     # compila (Editor fechado!)
    python run.py package                   # gera o .exe
    python run.py run --tests all --minutes 3   # validacao rapida dos 7 testes
    python run.py run --tests all --hours 48    # bateria completa
    python run.py report                    # (re)gera os graficos da ultima sessao
"""

from __future__ import annotations

import argparse
import importlib.util
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
    print("\nPython e bibliotecas")
    ok(f"Python {sys.version.split()[0]}") if sys.version_info >= (3, 10) else bad("Use Python 3.10 ou mais novo")
    for mod, pkg in (("psutil", "psutil"), ("pynvml", "nvidia-ml-py"), ("pandas", "pandas"), ("matplotlib", "matplotlib")):
        if importlib.util.find_spec(mod):
            ok(pkg)
        else:
            bad(f"{pkg} nao instalado -> pip install -r requirements.txt")
            problems += 1

    print("\nGPU")
    from bench.monitor import GpuReader
    gpu = GpuReader(cfg.bench["monitor"].get("gpu_index", 0))
    if gpu.mode == "none":
        bad("Nenhuma GPU NVIDIA encontrada (NVML e nvidia-smi indisponiveis)")
        problems += 1
    else:
        ok(f"{gpu.name} | driver {gpu.driver} | leitura via {gpu.mode}")
        sample = gpu.read()
        info(f"agora: {sample.get('gpu_temp_c')} C, {sample.get('power_w')} W, clock SM {sample.get('clock_sm_mhz')} MHz")

    print("\nUnreal Engine e projeto")
    build_bat = cfg.engine_dir / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    ok(f"Engine em {cfg.engine_dir}") if build_bat.exists() else (bad(f"Engine nao encontrada em {cfg.engine_dir}"), None)
    problems += 0 if build_bat.exists() else 1
    if cfg.uproject.exists():
        ok(f"Projeto: {cfg.uproject}")
        plugins = list((cfg.project_dir / "Plugins").glob("**/*.uplugin")) if (cfg.project_dir / "Plugins").exists() else []
        dlss = [p.stem for p in plugins if any(k in p.stem.lower() for k in ("dlss", "streamline", "nis"))]
        ok(f"Plugins NVIDIA no projeto: {', '.join(sorted(dlss))}") if dlss else bad("Plugin DLSS nao encontrado em <projeto>/Plugins")
        problems += 0 if dlss else 1
        ini = cfg.project_dir / "Config" / "DefaultEngine.ini"
        text = ini.read_text(encoding="utf-8-sig", errors="ignore") if ini.exists() else ""
        ok("DirectX 12 como RHI padrao") if "DefaultGraphicsRHI_DX12" in text else bad("RHI padrao nao e DX12 (rode: python run.py apply)")
        src = cfg.project_dir / "Source" / "Benchmark" / "BenchmarkManager.cpp"
        modified = src.exists() and "BenchCVars" in src.read_text(encoding="utf-8", errors="ignore")
        ok("Codigo C++ do benchmark aplicado") if modified else bad("Codigo C++ original (rode: python run.py apply)")
    else:
        bad(f"Projeto nao encontrado em {cfg.project_dir}")
        problems += 1

    print("\nJogo empacotado")
    exe = cfg.game_exe()
    ok(f"Executavel: {exe}") if exe.exists() else info(f"Ainda nao empacotado (esperado em {exe})")

    print("\nSaida e ferramentas")
    try:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        ok(f"Pasta de resultados: {cfg.output_dir}")
    except OSError as e:
        bad(f"Nao consegui criar {cfg.output_dir}: {e}")
        problems += 1
    pm = cfg.bench["presentmon"]
    if pm.get("enabled"):
        ok(f"PresentMon: {pm['exe']}") if Path(pm["exe"]).exists() else (bad(f"PresentMon nao encontrado: {pm['exe']}"), None)
        if is_windows():
            import ctypes
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            ok("Terminal como Administrador") if admin else bad("PresentMon precisa do terminal aberto como Administrador")
    else:
        info("PresentMon desligado (FPS exibido com Frame Generation nao sera medido)")

    print(f"\n{'Tudo certo.' if problems == 0 else f'{problems} problema(s) para resolver antes de rodar.'}")
    return 0 if problems == 0 else 1


def cmd_apply(cfg: Config, args) -> int:
    from bench.ue_build import apply_to_project
    return apply_to_project(cfg, _console_logger())


def cmd_build(cfg: Config, args) -> int:
    from bench.ue_build import build_editor
    return build_editor(cfg, _console_logger())


def cmd_package(cfg: Config, args) -> int:
    from bench.ue_build import package_game
    return package_game(cfg, _console_logger())


def cmd_run(cfg: Config, args) -> int:
    from bench.runner import new_session_dir, run_session, setup_logging

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
    if not args.yes:
        if input("\nComecar? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            return 1

    session_dir = new_session_dir(cfg)
    log = setup_logging(session_dir)
    log.info("Sessao: %s", session_dir)
    try:
        results = run_session(cfg, tests, duration_s, log, session_dir)
    except KeyboardInterrupt:
        log.warning("Sessao interrompida. Os dados ja gravados ficam em %s", session_dir)
        results = []

    try:
        from bench.report import generate
        generate(session_dir, float(cfg.bench["report"].get("warmup_minutes", 5)), log.info)
    except Exception as e:  # o relatorio nunca deve esconder o resultado dos testes
        log.error("Falha ao gerar o relatorio (rode 'python run.py report' depois): %s", e)

    failed = [r for r in results if r.get("status") != "completed"]
    for r in results:
        log.info("  %-18s %s", r["test_name"], r["status"])
    return 1 if failed or not results else 0


def cmd_report(cfg: Config, args) -> int:
    from bench.report import generate
    warmup = args.warmup if args.warmup is not None else float(cfg.bench["report"].get("warmup_minutes", 5))
    if args.sessions:
        sessions = [Path(s) for s in args.sessions]
    else:
        found = sorted(cfg.output_dir.glob("sessao_*"))
        if not found:
            print(f"Nenhuma sessao em {cfg.output_dir}")
            return 1
        sessions = found if args.all_sessions else [found[-1]]
    out_dir = None
    if len(sessions) > 1:
        out_dir = cfg.output_dir / f"comparacao_{datetime.now():%Y-%m-%d_%H-%M-%S}"
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
    sub.add_parser("apply", help="copia o codigo C++ para o projeto e ajusta o DefaultEngine.ini")
    sub.add_parser("build", help="compila o codigo C++ (feche o Editor antes)")
    sub.add_parser("package", help="gera o jogo empacotado (.exe)")

    r = sub.add_parser("run", help="executa uma bateria de testes")
    r.add_argument("--tests", default="all", help="'all' ou ids separados por virgula, ex.: 1,2,5")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--hours", type=float, help="duracao de cada teste em horas")
    g.add_argument("--minutes", type=float, help="duracao de cada teste em minutos")
    r.add_argument("--yes", action="store_true", help="nao pedir confirmacao")

    rep = sub.add_parser("report", help="gera os graficos (padrao: sessao mais recente)")
    rep.add_argument("sessions", nargs="*", help="uma ou mais pastas de sessao (varias = comparacao entre elas)")
    rep.add_argument("--all-sessions", action="store_true", help="junta todas as sessoes da pasta de resultados")
    rep.add_argument("--warmup", type=float, help="minutos iniciais a descartar")

    args = p.parse_args()
    cfg = Config(Path(args.config) if args.config else None, Path(args.tests_file) if args.tests_file else None)
    handlers = {"list": cmd_list, "check": cmd_check, "apply": cmd_apply, "build": cmd_build,
                "package": cmd_package, "run": cmd_run, "report": cmd_report}
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
