"""Monitor de sistema: grava uma linha a cada N segundos com metricas da GPU, CPU e RAM.

GPU: usa NVML (biblioteca oficial da NVIDIA, pacote nvidia-ml-py). Se nao estiver
disponivel, cai para o nvidia-smi. CPU e RAM: psutil.
"""

from __future__ import annotations

import csv
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


FIELDS = [
    "timestamp_utc", "elapsed_s",
    "gpu_util_pct", "gpu_mem_util_pct", "vram_used_mb", "vram_total_mb",
    "gpu_temp_c", "power_w", "power_limit_w", "energy_j",
    "clock_graphics_mhz", "clock_sm_mhz", "clock_mem_mhz",
    "fan_pct", "pstate", "throttle_reasons",
    "pcie_tx_mbs", "pcie_rx_mbs",
    "cpu_util_pct", "ram_used_mb", "ram_total_mb",
]

# Bits de "clock event reasons" (por que o clock esta abaixo do maximo)
THROTTLE_BITS = {
    0x1: "idle",
    0x2: "app_clocks",
    0x4: "sw_power_cap",
    0x8: "hw_slowdown",
    0x10: "sync_boost",
    0x20: "sw_thermal",
    0x40: "hw_thermal",
    0x80: "hw_power_brake",
    0x100: "display_clocks",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def decode_throttle(mask: int | None) -> str:
    if mask is None:
        return ""
    names = [name for bit, name in THROTTLE_BITS.items() if mask & bit]
    return "|".join(names) if names else "none"


class GpuReader:
    """Le metricas de uma GPU NVIDIA. Campos indisponiveis ficam vazios."""

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

    def _try(self, fn, *args, default=None):
        try:
            return fn(*args)
        except Exception:
            return default

    def read(self) -> dict:
        if self.mode == "nvml":
            return self._read_nvml()
        if self.mode == "nvidia-smi":
            return self._read_smi()
        return {}

    def _read_nvml(self) -> dict:
        h = self.handle
        n = pynvml
        d: dict = {}
        util = self._try(n.nvmlDeviceGetUtilizationRates, h)
        if util is not None:
            d["gpu_util_pct"] = util.gpu
            d["gpu_mem_util_pct"] = util.memory
        mem = self._try(n.nvmlDeviceGetMemoryInfo, h)
        if mem is not None:
            d["vram_used_mb"] = round(mem.used / 2**20, 1)
            d["vram_total_mb"] = round(mem.total / 2**20, 1)
        d["gpu_temp_c"] = self._try(n.nvmlDeviceGetTemperature, h, n.NVML_TEMPERATURE_GPU)
        p = self._try(n.nvmlDeviceGetPowerUsage, h)
        d["power_w"] = round(p / 1000.0, 2) if p is not None else None
        pl = self._try(n.nvmlDeviceGetEnforcedPowerLimit, h)
        d["power_limit_w"] = round(pl / 1000.0, 1) if pl is not None else None
        e = self._try(n.nvmlDeviceGetTotalEnergyConsumption, h)  # mJ desde o boot do driver
        d["energy_j"] = round(e / 1000.0, 1) if e is not None else None
        d["clock_graphics_mhz"] = self._try(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_GRAPHICS)
        d["clock_sm_mhz"] = self._try(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_SM)
        d["clock_mem_mhz"] = self._try(n.nvmlDeviceGetClockInfo, h, n.NVML_CLOCK_MEM)
        d["fan_pct"] = self._try(n.nvmlDeviceGetFanSpeed, h)
        ps = self._try(n.nvmlDeviceGetPerformanceState, h)
        d["pstate"] = f"P{ps}" if ps is not None else None
        reasons_fn = getattr(n, "nvmlDeviceGetCurrentClocksEventReasons", None) or \
            getattr(n, "nvmlDeviceGetCurrentClocksThrottleReasons", None)
        mask = self._try(reasons_fn, h) if reasons_fn else None
        d["throttle_reasons"] = decode_throttle(mask)
        tx = self._try(n.nvmlDeviceGetPcieThroughput, h, n.NVML_PCIE_UTIL_TX_BYTES)  # KB/s
        rx = self._try(n.nvmlDeviceGetPcieThroughput, h, n.NVML_PCIE_UTIL_RX_BYTES)
        d["pcie_tx_mbs"] = round(tx / 1024.0, 2) if tx is not None else None
        d["pcie_rx_mbs"] = round(rx / 1024.0, 2) if rx is not None else None
        return d

    def _read_smi(self) -> dict:
        q = ["utilization.gpu", "utilization.memory", "memory.used", "memory.total",
             "temperature.gpu", "power.draw", "power.limit", "clocks.gr", "clocks.sm",
             "clocks.mem", "fan.speed", "pstate"]
        keys = ["gpu_util_pct", "gpu_mem_util_pct", "vram_used_mb", "vram_total_mb",
                "gpu_temp_c", "power_w", "power_limit_w", "clock_graphics_mhz", "clock_sm_mhz",
                "clock_mem_mhz", "fan_pct", "pstate"]
        try:
            out = subprocess.check_output(
                ["nvidia-smi", f"--id={self.index}", f"--query-gpu={','.join(q)}",
                 "--format=csv,noheader,nounits"], text=True, timeout=10)
        except Exception:
            return {}
        vals = [v.strip() for v in out.strip().split(",")]
        return {k: (None if v in ("[N/A]", "N/A", "") else v) for k, v in zip(keys, vals)}


class SystemMonitor(threading.Thread):
    """Thread que grava system_samples.csv a cada `interval` segundos."""

    def __init__(self, out_csv: Path, interval: float = 5.0, gpu_index: int = 0):
        super().__init__(daemon=True, name="SystemMonitor")
        self.out_csv = Path(out_csv)
        self.interval = float(interval)
        self.gpu = GpuReader(gpu_index)
        self._stop_event = threading.Event()
        self.samples = 0
        if psutil is not None:
            psutil.cpu_percent(interval=None)  # primeira leitura serve so de referencia

    def stop(self, timeout: float = 15.0):
        self._stop_event.set()
        self.join(timeout=timeout)

    def run(self):
        new_file = not self.out_csv.exists()
        start = time.monotonic()
        next_tick = start
        with open(self.out_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            while not self._stop_event.is_set():
                row = {"timestamp_utc": utc_now_iso(), "elapsed_s": round(time.monotonic() - start, 1)}
                try:
                    row.update(self.gpu.read())
                except Exception as e:  # nunca derrubar o monitor por uma leitura
                    row["throttle_reasons"] = f"erro: {e}"
                if psutil is not None:
                    row["cpu_util_pct"] = psutil.cpu_percent(interval=None)
                    vm = psutil.virtual_memory()
                    row["ram_used_mb"] = round(vm.used / 2**20, 1)
                    row["ram_total_mb"] = round(vm.total / 2**20, 1)
                writer.writerow(row)
                f.flush()
                self.samples += 1
                # agenda pelo relogio, sem acumular atraso ao longo de 48h
                next_tick += self.interval
                self._stop_event.wait(max(0.0, next_tick - time.monotonic()))


class ExternalMonitor:
    """Roda o seu proprio script de monitoramento em paralelo durante o teste."""

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
