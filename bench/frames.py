"""FPS e tempos de frame de um jogo que NAO grava as proprias metricas (ex.: Black Myth: Wukong).

No UE5-Benchmark quem grava uma linha a cada 5 s e o proprio jogo (engine_samples.csv). Num
jogo de terceiros, este modulo faz esse papel: a cada `interval_s` le os frames medidos por
uma ferramenta externa e grava a mesma linha no mesmo formato, entao o TestMonitor, o CSV de
cada teste, o relatorio e o Mann-Kendall funcionam sem mudar nada.

Fontes de frames (escolha em config/wukong.json -> "frames"):
  presentmon  Windows. PresentMon (Intel, codigo aberto) mede cada frame apresentado. Com a
              coluna FrameType (PresentMon 2.x) separa frames renderizados dos gerados pelo
              Frame Generation -> "fps" (renderizado) e "fps_exibido".
  mangohud    Linux. MangoHud grava um CSV (configurado nas opcoes de inicializacao da Steam).
              Mede frames APRESENTADOS: com Frame Generation, "fps" inclui os gerados.
  nenhuma     So o relogio: grava a linha (sem FPS) para que as metricas do sistema, processo e
              GPU continuem a cada 5 s.

Nada e gravado enquanto o jogo esta fechado, igual ao UE5-Benchmark.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ENGINE_HEADER = ["timestamp_utc", "avg_fps", "p99_frametime_ms", "gpu_time_ms", "game_thread_ms",
                 "render_thread_ms", "dlssg_fps", "dlssg_frames_presented", "frames_no_intervalo"]

# Nomes das colunas no PresentMon 2.x e no 1.x (--v1_metrics), nessa ordem de preferencia
PM_INTERVAL = ("MsBetweenPresents", "FrameTime")
PM_DISPLAYED = ("DisplayedTime", "MsBetweenDisplayChange")
PM_GPU = ("MsGPUBusy", "GPUBusy", "MsGPUActive")
PM_START = ("CPUStartTime", "TimeInMs", "CPUStartQPCTime", "TimeInSeconds")
PM_RENDERED_TYPES = {"", "application", "unknown", "notset"}


def _f(row: dict, names) -> float | None:
    for n in names:
        v = row.get(n)
        if v not in (None, "", "NA"):
            try:
                x = float(v)
            except ValueError:
                continue
            if math.isfinite(x):
                return x
    return None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


class CsvTail:
    """Le so as linhas novas de um CSV que outro programa esta escrevendo."""

    def __init__(self, path: Path, header_line: int = 0):
        self.path = Path(path)
        self.header_line = header_line   # indice da linha do cabecalho (MangoHud: 2)
        self._offset = 0
        self._pending = ""
        self._lines_seen = 0
        self.header: list[str] | None = None

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            f.seek(self._offset)
            chunk = f.read()
            self._offset = f.tell()
        lines = (self._pending + chunk).split("\n")
        self._pending = lines.pop()
        rows = []
        for line in lines:
            line = line.rstrip("\r")
            idx = self._lines_seen
            self._lines_seen += 1
            if not line.strip():
                continue
            if idx < self.header_line:
                continue
            if self.header is None:
                self.header = [h.strip() for h in next(csv.reader([line]))]
                continue
            values = next(csv.reader(io.StringIO(line)))
            rows.append(dict(zip(self.header, values)))
        return rows


# ----------------------------------------------------------------------------- fontes

class PresentMonSource:
    """PresentMon com a saida CSV no STDOUT (--output_stdout), lida por uma thread.

    Nao da para ler o --output_file enquanto o PresentMon escreve: ele abre o arquivo com
    _wfopen_s, que bloqueia o arquivo para outros programas (no Windows, "acesso negado")."""

    name = "presentmon"

    def __init__(self, exe: str, process_name: str, csv_path: Path, extra_args: list[str] | None, log,
                 diag_prefix: Path | None = None, fg_factor: int = 1):
        self.exe = exe
        self.process_name = process_name
        # Frame Generation sem marcacao dos frames gerados (FrameType sempre "Application", como
        # no Black Myth: Wukong): com FG 2x o jogo apresenta exatamente 1 frame gerado para cada
        # renderizado, entao renderizados = apresentados / fg_factor.
        self.fg_factor = max(1, int(fg_factor or 1))
        self.csv_path = Path(csv_path)          # nao usado para ler; so o nome base
        self.extra_args = list(extra_args or [])
        self.log = log
        self.proc: subprocess.Popen | None = None
        # Diagnostico que fica na sessao: <teste>_presentmon.log (mensagens do PresentMon) e
        # <teste>_presentmon_amostra.csv (o CSV inteiro passaria de 1 GB em 48 h): as 300 primeiras
        # linhas (abertura/menu) e 3000 linhas a partir de 2 min (a cena ja rodando)
        self.diag_prefix = Path(diag_prefix) if diag_prefix else None
        self._log_file = None
        self._sample_file = None
        self._sample_lines = 0
        self._sample_t0 = time.monotonic()
        self._sample_mid = 0
        self._warned_exit = False
        self._rows_seen = 0
        self._header: list[str] | None = None
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    def start(self):
        args = [self.exe, "--process_name", self.process_name, "--output_stdout",
                "--no_console_stats", "--stop_existing_session", "--session_name", "BenchAging"]
        args += self.extra_args
        err = subprocess.DEVNULL
        if self.diag_prefix:
            self._log_file = open(self.diag_prefix.with_name(self.diag_prefix.name + "_presentmon.log"), "w",
                                  encoding="utf-8", errors="ignore")
            self._log_file.write(" ".join(f'"{a}"' if " " in a else a for a in args) + "\n\n")
            self._log_file.flush()
            err = self._log_file
            self._sample_file = open(self.diag_prefix.with_name(self.diag_prefix.name + "_presentmon_amostra.csv"),
                                     "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, bufsize=1,
                                         text=True, encoding="utf-8", errors="ignore")
        except OSError as e:
            self.log.warning("Nao consegui abrir o PresentMon (%s): os CSVs ficam sem FPS.", e)
            self.proc = None
            return
        self.log.info("PresentMon medindo os frames de %s", self.process_name)
        self._sample_t0 = time.monotonic()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True, name="PresentMonReader")
        self._reader.start()

    def _read_stdout(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip("\r\n").lstrip("\ufeff")
            if not line.strip():
                continue
            if self._sample_file:
                if self._sample_lines < 300:
                    self._sample_file.write(line + "\n")
                    self._sample_lines += 1
                    if self._sample_lines in (1, 300):
                        self._sample_file.flush()
                elif self._sample_mid < 3000 and time.monotonic() - self._sample_t0 >= 120:
                    self._sample_file.write(line + "\n")
                    self._sample_mid += 1
                    if self._sample_mid in (1, 3000):
                        self._sample_file.flush()
            try:
                values = next(csv.reader([line]))
            except Exception:
                continue
            if self._header is None:
                if "Application" in values or "ProcessID" in values:
                    self._header = [v.strip() for v in values]
                else:   # texto que nao e CSV (mensagem do PresentMon)
                    if self._log_file:
                        self._log_file.write(line + "\n")
                        self._log_file.flush()
                continue
            if values == self._header:     # cabecalho repetido
                continue
            with self._lock:
                self._buffer.append(dict(zip(self._header, values)))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._reader:
            self._reader.join(timeout=5)
        for f in (self._log_file, self._sample_file):
            if f:
                try:
                    f.close()
                except Exception:
                    pass

    def _check_alive(self):
        if self.proc is None or self._warned_exit or self.proc.poll() is None:
            return
        self._warned_exit = True
        tail = ""
        if self._log_file:
            self._log_file.flush()
            try:
                text = Path(self._log_file.name).read_text(encoding="utf-8", errors="ignore")
                tail = " | ".join(line.strip() for line in text.splitlines()[-6:] if line.strip())
            except OSError:
                pass
        self.log.warning("PresentMon fechou (codigo %s): sem FPS a partir daqui. %s%s", self.proc.returncode, tail,
                         " Rode o terminal como ADMINISTRADOR." if self.proc.returncode else "")

    def read_rows(self) -> list[dict]:
        with self._lock:
            rows, self._buffer = self._buffer, []
        return rows

    def aggregate(self, dt: float) -> dict:
        self._check_alive()
        new_rows = self.read_rows()
        if new_rows and not self._rows_seen:
            self.log.info("PresentMon: primeiros frames recebidos (colunas: %s)",
                          ", ".join(list(new_rows[0])[:12]) + ("..." if len(new_rows[0]) > 12 else ""))
        self._rows_seen += len(new_rows)
        return self.summarize(new_rows, dt)

    def summarize(self, new_rows: list[dict], dt: float) -> dict:
        rows = [r for r in new_rows
                if (r.get("Application") or self.process_name).lower() == self.process_name.lower()]
        if not rows or dt <= 0:
            return {}
        has_type = "FrameType" in rows[0]
        rendered = [r for r in rows if (r.get("FrameType") or "").strip().lower() in PM_RENDERED_TYPES]
        generated = len(rows) - len(rendered)
        displayed = sum(1 for r in rows if (_f(r, PM_DISPLAYED) or 0) > 0)

        # Tempo de frame dos frames RENDERIZADOS. Com Frame Generation, o intervalo entre
        # apresentacoes mistura frames gerados; o certo e a diferenca entre inicios de frames
        # renderizados.
        if not generated and self.fg_factor > 1:
            return self._summarize_fg_estimated(rows, dt)

        frametimes: list[float] = []
        if generated and has_type:
            starts = [_f(r, PM_START) for r in rendered]
            starts = [s for s in starts if s is not None]
            scale = 1000.0 if "TimeInSeconds" in rows[0] and "CPUStartTime" not in rows[0] else 1.0
            frametimes = [(b - a) * scale for a, b in zip(starts, starts[1:]) if b > a]
        if not frametimes:
            frametimes = [x for x in (_f(r, PM_INTERVAL) for r in rendered) if x is not None and x > 0]
        gpu = [x for x in (_f(r, PM_GPU) for r in rendered) if x is not None]

        out = {"avg_fps": round(len(rendered) / dt, 2), "frames_no_intervalo": len(rows)}
        p99 = percentile(frametimes, 99)
        if p99 is not None:
            out["p99_frametime_ms"] = round(p99, 3)
        if gpu:
            out["gpu_time_ms"] = round(sum(gpu) / len(gpu), 3)
        if generated and rendered:
            out["dlssg_fps"] = round(displayed / dt, 2)
            out["dlssg_frames_presented"] = round(displayed / len(rendered), 3)
        return out


    def _summarize_fg_estimated(self, rows: list[dict], dt: float) -> dict:
        """FG sem FrameType util: agrupa os frames apresentados de fg_factor em fg_factor.
        Cada grupo = 1 frame renderizado + os gerados a partir dele."""
        k = self.fg_factor
        intervals = [_f(r, PM_INTERVAL) for r in rows]
        gpus = [_f(r, PM_GPU) for r in rows]
        displayed = sum(1 for r in rows if (_f(r, PM_DISPLAYED) or 0) > 0)
        frametimes = [sum(x for x in intervals[i:i + k] if x is not None)
                      for i in range(0, len(intervals) - k + 1, k)]
        gpu_groups = [sum(x for x in gpus[i:i + k] if x is not None)
                      for i in range(0, len(gpus) - k + 1, k)]
        out = {"avg_fps": round(len(rows) / k / dt, 2), "frames_no_intervalo": len(rows),
               "dlssg_fps": round(displayed / dt, 2), "dlssg_frames_presented": float(k)}
        p99 = percentile([x for x in frametimes if x > 0], 99)
        if p99 is not None:
            out["p99_frametime_ms"] = round(p99, 3)
        if gpu_groups:
            # tempo de GPU por frame renderizado, incluindo a geracao do(s) frame(s) extra(s)
            out["gpu_time_ms"] = round(sum(gpu_groups) / len(gpu_groups), 3)
        return out


class MangoHudSource:
    name = "mangohud"

    def __init__(self, folder: Path, log):
        self.folder = Path(folder).expanduser()
        self.log = log
        self.tail: CsvTail | None = None
        self.started = time.time()

    def start(self):
        self.started = time.time()
        if not self.folder.exists():
            self.log.warning("Pasta de logs do MangoHud nao existe: %s (veja WUKONG.md, Linux).", self.folder)

    def stop(self):
        pass

    def _current_file(self) -> Path | None:
        if not self.folder.exists():
            return None
        files = [p for p in self.folder.glob("*.csv")
                 if not p.name.endswith("_summary.csv") and p.stat().st_mtime >= self.started - 5]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def aggregate(self, dt: float) -> dict:
        f = self._current_file()
        if f is None:
            return {}
        if self.tail is None or self.tail.path != f:  # jogo reaberto = arquivo novo
            self.tail = CsvTail(f, header_line=2)
        rows = self.tail.read()
        fps = [x for x in (_f(r, ("fps",)) for r in rows) if x is not None and x > 0]
        ft = [x for x in (_f(r, ("frametime",)) for r in rows) if x is not None and x > 0]
        if not fps:
            return {}
        out = {"avg_fps": round(sum(fps) / len(fps), 2), "frames_no_intervalo": len(rows)}
        p99 = percentile(ft, 99)
        if p99 is not None:
            out["p99_frametime_ms"] = round(p99, 3)
        return out


class NoSource:
    name = "nenhuma"

    def start(self):
        pass

    def stop(self):
        pass

    def aggregate(self, dt: float) -> dict:
        return {}


# ----------------------------------------------------------------------------- amostrador

class FrameSampler(threading.Thread):
    """Grava uma linha a cada `interval_s` em engine_samples.csv enquanto o jogo esta aberto."""

    def __init__(self, out_csv: Path, interval_s: float, source, is_running: Callable[[], bool],
                 log: logging.Logger | None = None):
        super().__init__(daemon=True, name="FrameSampler")
        self.out_csv = Path(out_csv)
        self.interval_s = float(interval_s)
        self.source = source
        self.is_running = is_running
        self.log = log or logging.getLogger("bench")
        self._stop_event = threading.Event()
        self.rows = 0
        self.last_fps: float | None = None

    def stop(self, timeout: float = 15.0):
        self._stop_event.set()
        self.join(timeout=timeout)
        self.source.stop()

    def run(self):
        self.source.start()
        self.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(self.out_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=ENGINE_HEADER, extrasaction="ignore")
            if f.tell() == 0:
                w.writeheader()
                f.flush()
            last = time.monotonic()
            self._t0_mono, self._t0_wall = last, datetime.now(timezone.utc)
            while not self._stop_event.wait(self.interval_s - ((time.monotonic() - last) % self.interval_s)):
                now = time.monotonic()
                dt, last = now - last, now
                try:
                    data = self.source.aggregate(dt)
                except Exception as e:  # a medicao de frames nunca derruba o teste
                    if not getattr(self, "_warned_error", False):
                        self._warned_error = True
                        self.log.warning("Leitura dos frames falhou: %s", e)
                    data = {}
                if not self.is_running():
                    continue
                self.last_fps = data.get("avg_fps")
                # Relogio monotonico: se o Windows acertar a hora no meio do teste, o tempo
                # das amostras nao volta para tras
                ts = self._t0_wall + timedelta(seconds=now - self._t0_mono)
                row = {"timestamp_utc": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")}
                row.update(data)
                w.writerow(row)
                f.flush()
                self.rows += 1


def make_source(cfg: dict, process_name: str, raw_dir: Path, log, diag_prefix: Path | None = None,
                fg_factor: int = 1):
    kind = (cfg.get("fonte") or "nenhuma").lower()
    if kind == "presentmon":
        exe = cfg.get("presentmon_exe") or "PresentMon.exe"
        return PresentMonSource(exe, process_name, Path(raw_dir) / "presentmon.csv", cfg.get("presentmon_args"), log,
                                diag_prefix, fg_factor=fg_factor)
    if kind == "mangohud":
        return MangoHudSource(Path(cfg.get("mangohud_dir") or "~/wukong_mangohud"), log)
    return NoSource()
