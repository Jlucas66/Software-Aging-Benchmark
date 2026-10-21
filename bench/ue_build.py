"""Compilar e empacotar o projeto Unreal pela linha de comando (sem abrir o Visual Studio).

O codigo C++ do benchmark fica direto em UE5Benchmark/Source/Benchmark: edite la.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Config, is_windows

# Plugins da NVIDIA que o codigo C++ usa (precisam estar em <projeto>/Plugins e habilitados)
REQUIRED_PLUGINS = ["DLSS", "StreamlineCore", "StreamlineDLSSG", "StreamlineReflex"]


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