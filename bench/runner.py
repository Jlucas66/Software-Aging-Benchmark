"""Execucao dos testes: abre o jogo com os parametros de cada teste, confere se os
cvars de DLSS realmente foram aplicados, monitora o sistema e reabre o jogo se ele
fechar sozinho antes do tempo.
"""

from __future__ import annotations

import csv
import ctypes
import json
import logging
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

from .config import Config, TestDef, is_windows
from .monitor import ExternalMonitor, SystemMonitor, utc_now_iso
from .presentmon import PresentMonSampler

FINISH_TOLERANCE_S = 60      # saida do jogo ate 60s antes do fim conta como "terminou normalmente"
FORCE_KILL_GRACE_S = 180     # se o jogo nao fechar sozinho ate 3 min depois do fim, e encerrado


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
    procs = []
    if psutil is not None:
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
    else:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()


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


def check_run_config(data: dict) -> list[str]:
    """Devolve a lista de problemas (vazia = todos os cvars ficaram como pedido)."""
    problems = []
    for item in data.get("cvars", []):
        name = item.get("name")
        if not item.get("exists", False):
            problems.append(f"{name}: nao existe no jogo (plugin DLSS/Streamline habilitado?)")
        elif item.get("read_only", False):
            problems.append(f"{name}: somente leitura em runtime (precisa ir no DefaultEngine.ini)")
        elif not values_match(item.get("requested", ""), item.get("actual", "")):
            problems.append(f"{name}: pedido={item.get('requested')} atual={item.get('actual')}")
    return problems


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        new = not path.exists()
        self._f = open(path, "a", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        if new:
            self._w.writerow(["timestamp_utc", "event", "detail"])

    def __call__(self, event: str, detail: str = ""):
        self._w.writerow([utc_now_iso(), event, detail])
        self._f.flush()

    def close(self):
        self._f.close()


# ----------------------------------------------------------------------------- execucao

class TestRunner:
    def __init__(self, cfg: Config, session_dir: Path, log: logging.Logger):
        self.cfg = cfg
        self.session_dir = session_dir
        self.log = log
        self.exe = cfg.game_exe()

    def _build_command(self, test: TestDef, out_dir: Path, duration_s: float, launch_n: int):
        game = self.cfg.bench["game"]
        run = self.cfg.bench["run"]
        tokens = [
            f"-BenchPhase={test.name}",
            f"-BenchDuration={int(duration_s)}",
            f"-BenchInterval={run['sample_interval_s']}",
            f'-BenchOutDir="{out_dir.as_posix()}"',
            f"-BenchCVars={test.cvars_arg()}",
            f'-ABSLOG="{(out_dir / f"unreal_{launch_n:02d}.log").as_posix()}"',
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
        tokens += list(game.get("extra_args", []))

        if is_windows():
            # A Unreal le os parametros no formato -Chave="valor com espaco"; por isso a
            # linha de comando e montada manualmente em vez de usar uma lista.
            return f'"{self.exe}" ' + " ".join(tokens)
        return [str(self.exe), *[t.replace('"', "") for t in tokens]]

    def _wait_run_config(self, proc, path: Path, launched_at: float, timeout: float):
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

    def run_test(self, test: TestDef, duration_s: float) -> dict:
        out_dir = self.session_dir / test.name
        out_dir.mkdir(parents=True, exist_ok=True)
        run_cfg = self.cfg.bench["run"]
        mon_cfg = self.cfg.bench["monitor"]
        pm_cfg = self.cfg.bench["presentmon"]
        events = EventLog(out_dir / "events.csv")
        strict = bool(run_cfg.get("strict_cvar_check", True))

        summary = {
            "test_id": test.id, "test_name": test.name, "features": test.features,
            "cvars": test.cvars, "duration_requested_s": duration_s,
            "started_utc": utc_now_iso(), "restarts": 0, "status": "running",
            "cvar_problems": [], "exe": str(self.exe),
        }

        self.log.info("=" * 70)
        self.log.info("TESTE %s - %s | duracao %.2f h | features: %s",
                      test.id, test.name, duration_s / 3600, ", ".join(test.features) or "nenhuma")
        self.log.info("cvars: %s", test.cvars_arg())

        # Monitores
        sysmon = None
        if mon_cfg.get("builtin", True):
            sysmon = SystemMonitor(out_dir / "system_samples.csv", run_cfg["sample_interval_s"], mon_cfg.get("gpu_index", 0))
            summary["gpu_name"], summary["gpu_driver"], summary["gpu_reader"] = sysmon.gpu.name, sysmon.gpu.driver, sysmon.gpu.mode
            sysmon.start()
        external = ExternalMonitor(mon_cfg.get("external_cmd"), out_dir)
        external.start()
        pm = None
        if pm_cfg.get("enabled"):
            pm = PresentMonSampler(pm_cfg, self.exe.name, out_dir / "presentmon", self.log)
            pm.start()

        start = time.monotonic()
        deadline = start + duration_s
        # Tolerancia para considerar que o jogo "terminou no horario" (60 s num teste de 48 h,
        # alguns segundos num teste curto de validacao)
        finish_tol = min(FINISH_TOLERANCE_S, max(10.0, 0.02 * duration_s))
        proc = None
        launch_n = 0
        max_restarts = int(run_cfg.get("max_restarts", 20))
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining < finish_tol:
                    summary["status"] = "completed"
                    break

                launch_n += 1
                cmd = self._build_command(test, out_dir, remaining, launch_n)
                launched_at = time.time()
                self.log.info("Abrindo o jogo (execucao %d, faltam %.2f h)", launch_n, remaining / 3600)
                self.log.debug("Comando: %s", cmd)
                events("launch", f"n={launch_n} remaining_s={int(remaining)}")
                proc = subprocess.Popen(cmd)

                data = self._wait_run_config(proc, out_dir / "run_config.json", launched_at,
                                             float(run_cfg.get("startup_timeout_s", 600)))
                if data is None:
                    if proc.poll() is not None:
                        self.log.error("O jogo fechou antes de gravar o run_config.json (codigo %s).", proc.returncode)
                    else:
                        self.log.error("O jogo nao gravou o run_config.json dentro do tempo limite.")
                    events("no_run_config", f"exit={proc.poll()}")
                    if strict:
                        summary["status"] = "aborted_no_run_config"
                        break
                else:
                    problems = check_run_config(data)
                    summary["cvar_problems"] = problems
                    summary["engine_info"] = {k: data.get(k) for k in ("gpu", "rhi", "resolution", "engine_version", "audit")}
                    if problems:
                        for p in problems:
                            self.log.error("cvar com problema: %s", p)
                        events("cvar_check_failed", " | ".join(problems))
                        if strict:
                            summary["status"] = "aborted_cvar_check"
                            break
                    else:
                        self.log.info("Conferido: todos os %d cvars ficaram com o valor pedido (RHI %s, %s).",
                                      len(data.get("cvars", [])), data.get("rhi"), data.get("resolution"))
                        events("cvar_check_ok", f"rhi={data.get('rhi')} res={data.get('resolution')}")

                # Espera o fim do teste
                crashed = False
                while True:
                    code = proc.poll()
                    now = time.monotonic()
                    if code is not None:
                        if now >= deadline - finish_tol:
                            summary["status"] = "completed"
                        else:
                            crashed = True
                            self.log.warning("O jogo fechou sozinho apos %.1f min (codigo %s).",
                                             (now - start) / 60, code)
                            events("game_exited_early", f"code={code}")
                        break
                    if now > deadline + FORCE_KILL_GRACE_S:
                        self.log.warning("O jogo nao fechou sozinho no fim do teste; encerrando.")
                        kill_tree(proc)
                        events("force_killed", "")
                        summary["status"] = "completed"
                        break
                    time.sleep(2.0)

                if not crashed:
                    break
                summary["restarts"] += 1
                if summary["restarts"] > max_restarts:
                    summary["status"] = "failed_too_many_restarts"
                    break
                time.sleep(10)
        except KeyboardInterrupt:
            self.log.warning("Interrompido pelo usuario (Ctrl+C).")
            summary["status"] = "interrupted"
            raise
        finally:
            if proc is not None:
                kill_tree(proc)
            if pm:
                pm.stop()
                summary["presentmon_windows"] = pm.windows_recorded
            external.stop()
            if sysmon:
                sysmon.stop()
                summary["system_samples"] = sysmon.samples
            summary["finished_utc"] = utc_now_iso()
            summary["wall_elapsed_s"] = round(time.monotonic() - start, 1)
            events("test_end", summary["status"])
            events.close()
            (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log.info("Teste %s terminou: %s (%.2f h, %d reinicios)",
                          test.name, summary["status"], summary["wall_elapsed_s"] / 3600, summary["restarts"])
        return summary


def new_session_dir(cfg: Config) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    d = cfg.output_dir / f"sessao_{stamp}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(session_dir: Path) -> logging.Logger:
    log = logging.getLogger("bench")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(session_dir / "orquestrador.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def run_session(cfg: Config, tests: list[TestDef], duration_s: float, log: logging.Logger, session_dir: Path) -> list[dict]:
    # Guarda uma copia da configuracao usada (reprodutibilidade da pesquisa)
    shutil.copy2(cfg.bench_path, session_dir / "bench.json")
    shutil.copy2(cfg.tests_path, session_dir / "tests.json")
    (session_dir / "session.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tests": [t.name for t in tests],
        "duration_per_test_s": duration_s,
        "exe": str(cfg.game_exe()),
    }, indent=2), encoding="utf-8")

    cooldown_s = float(cfg.bench["run"].get("cooldown_minutes", 10)) * 60
    runner = TestRunner(cfg, session_dir, log)
    results = []
    with keep_system_awake(log):
        for i, test in enumerate(tests):
            results.append(runner.run_test(test, duration_s))
            if i < len(tests) - 1 and cooldown_s > 0:
                log.info("Pausa de %.0f min para a GPU esfriar antes do proximo teste...", cooldown_s / 60)
                time.sleep(cooldown_s)
    return results
