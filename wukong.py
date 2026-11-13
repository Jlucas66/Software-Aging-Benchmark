"""Benchmark de software aging com o Black Myth: Wukong Benchmark Tool.

Mesmo metodo do run.py (7 testes, duracao configuravel, uma linha de metricas a cada 5 s,
relatorio e Mann-Kendall), usando a cena do Benchmark Tool em vez do UE5-Benchmark.

Comandos:
    python wukong.py check                      confere Steam, Benchmark Tool, perfis, PresentMon/MangoHud
    python wukong.py perfil salvar 02_dlss      guarda as configuracoes ATUAIS do jogo como perfil de um teste
    python wukong.py perfil mostrar [nome]      mostra um perfil (ou "atual" = o ini do jogo agora)
    python wukong.py perfil diff A B            o que muda entre dois perfis (descobrir chaves do menu)
    python wukong.py calibrar                   mostra a posicao do mouse na janela do jogo (para acoes)
    python wukong.py validar --tests 2          teste curto (12 min) com diagnostico do loop e do DLSS
    python wukong.py run --tests all --hours 48 bateria completa
    python wukong.py report                     relatorio da sessao mais recente

Passo a passo completo em WUKONG.md.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bench.config import is_windows  # noqa: E402
from bench.wukong import (PROFILES_DIR, GameIni, InputDriver, WukongConfig,  # noqa: E402
                          WukongInstall, find_game_pid, steam_command)

DEFAULT_BENCH = ROOT / "config" / "wukong.json"
DEFAULT_TESTS = ROOT / "config" / "tests_wukong.json"

# Chaves do menu mostradas no resumo de um perfil
SHOW_UI = ["Dlss", "SuperResolutionSampling", "ImageQuality", "InsertFrame", "Rtx", "RtxLevel", "QualityLevel",
           "Vsync", "LockFrameRate", "FrameRateQualityFirst", "ScreenMode", "ScreenResolution", "MotionBlur", "Dx12"]


def ok(m):
    print(f"  [OK] {m}")


def bad(m):
    print(f"  [!!] {m}")


def note(m):
    print(f"  [..] {m}")


def game_running() -> bool:
    return find_game_pid(0) is not None


# ----------------------------------------------------------------------------- comandos

def cmd_list(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    print()
    for t in cfg.tests:
        prof = cfg.profile_path(t)
        status = "perfil OK" if prof.exists() else "SEM PERFIL"
        print(f"  {t['id']}. {t['name']:<18} {status:<11} features: {', '.join(t['features']) or 'nenhuma'}")
    print(f"\n  Perfis em {PROFILES_DIR}")
    return 0


def cmd_check(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    problems = 0
    print("\nSteam e Benchmark Tool")
    steam = steam_command()
    if steam:
        ok(f"Steam: {' '.join(steam)}")
    else:
        bad("Steam nao encontrada")
        problems += 1
    if inst.install_dir and inst.install_dir.exists():
        ok(f"Benchmark Tool: {inst.install_dir}")
    else:
        bad("Black Myth: Wukong Benchmark Tool nao encontrado. Instale pela Steam (gratis) "
            "ou preencha wukong.install_dir em config/wukong.json")
        return 1
    if inst.ini and inst.ini.exists():
        ok(f"Configuracoes: {inst.ini}")
    else:
        bad("GameUserSettings.ini ainda nao existe: abra o Benchmark Tool uma vez pela Steam, aceite os "
            "termos, espere os shaders compilarem e feche")
        problems += 1
    hist = [d for d in inst.history_dirs() if d.exists()]
    if hist:
        ok(f"Resultados das voltas: {hist[0]} ({len(list(hist[0].iterdir()))} arquivo(s))")
    else:
        note("Pasta de resultados das voltas ainda nao existe (aparece depois da 1a volta completa): "
             + ", ".join(str(d) for d in inst.history_dirs()[:1]))
    dlls = inst.dll_versions()
    if dlls:
        ok("DLLs da NVIDIA no jogo: " + ", ".join(f"{k} ({v['bytes'] // 1024} KB)" for k, v in dlls.items()))
    if not is_windows():
        pfx = inst.library / "steamapps" / "compatdata" / "3132990" if inst.library else None
        if pfx and pfx.exists():
            ok(f"Prefixo do Proton: {pfx}")
        else:
            bad("Prefixo do Proton nao encontrado: abra o Benchmark Tool uma vez pela Steam com o Proton escolhido")
            problems += 1

    print("\nPerfis dos testes")
    for t in cfg.tests:
        p = cfg.profile_path(t)
        if p.exists():
            ui = GameIni.load(p).ui()
            ok(f"{t['name']:<16} Dlss={ui.get('Dlss')} SR={ui.get('SuperResolutionSampling')} "
               f"InsertFrame={ui.get('InsertFrame')} Rtx={ui.get('Rtx')}/{ui.get('RtxLevel')} "
               f"ImageQuality={ui.get('ImageQuality')}")
        else:
            bad(f"{t['name']:<16} sem perfil: configure no jogo e rode 'python wukong.py perfil salvar {t['perfil']}'")
            problems += 1

    print("\nMedicao de FPS")
    fr = cfg.w.get("frames") or {}
    fonte = fr.get("fonte", "nenhuma")
    if fonte == "presentmon":
        exe = fr.get("presentmon_exe") or "PresentMon.exe"
        if Path(exe).exists() or shutil.which(exe):
            ok(f"PresentMon: {exe}")
        else:
            bad(f"PresentMon nao encontrado ({exe}). Baixe em github.com/GameTechDev/PresentMon/releases")
            problems += 1
    elif fonte == "mangohud":
        d = Path(fr.get("mangohud_dir") or "~/wukong_mangohud").expanduser()
        (ok if d.exists() else bad)(f"Pasta de logs do MangoHud: {d}"
                                    + ("" if d.exists() else " (crie e configure as opcoes de inicializacao)"))
        if shutil.which("mangohud"):
            ok("MangoHud instalado")
        else:
            bad("MangoHud nao instalado (sudo apt install mangohud)")
            problems += 1
    else:
        note("Sem fonte de FPS (frames.fonte = nenhuma): so as metricas de sistema/GPU e o FPS por volta")

    print("\nTeclado e mouse (acoes)")
    if cfg.w.get("acoes_inicio") or cfg.w.get("acoes_nova_volta"):
        if not is_windows() and not shutil.which("xdotool"):
            bad("xdotool nao instalado (sudo apt install xdotool); a sessao precisa ser X11/XWayland")
            problems += 1
        else:
            ok(f"{len(cfg.w.get('acoes_inicio', []))} acao(oes) de inicio, "
               f"{len(cfg.w.get('acoes_nova_volta', []))} de nova volta")
    else:
        note("Sem acoes de teclado/mouse: depende do argumento -benchmark e do modo de repeticao salvo no perfil")

    print("\nMonitoramento")
    try:
        from bench.monitor import GpuReader
        g = GpuReader(cfg.bench.get("monitor", {}).get("gpu_index", 0))
        (ok if g.name != "desconhecida" else bad)(f"GPU: {g.name} (driver {g.driver})")
    except Exception as e:
        bad(f"GPU: {e}")
        problems += 1
    try:
        import psutil  # noqa: F401
        ok("psutil instalado")
    except ImportError:
        bad("psutil nao instalado (pip install -r requirements.txt)")
        problems += 1
    print(f"\n{'Tudo certo.' if not problems else f'{problems} problema(s) acima.'}")
    return 1 if problems else 0


def _profile_summary(ini: GameIni) -> list[str]:
    ui = ini.ui()
    s = ini.summary()["principal"]
    lines = [f"    {k:<24} {ui[k]}" for k in SHOW_UI if k in ui]
    lines.append(f"    {'Resolucao (ResolutionSize)':<24} {s.get('ResolutionSizeX')}x{s.get('ResolutionSizeY')}")
    lines.append(f"    {'bUseVSync / FrameRateLimit':<24} {s.get('bUseVSync')} / {s.get('FrameRateLimit')}")
    return lines


def cmd_perfil(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    def load(name: str) -> tuple[GameIni, Path]:
        p = inst.ini if name == "atual" else PROFILES_DIR / f"{name}.ini"
        if not p or not p.exists():
            raise SystemExit(f"Perfil '{name}' nao encontrado ({p}).")
        return GameIni.load(p), p

    if args.acao == "salvar":
        if not args.nomes:
            raise SystemExit("Uso: python wukong.py perfil salvar <nome>  (ex.: 02_dlss)")
        if game_running():
            raise SystemExit("Feche o Benchmark Tool antes: ele so grava as configuracoes no arquivo ao sair.")
        name = args.nomes[0]
        dst = PROFILES_DIR / f"{name}.ini"
        if dst.exists() and not args.forcar:
            raise SystemExit(f"{dst.name} ja existe. Use --forcar para substituir.")
        shutil.copy2(inst.ini, dst)
        print(f"\nPerfil salvo: {dst}")
        print("\n".join(_profile_summary(GameIni.load(dst))))
        return 0
    if args.acao == "mostrar":
        name = args.nomes[0] if args.nomes else "atual"
        ini, p = load(name)
        print(f"\n{p}")
        print("\n".join(_profile_summary(ini)))
        if args.tudo:
            for k, v in ini.ui().items():
                print(f"    UI  {k:<26} {v}")
            for k, v in ini.scalability().items():
                print(f"    sg  {k:<26} {v}")
        return 0
    if args.acao == "diff":
        if len(args.nomes) != 2:
            raise SystemExit("Uso: python wukong.py perfil diff <A> <B>   (use 'atual' para o ini do jogo agora)")
        (a, _), (b, _) = load(args.nomes[0]), load(args.nomes[1])
        sa, sb = a.summary(), b.summary()
        diffs = 0
        for part in ("UISettingData", "ScalabilityGroups", "principal"):
            keys = list(dict.fromkeys(list(sa[part]) + list(sb[part])))
            for k in keys:
                if sa[part].get(k) != sb[part].get(k):
                    print(f"  {part:<18} {k:<26} {sa[part].get(k)!s:>10}  ->  {sb[part].get(k)}")
                    diffs += 1
        # linhas fora das chaves conhecidas (ex.: uma opcao de repeticao)
        la, lb = set(a.lines), set(b.lines)
        for line in sorted(lb - la):
            k = line.split("=", 1)[0].strip()
            if k and k not in ("UISettingData",) and not k.startswith(("sg.", "LastGPUBenchmark", "LastCPUBenchmark")):
                if all(k not in sb[p] for p in ("principal", "ScalabilityGroups")):
                    print(f"  {'(linha)':<18} {line}")
                    diffs += 1
        print(f"\n{diffs} diferenca(s).")
        return 0
    if args.acao == "listar":
        for p in sorted(PROFILES_DIR.glob("*.ini")):
            print(f"  {p.stem}")
        return 0
    raise SystemExit("Acoes: salvar, mostrar, diff, listar")


def cmd_calibrar(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    drv = InputDriver(__import__("logging").getLogger("bench"))
    print("\nAbra o Benchmark Tool, deixe o mouse em cima de um botao e anote os numeros.")
    print("Use-os nas acoes de config/wukong.json, ex.: \"Click:0.115,0.452\". Ctrl+C para sair.\n")
    try:
        while True:
            win = drv.window(find_game_pid(0))
            if win is None:
                print("\r  janela do jogo nao encontrada...            ", end="", flush=True)
            else:
                fx, fy = drv.cursor_fraction(win)
                print(f"\r  janela {win[3]}x{win[4]}   mouse: {fx:.3f},{fy:.3f}        ", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    return 0


def _duration(cfg, args, default_min=None) -> float:
    if getattr(args, "minutes", None) is not None:
        return args.minutes * 60
    if getattr(args, "hours", None) is not None:
        return args.hours * 3600
    if default_min is not None:
        return default_min * 60
    return float(cfg.bench["run"]["default_hours"]) * 3600


def _preflight(cfg, inst, tests) -> bool:
    if not inst.install_dir or not inst.ini or not inst.ini.exists():
        print("Benchmark Tool ou GameUserSettings.ini nao encontrado. Rode 'python wukong.py check'.")
        return False
    if not steam_command():
        print("Steam nao encontrada.")
        return False
    missing = [t["name"] for t in tests if not cfg.profile_path(t).exists()]
    if missing:
        print("Testes sem perfil (usariam o ini atual do jogo): " + ", ".join(missing))
        print("Configure cada teste no jogo e rode 'python wukong.py perfil salvar <nome>'.")
        return False
    if game_running():
        print("Feche o Benchmark Tool antes de comecar.")
        return False
    return True


def cmd_run(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    from bench.wukong import run_session
    tests = cfg.select(args.tests)
    duration_s = _duration(cfg, args)
    if duration_s < 120:
        print("A duracao minima e 2 minutos (uma volta do Benchmark Tool leva ~3 min).")
        return 1
    if not _preflight(cfg, inst, tests):
        return 1
    cooldown_s = float(cfg.bench["run"].get("cooldown_minutes", 10)) * 60
    total_s = duration_s * len(tests) + cooldown_s * (len(tests) - 1)
    print("\nPlano da sessao (Black Myth: Wukong Benchmark Tool)")
    for t in tests:
        print(f"  {t['id']}. {t['name']:<18} perfil: {t['perfil']}")
    print(f"\n  Duracao de cada teste : {duration_s / 3600:.2f} h")
    print(f"  Pausa entre testes    : {cooldown_s / 60:.0f} min")
    print(f"  Termina por volta de  : {datetime.now() + timedelta(seconds=total_s):%d/%m %H:%M}")
    print(f"  Modo de loop          : {cfg.w.get('modo_loop', 'interno')}")
    print(f"  Medicao de FPS        : {(cfg.w.get('frames') or {}).get('fonte', 'nenhuma')}")
    print(f"  Resultados em         : {cfg.output_dir}")
    if not args.yes and input("\nComecar? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
        print("Cancelado.")
        return 1
    session = run_session(cfg, tests, duration_s)
    bad_tests = [t for t in session.data["testes"] if t["status"] != "completo"]
    return 1 if bad_tests or len(session.data["testes"]) < len(tests) else 0


def cmd_validar(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    from bench.wukong import run_session
    tests = cfg.select(args.tests)
    duration_s = _duration(cfg, args, default_min=12)
    if not _preflight(cfg, inst, tests):
        return 1
    print(f"\nValidacao: {', '.join(t['name'] for t in tests)}, {duration_s / 60:.0f} min cada. "
          "Nao mexa no computador durante o teste.\n")
    session = run_session(cfg, tests, duration_s)
    print("\n" + "=" * 70 + "\nDIAGNOSTICO\n")
    for e in session.data["testes"]:
        print(f"{e['nome']}: {e['status']}, {e['amostras']} amostras, {e['voltas']} volta(s) concluida(s), "
              f"aberto {e['execucoes']} vez(es)")
        if e["status"].startswith("falhou (nao comecou)"):
            bad("O teste nao comecou sozinho. O argumento -benchmark nao funcionou nesta versao: configure "
                "'acoes_inicio' (WUKONG.md, passo 6).")
        if e["voltas"] == 0 and e["status"] == "completo":
            note("Nenhuma volta terminou no periodo (cada volta leva ~3 min). Rode com --minutes 12 ou mais.")
        if e.get("reaberturas_fim_de_volta"):
            bad(f"O jogo parou {e['reaberturas_fim_de_volta']} vez(es) no fim da volta e foi reaberto: o modo de "
                "repeticao NAO esta ativo. Para aging, ligue-o (WUKONG.md, passo 5) ou use acoes_nova_volta.")
        elif e["voltas"] >= 2 and e["execucoes"] == 1:
            ok("Varias voltas no MESMO processo: o modo de repeticao funciona.")
        if e.get("voltas_reiniciadas_por_acao"):
            note(f"{e['voltas_reiniciadas_por_acao']} volta(s) reiniciada(s) pelas acoes (mesmo processo).")
        ap = e.get("configuracao_aplicada")
        if ap:
            ok(f"O jogo usou: Dlss={ap.get('Dlss')} InsertFrame={ap.get('InsertFrame')} Rtx={ap.get('Rtx')} "
               f"ImageQuality={ap.get('ImageQuality')} resolucao={ap.get('ScreenResolution')}")
        for p in e["problemas"]:
            bad(p)
        csv = session.dir / e["arquivo"]
        if csv.exists():
            import pandas as pd
            df = pd.read_csv(csv)
            if "fps" in df and df["fps"].notna().any():
                ok(f"FPS medido a cada {cfg.bench['run']['sample_interval_s']} s: media {df['fps'].mean():.1f}"
                   + (f", exibido (FG) {df['fps_exibido'].mean():.1f}" if "fps_exibido" in df and df['fps_exibido'].notna().any() else ""))
            else:
                note("Sem FPS nas amostras de 5 s (fonte de frames desligada ou sem dados).")
        print()
    print(f"Sessao: {session.dir}")
    return 0


def cmd_report(cfg: WukongConfig, inst: WukongInstall, args) -> int:
    from bench.dataset import find_sessions
    from bench.report import generate
    warmup = args.warmup if args.warmup is not None else float(cfg.bench.get("report", {}).get("warmup_minutes", 5))
    if args.sessions:
        sessions = [Path(s) for s in args.sessions]
    else:
        found = find_sessions(cfg.output_dir)
        if not found:
            print(f"Nenhuma sessao em {cfg.output_dir}")
            return 1
        sessions = found if args.all_sessions else [max(found, key=lambda p: p.stat().st_mtime)]
    out_dir = cfg.output_dir / f"comparacao_{datetime.now():%Y-%m-%d_%H-%M}" if len(sessions) > 1 else None
    return 0 if generate(sessions, warmup, out_dir=out_dir) else 1


def main() -> int:
    os.chdir(ROOT)
    p = argparse.ArgumentParser(description="Benchmark de software aging com o Black Myth: Wukong Benchmark Tool")
    p.add_argument("--config", default=str(DEFAULT_BENCH))
    p.add_argument("--tests-file", default=str(DEFAULT_TESTS))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="testes e perfis")
    sub.add_parser("check", help="confere instalacao, perfis e ferramentas")
    pf = sub.add_parser("perfil", help="salvar / mostrar / diff / listar perfis de configuracao")
    pf.add_argument("acao", choices=["salvar", "mostrar", "diff", "listar"])
    pf.add_argument("nomes", nargs="*")
    pf.add_argument("--forcar", action="store_true", help="substituir perfil existente")
    pf.add_argument("--tudo", action="store_true", help="mostrar todas as chaves")
    sub.add_parser("calibrar", help="posicao do mouse na janela do jogo, para as acoes")
    for name, hlp in (("run", "executa uma bateria"), ("validar", "teste curto com diagnostico")):
        r = sub.add_parser(name, help=hlp)
        r.add_argument("--tests", default="all" if name == "run" else "2")
        g = r.add_mutually_exclusive_group()
        g.add_argument("--hours", type=float)
        g.add_argument("--minutes", type=float)
        if name == "run":
            r.add_argument("--yes", action="store_true")
    rep = sub.add_parser("report", help="resumo e graficos")
    rep.add_argument("sessions", nargs="*")
    rep.add_argument("--all-sessions", action="store_true")
    rep.add_argument("--warmup", type=float)
    args = p.parse_args()

    cfg = WukongConfig(Path(args.config), Path(args.tests_file))
    inst = WukongInstall.detect(cfg.w)
    handlers = {"list": cmd_list, "check": cmd_check, "perfil": cmd_perfil, "calibrar": cmd_calibrar,
                "run": cmd_run, "validar": cmd_validar, "report": cmd_report}
    return handlers[args.command](cfg, inst, args)


if __name__ == "__main__":
    sys.exit(main())
