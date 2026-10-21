"""Coleta das metricas durante o teste.

O jogo grava uma linha a cada N segundos (FPS, tempos de frame) num arquivo temporario.
Este monitor acompanha esse arquivo e, a cada linha nova, mede na mesma hora:
  - o processo do jogo, pelo sistema operacional (memoria, threads, handles, CPU);
  - a GPU, pela NVML (VRAM, temperatura, clock, potencia, limitacoes);
  - a RAM usada no sistema.
e grava tudo numa linha so do CSV do teste. Assim existe UM arquivo por teste, ja
pronto para a analise, e ele fica salvo mesmo se o computador desligar no meio.

Nada e gravado enquanto o jogo esta fechado (abrindo, compilando shaders ou entre
um travamento e a reabertura): essas horas nao entram nas estatisticas.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover
    pynvml = None


# Colunas do CSV de cada teste, nesta ordem
FIELDS = [
    "timestamp_utc", "horas", "execucao",
    # medido pelo jogo (media dos ultimos N segundos)
    "fps", "fps_exibido", "frametime_p99_ms", "gpu_time_ms", "game_thread_ms", "render_thread_ms",
    # processo do jogo, medido pelo sistema operacional
    "proc_mem_mb", "proc_private_mb", "proc_threads", "proc_handles", "proc_cpu_pct",
    # sistema e GPU
    "ram_mb", "vram_mb", "gpu_util_pct", "gpu_temp_c", "gpu_clock_mhz", "gpu_power_w",
    "throttle_power", "throttle_thermal",
]

# Bits da NVML que dizem por que o clock da GPU esta abaixo do maximo
THROTTLE_POWER = 0x4 | 0x80           # limite de potencia (software) e power brake
THROTTLE_THERMAL = 0x8 | 0x20 | 0x40  # slowdown por hardware, limite termico (software e hardware)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- GPU

class GpuReader:
    """Le a GPU NVIDIA pela NVML (pacote nvidia-ml-py); se nao houver, usa o nvidia-smi."""

    def __init__(self, index: int = 0):
        self.index = index
        self.mode = "none"
        self.name = "desconhecida"
        self.driver = ""
        self.handle = None
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                name = pynvml.nvmlDeviceGetName(self.handle)
                self.name = name.decode() if isinstance(name, bytes) else name
                drv = pynvml.nvmlSystemGetDriverVersion()
                self.driver = drv.decode() if isinstance(drv, bytes) else drv
                self.mode = "nvml"
                return
            except Exception:
                self.handle = None
        if shutil.which("nvidia-smi"):
            self.mode = "nvidia-smi"
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", f"--id={index}", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                    text=True, timeout=10)
                parts = [p.strip() for p in out.strip().split(",")]
                self.name, self.driver = parts[0], parts[1] if len(parts) > 1 else ""
            except Exception:
                pass

    @staticmethod
    def _try(fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    def read(self) -> dict:
        if self.mode == "nvml":
            return self._read_nvml()
        if self.mode == "nvidia-smi":
            return self._read_smi()
        return {}

    def _read_nvml(self) -> dict:
        h, n = self.handle, pynvml
        d: dict = {}
        util = self._try(n.nvmlDeviceGetUtilizationRates, h)
        d["gpu_util_pct"] = util.gpu if util is not None else None
        mem = self._try(n.nvmlDeviceGetMemoryInfo, h)
        d["vram_mb"] = round(mem.used / 2**20, 1) if mem is not None else None
        d["gpu_temp_c"] = self._try(n.nvmlDeviceGetTemperature, h, n.NVML_TEMPERATURE_GPU)
        d["gpu_clock_mhz"] = self._try(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_SM)
        p = self._try(n.nvmlDeviceGetPowerUsage, h)
        d["gpu_power_w"] = round(p / 1000.0, 1) if p is not None else None
        reasons = getattr(n, "nvmlDeviceGetCurrentClocksEventReasons", None) or \
            getattr(n, "nvmlDeviceGetCurrentClocksThrottleReasons", None)
        mask = self._try(reasons, h) if reasons else None
        if mask is not None:
            d["throttle_power"] = int(bool(mask & THROTTLE_POWER))
            d["throttle_thermal"] = int(bool(mask & THROTTLE_THERMAL))
        return d

    def _read_smi(self) -> dict:
        keys = ["gpu_util_pct", "vram_mb", "gpu_temp_c", "gpu_clock_mhz", "gpu_power_w", "_mask"]
        q = "utilization.gpu,memory.used,temperature.gpu,clocks.sm,power.draw,clocks_throttle_reasons.active"
        try:
            out = subprocess.check_output(["nvidia-smi", f"--id={self.index}", f"--query-gpu={q}",
                                           "--format=csv,noheader,nounits"], text=True, timeout=10)
        except Exception:
            return {}
        vals = [v.strip() for v in out.strip().split(",")]
        d = {k: (None if v in ("[N/A]", "N/A", "") else v) for k, v in zip(keys, vals)}
        mask = d.pop("_mask", None)
        try:
            m = int(mask, 16)
            d["throttle_power"] = int(bool(m & THROTTLE_POWER))
            d["throttle_thermal"] = int(bool(m & THROTTLE_THERMAL))
        except (TypeError, ValueError):
            pass
        return d


# ----------------------------------------------------------------------------- processo do jogo

class GameProcess:
    """Mede o processo do jogo pelo sistema operacional (independe do que o jogo informa).

    proc_mem_mb      memoria fisica em uso (Working Set no Windows, RSS no Linux)
    proc_private_mb  memoria alocada so pelo jogo (Private Bytes no Windows; no Linux,
                     a parte residente que nao e compartilhada). Vazamento de memoria
                     aparece aqui primeiro: o Working Set pode cair quando o sistema
                     tira paginas da RAM, o Private Bytes nao.
    proc_threads     numero de threads
    proc_handles     handles abertos (Windows) / descritores de arquivo (Linux)
    proc_cpu_pct     uso de CPU do jogo, em % da CPU inteira (100 = todos os nucleos)
    """

    def __init__(self, exe_name: str):
        self.exe_name = exe_name.lower()
        self.root_pid: int | None = None
        self.proc = None
        self.ncpu = (psutil.cpu_count() or 1) if psutil else 1

    def attach(self, pid: int):
        self.root_pid = pid
        self.proc = None

    def _find(self):
        """O processo aberto pelo orquestrador ou, se ele for so um lancador (ex.: Proton),
        o processo filho com o nome do executavel."""
        if psutil is None or self.root_pid is None:
            return None
        try:
            root = psutil.Process(self.root_pid)
            if root.name().lower() == self.exe_name:
                return root
            for child in root.children(recursive=True):
                try:
                    if child.name().lower() == self.exe_name:
                        return child
                except psutil.Error:
                    continue
            return root
        except psutil.Error:
            return None

    def read(self) -> dict:
        if self.proc is None or not self.proc.is_running():
            self.proc = self._find()
            if self.proc is None:
                return {}
            try:
                self.proc.cpu_percent(None)  # a primeira leitura so serve de referencia
            except psutil.Error:
                pass
        p = self.proc
        d: dict = {}
        try:
            if p.status() == psutil.STATUS_ZOMBIE:  # jogo acabou de fechar: nao mede
                self.proc = None
                return d
            with p.oneshot():
                mi = p.memory_info()
                d["proc_mem_mb"] = round(mi.rss / 2**20, 1)
                private = getattr(mi, "private", None)
                if private is None and hasattr(mi, "shared"):
                    private = mi.rss - mi.shared
                d["proc_private_mb"] = round(private / 2**20, 1) if private is not None else None
                d["proc_threads"] = p.num_threads()
                if hasattr(p, "num_handles"):
                    d["proc_handles"] = p.num_handles()
                elif hasattr(p, "num_fds"):
                    d["proc_handles"] = p.num_fds()
                d["proc_cpu_pct"] = round(p.cpu_percent(None) / self.ncpu, 1)
        except psutil.Error:
            self.proc = None
        return d


# ----------------------------------------------------------------------------- monitor

# Coluna do arquivo do jogo -> coluna do CSV final
ENGINE_COLUMNS = {
    "avg_fps": "fps", "p99_frametime_ms": "frametime_p99_ms", "gpu_time_ms": "gpu_time_ms",
    "game_thread_ms": "game_thread_ms", "render_thread_ms": "render_thread_ms",
}


def engine_row_to_fields(row: dict) -> dict:
    out = {dst: row.get(src) for src, dst in ENGINE_COLUMNS.items()}
    # FPS exibido: so existe quando o Frame Generation esta de fato gerando frames
    # (mais de 1 frame exibido por frame renderizado). Sem FG fica vazio.
    presented = _num(row.get("dlssg_frames_presented"))
    if presented is not None and presented > 1:
        out["fps_exibido"] = row.get("dlssg_fps")
    return out


class TestMonitor(threading.Thread):
    """Le as linhas novas que o jogo grava e escreve o CSV do teste."""

    POLL_S = 0.5

    def __init__(self, engine_csv: Path, out_csv: Path, exe_name: str, gpu: GpuReader, test_start_utc: datetime):
        super().__init__(daemon=True, name="TestMonitor")
        self.engine_csv = Path(engine_csv)
        self.out_csv = Path(out_csv)
        self.gpu = gpu
        self.game = GameProcess(exe_name)
        self.t0 = test_start_utc
        self.launch = 0
        self.samples = 0
        self._stop_event = threading.Event()
        self._offset = 0
        self._header: list[str] | None = None
        self._pending = ""
        self._last_proc: dict = {}

    def new_launch(self, pid: int, launch_n: int):
        """Chamado pelo orquestrador cada vez que o jogo e (re)aberto."""
        self.launch = launch_n
        self.game.attach(pid)
        self._last_proc = {}

    def stop(self, timeout: float = 15.0):
        self._stop_event.set()
        self.join(timeout=timeout)

    def _new_engine_rows(self) -> list[dict]:
        if not self.engine_csv.exists():
            return []
        with open(self.engine_csv, "r", encoding="utf-8", errors="ignore", newline="") as f:
            f.seek(self._offset)
            chunk = f.read()
            self._offset = f.tell()
        text = self._pending + chunk
        lines = text.split("\n")
        self._pending = lines.pop()  # ultima linha pode estar pela metade
        rows = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("timestamp_utc"):
                self._header = line.split(",")
                continue
            if self._header is None:
                continue
            rows.append(next(csv.DictReader(io.StringIO(line), fieldnames=self._header)))
        return rows

    def _write(self, writer, engine_row: dict):
        row = {"timestamp_utc": engine_row.get("timestamp_utc") or utc_now_iso(), "execucao": self.launch}
        ts = engine_row.get("timestamp_utc")
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else datetime.now(timezone.utc)
        except ValueError:
            t = datetime.now(timezone.utc)
        row["horas"] = round((t - self.t0).total_seconds() / 3600.0, 5)
        row.update(engine_row_to_fields(engine_row))
        # Leitura do processo feita na volta anterior (ate 0,5 s antes): a ultima linha que o
        # jogo grava sai logo antes dele fechar, e medir depois pegaria o jogo se desmontando.
        row.update(self._last_proc)
        try:
            row.update(self.gpu.read())
        except Exception:
            pass
        if psutil is not None:
            row["ram_mb"] = round(psutil.virtual_memory().used / 2**20, 1)
        writer.writerow(row)

    def run(self):
        new_file = not self.out_csv.exists() or self.out_csv.stat().st_size == 0
        with open(self.out_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
                f.flush()
            while True:
                stopping = self._stop_event.is_set()
                try:
                    rows = self._new_engine_rows()
                except OSError:
                    rows = []
                for r in rows:
                    self._write(writer, r)
                    self.samples += 1
                if rows:
                    f.flush()
                if stopping:
                    break
                self._last_proc = self.game.read()
                self._stop_event.wait(self.POLL_S)


class ExternalMonitor:
    """Roda o seu proprio script de monitoramento em paralelo durante o teste (opcional)."""

    def __init__(self, cmd: list[str] | None, out_dir: Path):
        self.cmd = [c.replace("{out_dir}", str(out_dir)) for c in cmd] if cmd else None
        self.proc: subprocess.Popen | None = None

    def start(self):
        if self.cmd:
            self.proc = subprocess.Popen(self.cmd)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()