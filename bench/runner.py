"""Execucao dos testes.

Para cada teste: abre o jogo com os cvars do teste, confere se o DLSS ficou como pedido,
grava as metricas (bench/monitor.py) e reabre o jogo se ele fechar antes da hora.

Pasta de cada sessao (BenchmarkRuns/<data>_<plataforma>/):
    sessao.json       maquina, versoes, configuracao e o resultado de cada teste
    log.txt           o que aconteceu, em ordem (o mesmo texto que aparece no terminal)
    <teste>.csv       uma linha a cada 5 s com todas as metricas (um arquivo por teste)
    logs/             logs da Unreal, SO quando algo deu errado (travamento, DLSS, OTA)

Os arquivos que o jogo grava durante o teste ficam em .tmp/ e sao apagados no fim.
"""

from __future__ import annotations

import ctypes
import json
import logging
import platform
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from .config import Config, TestDef, is_windows, platform_name
from .monitor import ExternalMonitor, GpuReader, TestMonitor

# Desliga as atualizacoes automaticas (OTA) da NVIDIA dentro do jogo. Sem isso, o driver pode
# carregar versoes do Frame Generation/DLSS baixadas pela internet em vez das do plugin, e cada
# maquina (ou cada dia) usaria uma versao diferente.
NO_OTA_ARGS = ["-slnoota", "-ini:Engine:[/Script/DLSS.DLSSSettings]:bAllowOTAUpdate=False"]
OTA_LOG_MARKERS = ["DLSS model OTA update enabled", "Found OTA plugin", "bAllowOTAUpdate           to 1"]

# Versoes lidas do log da Unreal (vao para o sessao.json)
VERSION_PATTERNS = {
    "unreal": r"Engine Version: (\S+)",
    "plugin_dlss": r"Loaded DLSS-SR plugin version (\S+)",
    "plugin_streamline": r"Loaded Streamline plugin version (\S+)",
}
MACHINE_PATTERN = r"LogInit: OS: (.+?), CPU: (.+?), GPU: (.+)$"

FINISH_TOLERANCE_S = 60      # saida do jogo ate 60 s antes do fim conta como "terminou normalmente"
FORCE_KILL_GRACE_S = 180     # se o jogo nao fechar sozinho ate 3 min depois do fim, e encerrado
TMP_DIR = ".tmp"


# ----------------------------------------------------------------------------- utilidades

