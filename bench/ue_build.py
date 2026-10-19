"""Tarefas da Unreal: copiar o codigo C++ para o projeto, ajustar o DefaultEngine.ini,
compilar e empacotar - tudo pela linha de comando, sem precisar abrir o Visual Studio.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import ROOT, Config, is_windows

SOURCE_TEMPLATES = ROOT / "unreal" / "Source" / "Benchmark"


def _q(p) -> str:
    """Coloca aspas em caminhos (formato que a Unreal espera: -Arg="C:/com espaco")."""
    return f'"{p}"'


def _run_bat(bat: Path, args: list[str], log) -> int:
    if not bat.exists():
        log.error("Nao encontrei %s. Confira 'engine_dir' em config/bench.json.", bat)
        return 1
    if is_windows():
        # cmd /s /c ""C:/caminho com espaco/x.bat" args" - forma segura para .bat com aspas
        cmdline = f'cmd /s /c ""{bat}" {" ".join(args)}"'
        log.info("Executando: %s", cmdline)
        return subprocess.run(cmdline).returncode
    log.info("Executando: %s %s", bat, " ".join(args))
    return subprocess.run([str(bat), *[a.replace('"', "") for a in args]]).returncode


def set_ini_values(path: Path, section: str, values: dict[str, str]) -> None:
    """Define chave=valor dentro de uma secao de um .ini da Unreal, preservando o resto."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    header = f"[{section}]"
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
    if idx is None:
        lines += ["", header]
        idx = len(lines) - 1
    end = next((i for i in range(idx + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    for key, val in values.items():
        found = False
        for i in range(idx + 1, end):
            if lines[i].split("=", 1)[0].strip() == key:
                lines[i] = f"{key}={val}"
                found = True
        if not found:
            lines.insert(end, f"{key}={val}")
            end += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_to_project(cfg: Config, log) -> int:
    project = cfg.project_dir
    src_dir = project / "Source" / "Benchmark"
    if not cfg.uproject.exists() or not src_dir.exists():
        log.error("Projeto nao encontrado em %s (esperava Benchmark.uproject e Source/Benchmark).", project)
        return 1

    # Backup FORA da pasta Source (tudo dentro de Source e compilado pela Unreal)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = project / "_bench_backup" / stamp
    (backup / "Source").mkdir(parents=True, exist_ok=True)
    (backup / "Config").mkdir(parents=True, exist_ok=True)

    for tpl in sorted(SOURCE_TEMPLATES.iterdir()):
        target = src_dir / tpl.name
        if target.exists():
            shutil.copy2(target, backup / "Source" / tpl.name)
        shutil.copy2(tpl, target)
        log.info("Copiado: %s", target)

    ini = project / "Config" / "DefaultEngine.ini"
    if ini.exists():
        shutil.copy2(ini, backup / "Config" / ini.name)
    set_ini_values(ini, "/Script/WindowsTargetPlatform.WindowsTargetSettings",
                   {"DefaultGraphicsRHI": "DefaultGraphicsRHI_DX12"})
    if cfg.bench["unreal"].get("enable_hardware_ray_tracing", True):
        set_ini_values(ini, "/Script/Engine.RendererSettings", {
            "r.RayTracing": "True",
            "r.SkinCache.CompileShaders": "True",
            "r.Lumen.HardwareRayTracing": "True",
        })
        log.info("DefaultEngine.ini: DirectX 12 + ray tracing por hardware ligados.")
    else:
        log.info("DefaultEngine.ini: DirectX 12 ligado (ray tracing por hardware desligado).")

    log.info("Backup dos arquivos originais em: %s", backup)
    return 0


def build_editor(cfg: Config, log) -> int:
    """Compila o codigo C++ do projeto (alvo do Editor). O Editor precisa estar FECHADO."""
    bat = cfg.engine_dir / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    args = [f"{cfg.project_name}Editor", "Win64", "Development",
            f"-Project={_q(cfg.uproject)}", "-WaitMutex", "-NoHotReloadFromIDE"]
    return _run_bat(bat, args, log)


def package_game(cfg: Config, log) -> int:
    """Gera o jogo empacotado (Development, para manter os logs) em package_dir."""
    bat = cfg.engine_dir / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    cfg.package_dir.mkdir(parents=True, exist_ok=True)
    args = ["BuildCookRun", f"-project={_q(cfg.uproject)}", "-noP4", "-platform=Win64",
            "-clientconfig=Development", "-build", "-cook", "-stage", "-pak", "-archive",
            f"-archivedirectory={_q(cfg.package_dir)}", "-utf8output"]
    return _run_bat(bat, args, log)
