"""Amostragem periodica com PresentMon (frames exibidos, incluindo Frame Generation).

O PresentMon grava uma linha por frame. Em 48h isso daria varios GB, entao aqui ele
roda em janelas: `sample_seconds` de gravacao a cada `every_minutes`.
Precisa rodar o terminal como Administrador (o PresentMon usa eventos ETW do Windows).
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path


class PresentMonSampler(threading.Thread):
    def __init__(self, cfg: dict, process_name: str, out_dir: Path, log):
        super().__init__(daemon=True, name="PresentMonSampler")
        self.exe = cfg["exe"]
        self.every_s = float(cfg.get("every_minutes", 10)) * 60.0
        self.sample_s = int(cfg.get("sample_seconds", 30))
        self.args_template = cfg.get("args", [])
        self.process_name = process_name
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log = log
        self._stop_event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.windows_recorded = 0

    def stop(self):
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.join(timeout=self.sample_s + 15)

    def run(self):
        # primeira janela depois de 2 minutos (deixa o jogo estabilizar)
        if self._stop_event.wait(120):
            return
        index = len(list(self.out_dir.glob("pm_*.csv")))
        while not self._stop_event.is_set():
            index += 1
            out = self.out_dir / f"pm_{index:04d}.csv"
            args = [a.replace("{process}", self.process_name)
                     .replace("{output}", str(out))
                     .replace("{seconds}", str(self.sample_s)) for a in self.args_template]
            try:
                self._proc = subprocess.Popen([self.exe, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                _, err = self._proc.communicate(timeout=self.sample_s + 60)
                if self._proc.returncode not in (0, None) and err:
                    self.log.warning("PresentMon terminou com erro: %s", err.strip()[:300])
                elif out.exists():
                    self.windows_recorded += 1
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except FileNotFoundError:
                self.log.error("PresentMon nao encontrado em %s - desativando para este teste.", self.exe)
                return
            if self._stop_event.wait(max(1.0, self.every_s - self.sample_s)):
                return
