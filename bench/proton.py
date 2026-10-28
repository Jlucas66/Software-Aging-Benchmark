"""Abrir o jogo no Linux pelo Proton (umu-launcher).

O plugin DLSS da Unreal so existe para Windows, entao no Linux roda o MESMO Benchmark.exe
empacotado no Windows, traduzido pelo Proton:
    DirectX 12 -> Vulkan (VKD3D-Proton)   e   NVAPI/DLSS -> driver NVIDIA (DXVK-NVAPI)

O umu-launcher roda o Proton fora da Steam, dentro do mesmo ambiente (Steam Runtime) que a
Steam usaria. Configuracao em config/bench.json, bloco "linux".
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def win_path(p: Path) -> str:
    """Caminho do Linux no formato que o jogo (dentro do Wine) entende: Z: = raiz do Linux."""
    return "Z:" + Path(p).resolve().as_posix()


class ProtonLauncher:
    def __init__(self, linux_cfg: dict):
        c = linux_cfg or {}
        launcher = c.get("launcher", "umu-run")
        # aceita so o nome (se estiver no PATH) ou o caminho completo, inclusive com ~
        self.launcher = str(_expand(launcher)) if ("/" in launcher or launcher.startswith("~")) else launcher
        self.proton_path = _expand(c.get("proton_path", ""))
        self.prefix = _expand(c.get("wine_prefix", "~/.local/share/bench-prefix"))
        self.extra_env = {k: str(v) for k, v in (c.get("env") or {}).items()}

    # ------------------------------------------------------------------ comando
    def env(self) -> dict:
        env = dict(os.environ)
        env.update({
            "GAMEID": "umu-0",                 # sem correcoes especificas de nenhum jogo
            "PROTONPATH": str(self.proton_path),
            "WINEPREFIX": str(self.prefix),
            "UMU_RUNTIME_UPDATE": "0",         # nao atualiza o Steam Runtime no meio da pesquisa
        })
        env.update(self.extra_env)
        return env

    def command(self, exe: Path, tokens: list[str]) -> list[str]:
        launcher = shutil.which(self.launcher) or self.launcher
        return [launcher, str(exe), *[t.replace('"', "") for t in tokens]]

    # ------------------------------------------------------------------ informacoes
    def proton_version(self) -> str | None:
        f = self.proton_path / "version"
        try:
            return f.read_text(encoding="utf-8", errors="ignore").strip().split()[-1]
        except OSError:
            return self.proton_path.name or None

    def info(self) -> dict:
        return {
            "lancador": self.launcher,
            "proton": self.proton_version(),
            "proton_path": str(self.proton_path),
            "wine_prefix": str(self.prefix),
            "variaveis": {**self.extra_env, "UMU_RUNTIME_UPDATE": "0"},
        }

    def problems(self) -> list[str]:
        out = []
        if not shutil.which(self.launcher):
            out.append(f"'{self.launcher}' nao encontrado: instale o umu-launcher (COMANDOS.md, secao Linux)")
        if not str(self.proton_path) or not (self.proton_path / "proton").exists():
            out.append(f"Proton nao encontrado em {self.proton_path} (confira 'linux.proton_path' no bench.json)")
        return out

    # ------------------------------------------------------------------ limpeza
    @staticmethod
    def kill_leftovers(exe_name: str) -> int:
        """Fecha processos do jogo que tenham sobrado dentro do Wine (ex.: depois de um travamento)."""
        if psutil is None:
            return 0
        name = exe_name.lower()
        killed = 0
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() == name:
                    p.kill()
                    killed += 1
            except psutil.Error:
                pass
        return killed