@contextmanager
def keep_system_awake(log):
    """Impede o Windows de suspender ou desligar a tela durante o teste."""
    if not is_windows():
        yield
        return
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        log.info("Suspensao automatica do Windows bloqueada durante os testes.")
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def kill_tree(proc: subprocess.Popen, timeout: float = 20.0) -> None:
    if proc.poll() is not None:
        return
    if psutil is None:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    try:
        parent = psutil.Process(proc.pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def values_match(requested: str, actual: str) -> bool:
    r, a = str(requested).strip().lower(), str(actual).strip().lower()
    if r == a:
        return True
    booleans = {"true": "1", "false": "0", "on": "1", "off": "0"}
    r, a = booleans.get(r, r), booleans.get(a, a)
    try:
        fr, fa = float(r), float(a)
        return abs(fr - fa) <= 1e-3 * max(1.0, abs(fr))
    except ValueError:
        return r == a


# Recurso do DLSS -> (cvar que o liga, chave no bloco "support" do run_config.json, nome legivel)
FEATURE_SUPPORT = [
    ("r.NGX.DLSS.Enable", "dlss_sr", "DLSS Super Resolution/DLAA"),
    ("r.NGX.DLSS.DenoiserMode", "dlss_rr", "DLSS Ray Reconstruction"),
    ("r.Streamline.DLSSG.Enable", "dlssg", "DLSS Frame Generation"),
]


def _is_on(value) -> bool:
    try:
        return float(str(value).strip()) != 0
    except ValueError:
        return str(value).strip().lower() in ("true", "on")


def read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def find_ota_lines(log_text: str) -> list[str]:
    """Linhas do log da Unreal que mostram alguma atualizacao OTA da NVIDIA ativa."""
    return [ln.strip()[-160:] for ln in log_text.splitlines() if any(m in ln for m in OTA_LOG_MARKERS)]


def parse_versions(log_text: str) -> dict:
    out = {}
    for key, pattern in VERSION_PATTERNS.items():
        m = re.search(pattern, log_text)
        if m:
            out[key] = m.group(1)
    m = re.search(MACHINE_PATTERN, log_text, re.MULTILINE)
    if m:
        out["_cpu"] = m.group(2).strip()
    return out


def check_run_config(data: dict, requested: dict | None = None) -> list[str]:
    """Devolve a lista de problemas (vazia = cvars aplicados e recursos suportados)."""
    problems = []
    for item in data.get("cvars", []):
        name = item.get("name")
        if not item.get("exists", False):
            problems.append(f"{name}: nao existe no jogo (plugin DLSS/Streamline habilitado?)")
        elif item.get("read_only", False):
            problems.append(f"{name}: somente leitura em runtime (precisa ir no DefaultEngine.ini)")
        elif not values_match(item.get("requested", ""), item.get("actual", "")):
            problems.append(f"{name}: pedido={item.get('requested')} atual={item.get('actual')}")

    # O cvar pode ficar "1" mesmo numa GPU sem suporte; por isso o jogo tambem pergunta
    # ao plugin da NVIDIA se cada recurso pedido esta disponivel.
    requested = requested or {}
    needed = [(key, label) for cvar, key, label in FEATURE_SUPPORT if _is_on(requested.get(cvar, "0"))]
    support = data.get("support")
    if needed and not isinstance(support, dict):
        problems.append("run_config.json sem o bloco 'support': o jogo empacotado e de uma versao antiga do codigo")
    elif needed:
        for key, label in needed:
            status = support.get(key, "<ausente>")
            if status != "Supported":
                problems.append(f"{label} nao esta disponivel nesta maquina: {status}")
    return problems


# ----------------------------------------------------------------------------- sessao

class Session:
    """Pasta da sessao + sessao.json (regravado a cada mudanca, entao fica valido mesmo
    se o computador desligar no meio)."""

    def __init__(self, cfg: Config, tests: list[TestDef], duration_s: float, gpu: GpuReader):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        base = cfg.output_dir / f"{stamp}_{platform_name()}"
        self.dir = base
        n = 2
        while self.dir.exists():
            self.dir = base.with_name(f"{base.name}_{n}")
            n += 1
        self.dir.mkdir(parents=True)
        game = cfg.bench["game"]
        run = cfg.bench["run"]
        self.data = {
            "plataforma": platform_name(),
            "inicio": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fim": None,
            "maquina": {
                "sistema": platform.platform(),
                "cpu": platform.processor() or platform.machine(),
                "ram_gb": round(psutil.virtual_memory().total / 2**30, 1) if psutil else None,
                "gpu": gpu.name,
                "driver_nvidia": gpu.driver,
            },
            "versoes": {},
            "configuracao": {
                "horas_por_teste": round(duration_s / 3600, 4),
                "intervalo_amostra_s": run["sample_interval_s"],
                "pausa_entre_testes_min": run.get("cooldown_minutes", 10),
                "resolucao": game.get("resolution"),
                "modo_janela": game.get("window_mode"),
                "rhi": game.get("rhi"),
                "ray_tracing_hardware": cfg.bench["unreal"].get("enable_hardware_ray_tracing", True),
                "executavel": str(cfg.game_exe()),
                "argumentos_extras": NO_OTA_ARGS + list(game.get("extra_args", [])),
            },
            "testes": [],
        }
        self.save()

    def add_versions(self, log_text: str):
        if self.data["versoes"]:
            return
        found = parse_versions(log_text)
        cpu = found.pop("_cpu", None)
        if cpu:
            self.data["maquina"]["cpu"] = cpu
        self.data["versoes"] = found
        self.save()

    def save(self):
        path = self.dir / "sessao.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def setup_logging(session_dir: Path) -> logging.Logger:
    log = logging.getLogger("bench")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.FileHandler(session_dir / "log.txt", encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


# ----------------------------------------------------------------------------- execucao

class TestRunner:
    def __init__(self, cfg: Config, session: Session, gpu: GpuReader, log: logging.Logger):
        self.cfg = cfg
        self.session = session
        self.gpu = gpu
        self.log = log
        self.exe = cfg.game_exe()

    def _build_command(self, test: TestDef, raw_dir: Path, duration_s: float, launch_n: int):
        game = self.cfg.bench["game"]
        run = self.cfg.bench["run"]
        tokens = [
            f"-BenchPhase={test.name}",
            f"-BenchDuration={int(duration_s)}",
            f"-BenchInterval={run['sample_interval_s']}",
            f'-BenchOutDir="{raw_dir.as_posix()}"',
            f"-BenchCVars={test.cvars_arg()}",
            f'-ABSLOG="{(raw_dir / f"unreal_{launch_n:02d}.log").as_posix()}"',
        ]
        res = game.get("resolution")
        if res:
            tokens += [f"-ResX={int(res[0])}", f"-ResY={int(res[1])}"]
        mode = (game.get("window_mode") or "").lower()
        if mode in ("fullscreen", "windowed"):
            tokens.append(f"-{mode}")
        rhi = (game.get("rhi") or "").lower()
        if rhi:
            tokens.append(f"-{rhi}")
        if game.get("camera_speed"):
            tokens.append(f"-BenchCameraSpeed={game['camera_speed']}")
        tokens += NO_OTA_ARGS
        tokens += list(game.get("extra_args", []))

        if is_windows():
            # A Unreal le os parametros no formato -Chave="valor com espaco"; por isso a
            # linha de comando e montada manualmente em vez de usar uma lista.
            return f'"{self.exe}" ' + " ".join(tokens)
        return [str(self.exe), *[t.replace('"', "") for t in tokens]]

    @staticmethod
    def _wait_run_config(proc, path: Path, launched_at: float, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_mtime >= launched_at - 1:
                time.sleep(0.5)  # garante que terminou de gravar
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            if proc.poll() is not None:
                return None
            time.sleep(1.0)
        return None

    def _check_launch(self, proc, test: TestDef, raw_dir: Path, launch_n: int, launched_at: float, entry: dict) -> bool:
        """Confere DLSS/cvars logo depois de abrir o jogo. Devolve False se o teste deve parar."""
        strict = bool(self.cfg.bench["run"].get("strict_cvar_check", True))
        data = self._wait_run_config(proc, raw_dir / "run_config.json", launched_at,
                                     float(self.cfg.bench["run"].get("startup_timeout_s", 600)))
        log_text = read_log(raw_dir / f"unreal_{launch_n:02d}.log")
        self.session.add_versions(log_text)
        if data is None:
            if proc.poll() is not None:
                msg = f"o jogo fechou antes de gravar o run_config.json (codigo {proc.returncode})"
            else:
                msg = "o jogo nao gravou o run_config.json dentro do tempo limite"
            self.log.error(msg[0].upper() + msg[1:] + ".")
            entry["problemas"].append(msg)
            if strict:
                entry["status"] = "abortado (jogo nao iniciou)"
                return False
            return True

        entry["resolucao_real"] = data.get("resolution")
        entry["rhi_real"] = data.get("rhi")
        entry["dlss"] = data.get("support") or {}
        problems = check_run_config(data, test.cvars)
        if problems:
            for p in problems:
                self.log.error("DLSS/cvar com problema: %s", p)
            entry["problemas"].extend(problems)
            if strict:
                entry["status"] = "abortado (DLSS nao ficou como pedido)"
                return False
        else:
            sup = entry["dlss"]
            self.log.info("Conferido: %d cvars com o valor pedido | %s %s | DLSS %s, FG %s",
                          len(data.get("cvars", [])), data.get("rhi"), data.get("resolution"),
                          sup.get("dlss_mode"), sup.get("dlssg_mode"))

        ota = find_ota_lines(log_text)
        if ota:
            entry["ota_ativa"] = True
            entry["problemas"].append("atualizacao OTA da NVIDIA ativa: " + ota[0])
            self.log.warning("Atualizacao OTA da NVIDIA ainda ativa (versoes podem variar entre maquinas):")
            for line in ota[:3]:
                self.log.warning("   %s", line)
        return True

    def run_test(self, test: TestDef, duration_s: float) -> dict:
        sdir = self.session.dir
        raw_dir = sdir / TMP_DIR / test.name
        raw_dir.mkdir(parents=True, exist_ok=True)
        run_cfg = self.cfg.bench["run"]
        mon_cfg = self.cfg.bench["monitor"]

        entry = {
            "id": test.id, "nome": test.name, "features": test.features, "cvars": test.cvars,
            "arquivo": f"{test.name}.csv", "status": "rodando",
            "inicio": datetime.now().astimezone().isoformat(timespec="seconds"), "fim": None,
            "horas": 0.0, "execucoes": 0, "reinicios": 0, "amostras": 0,
            "dlss": {}, "ota_ativa": False, "problemas": [], "logs": [],
        }
        self.session.data["testes"].append(entry)
        self.session.save()

        self.log.info("=" * 70)
        self.log.info("TESTE %s - %s | %.2f h | features: %s",
                      test.id, test.name, duration_s / 3600, ", ".join(test.features) or "nenhuma")
        self.log.info("cvars: %s", test.cvars_arg())

        monitor = TestMonitor(raw_dir / "engine_samples.csv", sdir / entry["arquivo"], self.exe.name,
                              self.gpu, datetime.now(timezone.utc))
        monitor.start()
        external = ExternalMonitor(mon_cfg.get("external_cmd"), sdir)
        external.start()

        start = time.monotonic()
        deadline = start + duration_s
        # Tolerancia para "terminou no horario": 60 s num teste de 48 h, poucos segundos num de validacao
        finish_tol = min(FINISH_TOLERANCE_S, max(10.0, 0.02 * duration_s))
        max_restarts = int(run_cfg.get("max_restarts", 20))
        proc = None
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining < finish_tol:
                    entry["status"] = "completo"
                    break

                entry["execucoes"] += 1
                n = entry["execucoes"]
                cmd = self._build_command(test, raw_dir, remaining, n)
                launched_at = time.time()
                self.log.info("Abrindo o jogo (execucao %d, faltam %.2f h)", n, remaining / 3600)
                proc = subprocess.Popen(cmd)
                monitor.new_launch(proc.pid, n)
                self.session.save()

                if not self._check_launch(proc, test, raw_dir, n, launched_at, entry):
                    break
                self.session.save()

                crashed = False
                while True:
                    code = proc.poll()
                    now = time.monotonic()
                    if code is not None:
                        if now >= deadline - finish_tol:
                            entry["status"] = "completo"
                        else:
                            crashed = True
                            msg = f"o jogo fechou sozinho apos {(now - start) / 3600:.2f} h (codigo {code})"
                            self.log.warning(msg[0].upper() + msg[1:] + ".")
                            entry["problemas"].append(msg)
                        break
                    if now > deadline + FORCE_KILL_GRACE_S:
                        self.log.warning("O jogo nao fechou sozinho no fim do teste; encerrando.")
                        kill_tree(proc)
                        entry["status"] = "completo"
                        break
                    time.sleep(2.0)

                if not crashed:
                    break
                entry["reinicios"] += 1
                if entry["reinicios"] > max_restarts:
                    entry["status"] = "falhou (reinicios demais)"
                    break
                self.session.save()
                time.sleep(10)
        except KeyboardInterrupt:
            self.log.warning("Interrompido pelo usuario (Ctrl+C).")
            entry["status"] = "interrompido"
            raise
        finally:
            if proc is not None:
                kill_tree(proc)
            time.sleep(0.5)
            monitor.stop()
            external.stop()
            entry["fim"] = datetime.now().astimezone().isoformat(timespec="seconds")
            entry["horas"] = round((time.monotonic() - start) / 3600, 3)
            entry["amostras"] = monitor.samples
            self._finish_raw(raw_dir, entry)
            self.session.save()
            self.log.info("Teste %s terminou: %s (%.2f h, %d amostras, %d reinicio(s))",
                          test.name, entry["status"], entry["horas"], entry["amostras"], entry["reinicios"])
        return entry

    def _finish_raw(self, raw_dir: Path, entry: dict):
        """Guarda os logs da Unreal so se algo deu errado; apaga o resto dos arquivos temporarios."""
        if entry["problemas"] or entry["status"] != "completo":
            logs_dir = self.session.dir / "logs"
            for f in sorted(raw_dir.glob("unreal_*.log")):
                logs_dir.mkdir(exist_ok=True)
                target = logs_dir / f"{entry['nome']}_{f.name}"
                shutil.move(str(f), target)
                entry["logs"].append(f"logs/{target.name}")
            if entry["logs"]:
                self.log.info("Logs da Unreal guardados em %s (houve problema no teste).", logs_dir)
        shutil.rmtree(raw_dir, ignore_errors=True)
        try:
            raw_dir.parent.rmdir()  # .tmp/ some quando fica vazia
        except OSError:
            pass


def run_session(cfg: Config, tests: list[TestDef], duration_s: float) -> tuple[Session, list[dict]]:
    gpu = GpuReader(cfg.bench["monitor"].get("gpu_index", 0))
    session = Session(cfg, tests, duration_s, gpu)
    log = setup_logging(session.dir)
    log.info("Sessao: %s", session.dir)
    cooldown_s = float(cfg.bench["run"].get("cooldown_minutes", 10)) * 60
    runner = TestRunner(cfg, session, gpu, log)
    results = []
    try:
        with keep_system_awake(log):
            for i, test in enumerate(tests):
                results.append(runner.run_test(test, duration_s))
                if i < len(tests) - 1 and cooldown_s > 0:
                    log.info("Pausa de %.0f min para a GPU esfriar antes do proximo teste...", cooldown_s / 60)
                    time.sleep(cooldown_s)
    except KeyboardInterrupt:
        log.warning("Sessao interrompida. Os dados ja gravados ficam em %s", session.dir)
    finally:
        session.data["fim"] = datetime.now().astimezone().isoformat(timespec="seconds")
        session.save()
    log.info("-" * 70)
    for r in session.data["testes"]:
        log.info("  %-18s %-12s %6.2f h  %6d amostras", r["nome"], r["status"], r["horas"], r["amostras"])
    log.info("Resultados em %s", session.dir)
    return session, results