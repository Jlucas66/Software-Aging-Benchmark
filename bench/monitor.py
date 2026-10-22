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
import time
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
    # CPU da maquina inteira e outros processos
    "cpu_total_pct", "cpu_nucleo_max_pct", "outros_cpu_pct",
    # memoria e GPU
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
    proc_cpu_pct     uso de CPU do jogo, em % da CPU inteira (100 = todos os nucleos),
                     media entre duas amostras
    """

    def __init__(self, exe_name: str):
        self.exe_name = exe_name.lower()
        self.root_pid: int | None = None
        self.attached_at = 0.0
        self.proc = None
        self.ncpu = (psutil.cpu_count() or 1) if psutil else 1

    def attach(self, pid: int):
        self.root_pid = pid
        self.attached_at = time.time()
        self.proc = None

    def _find(self):
        """O processo do jogo: o proprio processo aberto pelo orquestrador (Windows) ou, quando
        ele e so um lancador (Linux: umu-run -> Proton -> Wine), o processo com o nome do .exe.
        Nunca mede o lancador no lugar do jogo: sem o jogo, as colunas do processo ficam vazias."""
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
        except psutil.Error:
            pass
        # O Wine pode criar o processo fora da arvore do lancador: procura pelo nome,
        # so entre os processos abertos depois desta execucao.
        for p in psutil.process_iter(["name", "create_time"]):
            try:
                if (p.info["name"] or "").lower() == self.exe_name and p.info["create_time"] >= self.attached_at - 5:
                    return p
            except psutil.Error:
                continue
        return None

    def read(self) -> dict:
        if self.proc is None or not self.proc.is_running():
            self.proc = self._find()
            if self.proc is None:
                return {}
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
                ct = p.cpu_times()
                d["_cpu_s"] = ct.user + ct.system   # tempo de CPU acumulado (vira % no monitor)
                d["_pid"] = p.pid
                d["_t"] = time.monotonic()
        except psutil.Error:
            self.proc = None
        return d


# ----------------------------------------------------------------------------- outros processos

class ProcessLog:
    """Registra, a cada `interval_s`, os OUTROS processos do computador que estavam usando
    CPU ou memoria de forma relevante (antivirus, Windows Update, navegador, driver...).
    Eles competem com o jogo pela maquina e podem parecer software aging.

    <teste>_processos.csv: timestamp_utc, horas, pid, processo, cpu_pct, mem_mb
      cpu_pct = media do ultimo intervalo, em % da CPU inteira
    Entram os processos com cpu_pct >= min_cpu_pct ou mem_mb >= min_mem_mb.
    """

    FIELDS = ["timestamp_utc", "horas", "pid", "processo", "cpu_pct", "mem_mb"]

    def __init__(self, out_csv: Path, t0: datetime, exe_name: str, interval_s: float = 60,
                 min_cpu_pct: float = 1.0, min_mem_mb: float = 300):
        self.out_csv = Path(out_csv)
        self.t0 = t0
        self.exe_name = exe_name.lower()
        self.interval_s = float(interval_s)
        self.min_cpu = float(min_cpu_pct)
        self.min_mem = float(min_mem_mb)
        self.ncpu = (psutil.cpu_count() or 1) if psutil else 1
        self._procs: dict = {}
        self._next = 0.0
        self.snapshots = 0

    def maybe_snapshot(self):
        if psutil is None or time.monotonic() < self._next:
            return
        self._next = time.monotonic() + self.interval_s
        now = datetime.now(timezone.utc)
        horas = round((now - self.t0).total_seconds() / 3600.0, 5)
        rows, seen = [], set()
        for p in psutil.process_iter(["name"]):
            pid = p.pid
            name = p.info.get("name") or ""
            if pid == 0 or name.lower() == self.exe_name:
                continue  # "Ociosidade do Sistema" e o proprio jogo (medido no CSV principal)
            seen.add(pid)
            known = self._procs.get(pid)
            try:
                reused = known is not None and known.create_time() != p.create_time()
            except psutil.Error:
                continue
            if known is None or reused:   # processo novo (ou pid reaproveitado)
                self._procs[pid] = p
                try:
                    p.cpu_percent(None)  # primeira vez: so referencia, a media vem no proximo
                except psutil.Error:
                    pass
                cpu = None
            else:
                p = known
                try:
                    cpu = p.cpu_percent(None) / self.ncpu
                except psutil.Error:
                    cpu = None
            try:
                mem = p.memory_info().rss / 2**20
            except psutil.Error:
                mem = None
            if (cpu is not None and cpu >= self.min_cpu) or (mem is not None and mem >= self.min_mem):
                rows.append({"timestamp_utc": now.isoformat(timespec="seconds"), "horas": horas, "pid": pid,
                             "processo": name, "cpu_pct": round(cpu, 1) if cpu is not None else "",
                             "mem_mb": round(mem, 1) if mem is not None else ""})
        for pid in list(self._procs):
            if pid not in seen:
                del self._procs[pid]
        new_file = not self.out_csv.exists()
        with open(self.out_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            if new_file:
                w.writeheader()
            w.writerows(sorted(rows, key=lambda r: -(r["cpu_pct"] or 0)))
        self.snapshots += 1


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

    def __init__(self, engine_csv: Path, out_csv: Path, exe_name: str, gpu: GpuReader, test_start_utc: datetime,
                 process_log: ProcessLog | None = None):
        super().__init__(daemon=True, name="TestMonitor")
        self.process_log = process_log
        self._prev_game_cpu: tuple | None = None   # (pid, tempo de CPU, instante) da amostra anterior
        if psutil is not None:
            psutil.cpu_percent(None, percpu=True)   # referencia para o uso da CPU
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
        self._prev_game_cpu = None

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
        proc = dict(self._last_proc)
        cpu_s, pid, t_mono = proc.pop("_cpu_s", None), proc.pop("_pid", None), proc.pop("_t", None)
        row.update(proc)
        # CPU do jogo = tempo de CPU gasto desde a amostra anterior / tempo passado
        game_cpu = None
        if cpu_s is not None:
            prev = self._prev_game_cpu
            if prev and prev[0] == pid and t_mono > prev[2]:
                game_cpu = max(0.0, 100.0 * (cpu_s - prev[1]) / (t_mono - prev[2]) / self.game.ncpu)
                row["proc_cpu_pct"] = round(game_cpu, 1)
            self._prev_game_cpu = (pid, cpu_s, t_mono)
        if psutil is not None:
            # Uso da CPU desde a amostra anterior: media de todos os nucleos (total) e o nucleo
            # mais ocupado. Total baixo com um nucleo em ~100% = gargalo numa thread so.
            cores = psutil.cpu_percent(None, percpu=True)
            total = sum(cores) / len(cores) if cores else 0.0
            row["cpu_total_pct"] = round(total, 1)
            row["cpu_nucleo_max_pct"] = round(max(cores), 1) if cores else None
            if game_cpu is not None:
                row["outros_cpu_pct"] = round(max(0.0, total - game_cpu), 1)
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
                if self.process_log is not None:
                    try:
                        self.process_log.maybe_snapshot()
                    except Exception:
                        pass  # o registro de processos nunca derruba a coleta principal
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