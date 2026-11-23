"""Orquestracao do Black Myth: Wukong Benchmark Tool (Steam, AppID 3132990).

O Benchmark Tool nao tem modo de linha de comando nem API. O que existe, e este modulo usa:
  - configuracoes em <instalacao>/b1/Saved/Config/Windows/GameUserSettings.ini
    (linha UISettingData=(("Chave", "Valor"),...) = o que aparece no menu do jogo,
    mais a secao [ScalabilityGroups]);
  - abertura pela Steam: steam -applaunch 3132990 [argumentos]. O argumento -benchmark da
    Unreal comeca o teste direto, sem menu (relatado por terceiros; CONFIRA na sua maquina
    com `python wukong.py validar`);
  - um JSON por volta concluida em %TEMP%/b1/BenchMarkHistory/Tool/<unix-time> (no Linux,
    dentro do prefixo do Proton), com FPS medio/min/max/95% e as configuracoes aplicadas;
  - teclado e mouse (acoes configuraveis) para o que so da para fazer pela interface,
    como ligar o modo de repeticao (loop).

Para a pesquisa de software aging o ideal e UM processo do jogo durante as 48 h inteiras
(modo de repeticao do proprio Benchmark Tool). Reabrir o jogo a cada volta zera o estado do
processo e mede outra coisa; o sessao.json registra quantas vezes o jogo foi aberto.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from .config import ROOT, is_windows, load_jsonc, platform_name
from .monitor import is_game_process

APP_ID = 3132990
GAME_EXE = "b1-Win64-Shipping.exe"
INI_REL = Path("b1/Saved/Config/Windows/GameUserSettings.ini")
MAIN_SECTION = "/Script/GSGameSettings.GSGameUserSettings"
SCALABILITY_SECTION = "ScalabilityGroups"
PROFILES_DIR = ROOT / "config" / "wukong_perfis"

# Campos do JSON de resultado que dizem quais configuracoes o jogo de fato usou
APPLIED_KEYS = ["ScreenMode", "ScreenResolution", "QualityLevel", "ImageQuality", "Rtx", "Dlss",
                "InsertFrame", "Dx12", "MotionBlur", "ViewDistance", "AntiAliasing", "PostProcessing",
                "ShadowQuality", "TextureQuality", "MaterialQuality", "VegetationQuality"]


# ============================================================================ Steam

def steam_roots() -> list[Path]:
    roots: list[Path] = []
    if is_windows():
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        roots.append(Path("C:/Program Files (x86)/Steam"))
    else:
        home = Path.home()
        roots += [home / ".steam/steam", home / ".local/share/Steam",
                  home / ".var/app/com.valvesoftware.Steam/.local/share/Steam", home / "snap/steam/common/.local/share/Steam"]
    out, seen = [], set()
    for r in roots:
        try:
            rr = r.resolve()
        except OSError:
            continue
        if rr.exists() and rr not in seen:
            seen.add(rr)
            out.append(rr)
    return out


def steam_libraries() -> list[Path]:
    libs: list[Path] = []
    for root in steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
    out, seen = [], set()
    for lib in libs:
        key = str(lib).lower()
        if key not in seen and (lib / "steamapps").exists():
            seen.add(key)
            out.append(lib)
    return out


def find_install() -> tuple[Path | None, Path | None]:
    """(pasta do Benchmark Tool, biblioteca Steam onde ele esta)"""
    for lib in steam_libraries():
        acf = lib / "steamapps" / f"appmanifest_{APP_ID}.acf"
        if acf.exists():
            m = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text(encoding="utf-8", errors="ignore"))
            if m:
                d = lib / "steamapps" / "common" / m.group(1)
                if d.exists():
                    return d, lib
    return None, None


def steam_command() -> list[str] | None:
    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                exe = winreg.QueryValueEx(k, "SteamExe")[0]
                if Path(exe).exists():
                    return [exe]
        except (ImportError, OSError):
            pass
        for r in steam_roots():
            if (r / "steam.exe").exists():
                return [str(r / "steam.exe")]
        return None
    if shutil.which("steam"):
        return ["steam"]
    if shutil.which("flatpak") and (Path.home() / ".var/app/com.valvesoftware.Steam").exists():
        return ["flatpak", "run", "com.valvesoftware.Steam"]
    return None


# ============================================================================ GameUserSettings.ini

TUPLE_RE = re.compile(r'\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)')


def parse_ui(value: str) -> dict[str, str]:
    """UISettingData=(("Dlss", "1"),("Rtx", "0")) -> {"Dlss": "1", "Rtx": "0"} (ordem mantida)"""
    return {k: v for k, v in TUPLE_RE.findall(value or "")}


def format_ui(data: dict[str, str]) -> str:
    return "(" + ",".join(f'("{k}", "{v}")' for k, v in data.items()) + ")"


class GameIni:
    """Edicao pontual do GameUserSettings.ini: so as chaves pedidas mudam, o resto fica igual
    (inclusive linhas repetidas como LastGPUBenchmarkSteps)."""

    def __init__(self, text: str):
        self.lines = text.splitlines()

    @classmethod
    def load(cls, path: Path) -> "GameIni":
        return cls(Path(path).read_text(encoding="utf-8-sig", errors="ignore"))

    def text(self) -> str:
        return "\r\n".join(self.lines) + "\r\n"

    def _section(self, name: str) -> tuple[int, int]:
        header = f"[{name}]"
        for i, line in enumerate(self.lines):
            if line.strip() == header:
                end = next((j for j in range(i + 1, len(self.lines)) if self.lines[j].startswith("[")), len(self.lines))
                return i, end
        self.lines += ["", header]
        return len(self.lines) - 1, len(self.lines)

    def get(self, section: str, key: str) -> str | None:
        start, end = self._section(section)
        for line in self.lines[start + 1:end]:
            if line.split("=", 1)[0].strip() == key and "=" in line:
                return line.split("=", 1)[1]
        return None

    def set(self, section: str, key: str, value: str):
        start, end = self._section(section)
        for i in range(start + 1, end):
            if self.lines[i].split("=", 1)[0].strip() == key and "=" in self.lines[i]:
                self.lines[i] = f"{key}={value}"
                return
        insert = end
        while insert > start + 1 and not self.lines[insert - 1].strip():
            insert -= 1
        self.lines.insert(insert, f"{key}={value}")

    def ui(self) -> dict[str, str]:
        return parse_ui(self.get(MAIN_SECTION, "UISettingData") or "")

    def set_ui(self, updates: dict[str, str]):
        data = self.ui()
        data.update({k: str(v) for k, v in updates.items()})
        self.set(MAIN_SECTION, "UISettingData", format_ui(data))

    def scalability(self) -> dict[str, str]:
        start, end = self._section(SCALABILITY_SECTION)
        out = {}
        for line in self.lines[start + 1:end]:
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def summary(self) -> dict:
        keys = ["ResolutionSizeX", "ResolutionSizeY", "FullscreenMode", "bUseVSync", "FrameRateLimit"]
        return {"UISettingData": self.ui(), "ScalabilityGroups": self.scalability(),
                "principal": {k: self.get(MAIN_SECTION, k) for k in keys}}


# ============================================================================ janela e entrada

class InputDriver:
    """Teclado e mouse na janela do jogo. Coordenadas sao FRACOES da area da janela
    (0,0 = canto superior esquerdo; 1,1 = inferior direito), entao valem em qualquer resolucao.
    Windows: API do Windows (ctypes). Linux: xdotool (a janela do Proton tem a classe
    steam_app_3132990)."""

    VK = {"enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09,
          "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "backspace": 0x08}
    XK = {"enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "space": "space",
          "tab": "Tab", "up": "Up", "down": "Down", "left": "Left", "right": "Right", "backspace": "BackSpace"}

    def __init__(self, log: logging.Logger):
        self.log = log

    # ---------------- janela
    def window(self, pid: int | None) -> tuple | None:
        """(identificador, x, y, largura, altura) da area da janela do jogo, ou None."""
        return self._win_window(pid) if is_windows() else self._x_window()

    def _win_window(self, pid):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        # Tipos declarados: sem isso o ctypes converte o HWND (64 bits) para int de 32 bits
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        found = []
        pids = {pid} if pid else set()
        if psutil is not None:
            for p in psutil.process_iter(["name"]):
                if is_game_process(p, GAME_EXE):
                    pids.add(p.pid)

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value in pids and user32.IsWindowVisible(hwnd):
                r = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(r))
                pt = wintypes.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(pt))
                if r.right > 200 and r.bottom > 200:
                    found.append((hwnd, pt.x, pt.y, r.right, r.bottom))
            return True

        user32.EnumWindows(cb, 0)
        return max(found, key=lambda w: w[3] * w[4]) if found else None

    def _x_window(self):
        if not shutil.which("xdotool"):
            return None
        try:
            ids = subprocess.run(["xdotool", "search", "--class", f"steam_app_{APP_ID}"],
                                 capture_output=True, text=True, timeout=10).stdout.split()
        except (OSError, subprocess.TimeoutExpired):
            return None
        best = None
        for wid in ids:
            geo = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                                 capture_output=True, text=True, timeout=10).stdout
            d = dict(line.split("=", 1) for line in geo.split() if "=" in line)
            try:
                w = (wid, int(d["X"]), int(d["Y"]), int(d["WIDTH"]), int(d["HEIGHT"]))
            except (KeyError, ValueError):
                continue
            if w[3] > 200 and w[4] > 200 and (best is None or w[3] * w[4] > best[3] * best[4]):
                best = w
        return best

    def focus(self, win):
        if is_windows():
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(0x12, 0, 0, 0)        # ALT: libera o SetForegroundWindow
            user32.SetForegroundWindow(win[0])
            user32.keybd_event(0x12, 0, 2, 0)
        else:
            subprocess.run(["xdotool", "windowactivate", "--sync", str(win[0])], timeout=10,
                           capture_output=True)
        time.sleep(0.3)

    # ---------------- acoes
    def key(self, name: str):
        n = name.strip().lower()
        if is_windows():
            import ctypes
            user32 = ctypes.windll.user32
            vk = self.VK.get(n) or (ord(n.upper()) if len(n) == 1 else None)
            if vk is None:
                raise ValueError(f"tecla desconhecida: {name}")
            scan = user32.MapVirtualKeyW(vk, 0)
            user32.keybd_event(vk, scan, 0, 0)
            time.sleep(0.08)
            user32.keybd_event(vk, scan, 2, 0)
        else:
            subprocess.run(["xdotool", "key", self.XK.get(n, name)], timeout=10)

    def click(self, win, fx: float, fy: float):
        x, y = int(win[1] + fx * win[3]), int(win[2] + fy * win[4])
        if is_windows():
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetCursorPos(x, y)
            time.sleep(0.15)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.08)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        else:
            subprocess.run(["xdotool", "mousemove", str(x), str(y)], timeout=10)
            time.sleep(0.15)
            subprocess.run(["xdotool", "click", "1"], timeout=10)

    def cursor_fraction(self, win) -> tuple[float, float] | None:
        if is_windows():
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            x, y = pt.x, pt.y
        else:
            out = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True).stdout
            d = dict(line.split("=", 1) for line in out.split() if "=" in line)
            x, y = int(d.get("X", 0)), int(d.get("Y", 0))
        return (x - win[1]) / win[3], (y - win[2]) / win[4]

    def run_actions(self, actions: list[str], pid: int | None) -> bool:
        """Acoes: "Key:Enter", "Click:0.115,0.452", "Wait:3000" (ms)."""
        if not actions:
            return True
        win = self.window(pid)
        if win is None:
            self.log.warning("Janela do jogo nao encontrada para enviar teclado/mouse.")
            return False
        self.focus(win)
        for a in actions:
            kind, _, arg = a.partition(":")
            kind = kind.strip().lower()
            if kind == "wait":
                time.sleep(float(arg) / 1000.0)
            elif kind == "key":
                self.key(arg)
            elif kind == "click":
                fx, fy = (float(v) for v in arg.split(","))
                self.click(self.window(pid) or win, fx, fy)
            else:
                raise ValueError(f"acao desconhecida: {a}")
            time.sleep(0.2)
        return True


# ============================================================================ instalacao

@dataclass
class WukongInstall:
    cfg: dict
    install_dir: Path | None = None
    library: Path | None = None
    problems: list[str] = field(default_factory=list)

    @classmethod
    def detect(cls, cfg: dict) -> "WukongInstall":
        w = cls(cfg)
        explicit = (cfg.get("install_dir") or "").strip()
        if explicit:
            w.install_dir = Path(os.path.expandvars(explicit)).expanduser()
            w.library = w.install_dir.parent.parent.parent if w.install_dir.parent.name == "common" else None
        else:
            w.install_dir, w.library = find_install()
        return w

    @property
    def ini(self) -> Path | None:
        return self.install_dir / INI_REL if self.install_dir else None

    @property
    def exe(self) -> Path | None:
        return self.install_dir / "b1" / "Binaries" / "Win64" / GAME_EXE if self.install_dir else None

    def history_dirs(self) -> list[Path]:
        """Onde o Benchmark Tool grava um JSON por volta concluida."""
        explicit = (self.cfg.get("history_dir") or "").strip()
        if explicit:
            return [Path(os.path.expandvars(explicit)).expanduser()]
        if is_windows():
            return [Path(os.environ.get("TEMP", "")) / "b1" / "BenchMarkHistory" / "Tool"]
        out = []
        if self.library:
            users = self.library / "steamapps" / "compatdata" / str(APP_ID) / "pfx" / "drive_c" / "users"
            for user in ("steamuser",):
                for temp in ("AppData/Local/Temp", "Temp", "Local Settings/Temp"):
                    out.append(users / user / temp / "b1" / "BenchMarkHistory" / "Tool")
        return out

    def history_files(self) -> dict[Path, float]:
        files = {}
        for d in self.history_dirs():
            if d.exists():
                for f in d.iterdir():
                    if f.is_file():
                        try:
                            files[f] = f.stat().st_mtime
                        except OSError:
                            pass
        return files

    def dll_versions(self) -> dict:
        """Tamanho e data das DLLs da NVIDIA que vem com o jogo (DLSS, Frame Generation,
        Reflex). Muda quando a Steam atualiza o Benchmark Tool: anote no trabalho."""
        out = {}
        if not self.install_dir:
            return out
        for pattern in ("nvngx_dlss*.dll", "sl.*.dll", "nvngx_dlssg.dll"):
            for f in self.install_dir.rglob(pattern):
                st = f.stat()
                out[f.name] = {"bytes": st.st_size,
                               "modificado": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
        return out


def find_game_pid(since: float) -> int | None:
    if psutil is None:
        return None
    best = None
    for p in psutil.process_iter(["create_time"]):
        try:
            if p.info["create_time"] >= since - 5 and is_game_process(p, GAME_EXE):
                if best is None or p.info["create_time"] > best[1]:
                    best = (p.pid, p.info["create_time"])
        except psutil.Error:
            continue
    return best[0] if best else None


def kill_game(log: logging.Logger | None = None) -> int:
    """Fecha o jogo A FORCA. Fechar normalmente faz o jogo regravar o GameUserSettings.ini
    com o que ele tinha carregado; como o perfil e reaplicado antes de cada abertura, nao
    faz diferenca para os testes, mas mantem o arquivo previsivel."""
    n = 0
    if psutil is None:
        return 0
    for p in psutil.process_iter():
        try:
            if is_game_process(p, GAME_EXE):
                p.kill()
                n += 1
        except psutil.Error:
            continue
    if n and log:
        log.info("Benchmark Tool encerrado (%d processo(s)).", n)
    return n


def load_result(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig", errors="ignore"))
    except (OSError, ValueError):
        return None


def result_summary(data: dict) -> dict:
    recs = data.get("Records") or []
    out = {k: data.get(k) for k in ("TimeStamp", "FPSAvg", "FPSMin", "FPSMax", "FPS95", "GameVer", "GpuDriverVer")}
    out["registros"] = len(recs)
    if recs:
        try:
            out["duracao_s"] = round((recs[-1]["TimeStamp"] - recs[0]["TimeStamp"]) / 1000.0, 1)
        except (KeyError, TypeError):
            pass
    out.update({k: data.get(k) for k in APPLIED_KEYS})
    return out


def compare_applied(expected_ui: dict[str, str], result: dict) -> list[str]:
    """Confere, pelo JSON da volta, se o jogo usou as configuracoes do perfil."""
    problems = []
    for key in ("Dlss", "InsertFrame", "Rtx", "QualityLevel"):
        if key in expected_ui and key in result:
            want, got = str(expected_ui[key]).strip(), str(result[key]).strip()
            if want != got:
                problems.append(f"{key}: perfil={want}, jogo usou={got}")
    return problems


# ============================================================================ configuracao

class WukongConfig:
    def __init__(self, bench_path: Path, tests_path: Path):
        self.bench_path, self.tests_path = Path(bench_path), Path(tests_path)
        self.bench = load_jsonc(self.bench_path)
        raw = load_jsonc(self.tests_path)
        self.defaults = raw.get("todos", {})
        self.tests = []
        for t in raw["tests"]:
            self.tests.append({"id": int(t["id"]), "name": t["name"], "features": list(t.get("features", [])),
                               "perfil": t.get("perfil", t["name"]), "ui": dict(t.get("ui", {})),
                               "escalabilidade": dict(t.get("escalabilidade", {}))})
        names = [t["name"] for t in self.tests]
        if len(names) != len(set(names)):
            raise SystemExit(f"{self.tests_path.name}: existem testes com o mesmo nome.")

    @property
    def w(self) -> dict:
        return self.bench["wukong"]

    @property
    def output_dir(self) -> Path:
        p = Path(self.bench["run"]["output_dir"])
        return p if p.is_absolute() else ROOT / p

    def select(self, spec: str | None) -> list[dict]:
        if not spec or spec.lower() == "all":
            return list(self.tests)
        out = []
        for s in (x.strip() for x in spec.split(",") if x.strip()):
            m = [t for t in self.tests if str(t["id"]) == s or t["name"] == s]
            if not m:
                raise SystemExit(f"Teste '{s}' nao encontrado. Use 'python wukong.py list'.")
            out += m
        return out

    def profile_path(self, test: dict) -> Path:
        return PROFILES_DIR / f"{test['perfil']}.ini"

    def build_ini(self, test: dict, current_ini: Path) -> GameIni:
        """Perfil do teste (capturado do jogo) + o que vale para todos + ajustes do teste."""
        prof = self.profile_path(test)
        ini = GameIni.load(prof if prof.exists() else current_ini)
        ui = dict(self.defaults.get("ui", {}))
        ui.update(test["ui"])
        if ui:
            ini.set_ui(ui)
        for k, v in self.defaults.get("principal", {}).items():
            ini.set(MAIN_SECTION, k, str(v))
        for k, v in {**self.defaults.get("escalabilidade", {}), **test["escalabilidade"]}.items():
            ini.set(SCALABILITY_SECTION, k, str(v))
        return ini


# ============================================================================ sessao e execucao

class WukongSession:
    """Mesmo formato do sessao.json do UE5-Benchmark (o relatorio e o Mann-Kendall leem igual)."""

    def __init__(self, cfg: WukongConfig, inst: WukongInstall, tests: list[dict], duration_s: float, gpu):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        base = cfg.output_dir / f"{stamp}_{platform_name()}"
        self.dir = base
        n = 2
        while self.dir.exists():
            self.dir = base.with_name(f"{base.name}_{n}")
            n += 1
        self.dir.mkdir(parents=True)
        import platform as _pf
        w = cfg.w
        self.data = {
            "cena": "Black Myth: Wukong Benchmark Tool",
            "plataforma": platform_name(),
            "inicio": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fim": None,
            "maquina": {
                "sistema": _pf.platform(),
                "cpu": _pf.processor() or _pf.machine(),
                "ram_gb": round(psutil.virtual_memory().total / 2**30, 1) if psutil else None,
                "gpu": gpu.name, "driver_nvidia": gpu.driver,
            },
            "versoes": {"dlls_nvidia_do_jogo": inst.dll_versions()},
            "configuracao": {
                "horas_por_teste": round(duration_s / 3600, 4),
                "intervalo_amostra_s": cfg.bench["run"]["sample_interval_s"],
                "pausa_entre_testes_min": cfg.bench["run"].get("cooldown_minutes", 10),
                "instalacao": str(inst.install_dir),
                "argumentos": list(w.get("launch_args", [])),
                "modo_loop": w.get("modo_loop", "interno"),
                "fonte_frames": (w.get("frames") or {}).get("fonte", "nenhuma"),
            },
            "testes": [],
        }
        self.save()

    def save(self):
        path = self.dir / "sessao.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


class WukongRunner:
    def __init__(self, cfg: WukongConfig, inst: WukongInstall, session: WukongSession, gpu, log: logging.Logger):
        self.cfg, self.inst, self.session, self.gpu, self.log = cfg, inst, session, gpu, log
        self.w = cfg.w
        self.input = InputDriver(log)
        self.steam = steam_command()
        self.manual = False   # 1a abertura de cada teste feita pela pessoa (para ligar o loop no menu)

    # ---------------- passos
    def apply_profile(self, test: dict, entry: dict):
        ini = self.cfg.build_ini(test, self.inst.ini)
        self.inst.ini.write_text(ini.text(), encoding="utf-8")
        entry["perfil"] = test["perfil"] if self.cfg.profile_path(test).exists() else "(ini atual do jogo)"
        entry["configuracao_pedida"] = ini.summary()
        (self.session.dir / f"{test['name']}_GameUserSettings.ini").write_text(ini.text(), encoding="utf-8")
        return ini

    def launch(self) -> int | None:
        kill_game()
        time.sleep(3)
        since = time.time()
        cmd = self.steam + ["-applaunch", str(APP_ID)] + [str(a) for a in self.w.get("launch_args", [])]
        self.log.info("Abrindo pela Steam: %s", " ".join(cmd))
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        timeout = float(self.w.get("startup_timeout_s", 900))
        while time.time() - since < timeout:
            pid = find_game_pid(since)
            if pid:
                return pid
            time.sleep(2)
        return None

    def wait_manual_open(self, test: dict) -> int | None:
        """Modo manual: a pessoa abre o tool pela Steam, liga o loop e inicia o teste."""
        kill_game()
        time.sleep(3)
        since = time.time()
        timeout = float(self.w.get("manual_timeout_min", 60)) * 60
        msg = (f"\a\n{'=' * 70}\n  TESTE {test['name']}: perfil aplicado. Agora:\n"
               "    1. Abra o Black Myth: Wukong Benchmark Tool pela Steam (modo normal)\n"
               "    2. Ligue o modo de repeticao (loop) - NAO mude nenhuma outra configuracao\n"
               "    3. Inicie o teste de desempenho\n"
               f"  Aguardando ate {timeout / 60:.0f} min. A contagem das horas comeca quando a GPU ficar ocupada.\n"
               f"{'=' * 70}")
        print(msg, flush=True)
        self.log.info("Modo manual: aguardando a pessoa abrir o tool e iniciar o teste com o loop ligado.")
        while time.time() - since < timeout:
            pid = find_game_pid(since)
            if pid:
                self.log.info("Benchmark Tool aberto (pid %d).", pid)
                return pid
            time.sleep(2)
        return None

    def wait_gpu_busy(self, pid: int, timeout: float) -> bool:
        """Espera o teste comecar de fato (GPU ocupada), passando pela compilacao de shaders."""
        limiar = float(self.w.get("gpu_ocupada_pct", 70))
        t0 = time.time()
        busy_since = None
        while time.time() - t0 < timeout:
            if not self.alive(pid):
                return False
            util = (self.gpu.read() or {}).get("gpu_util_pct")
            if util is not None and util >= limiar:
                busy_since = busy_since or time.time()
                if time.time() - busy_since >= 10:
                    return True
            else:
                busy_since = None
            time.sleep(2)
        return False

    @staticmethod
    def alive(pid: int | None) -> bool:
        if not pid or psutil is None:
            return False
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False

    def start_lap(self, pid: int, first: bool) -> bool:
        actions = list(self.w.get("acoes_inicio", [])) if first else list(self.w.get("acoes_nova_volta", []))
        if not actions:
            return True
        delay = float(self.w.get("espera_menu_s", 30)) if first else 0
        if delay:
            self.log.info("Esperando %.0f s o menu carregar para enviar as acoes...", delay)
            time.sleep(delay)
        ok = self.input.run_actions(actions, pid)
        self.log.info("Acoes %s enviadas (%d).", "de inicio" if first else "de nova volta", len(actions))
        return ok

    def collect_laps(self, known: dict, test: dict, entry: dict, expected_ui: dict) -> int:
        """Copia os JSONs de voltas novas para a sessao e confere as configuracoes aplicadas."""
        new = 0
        laps_dir = self.session.dir / f"{test['name']}_voltas"
        for f, mtime in self.inst.history_files().items():
            if f in known and known[f] == mtime:
                continue
            known[f] = mtime
            data = load_result(f)
            if not data:
                continue
            laps_dir.mkdir(exist_ok=True)
            shutil.copy2(f, laps_dir / f"{f.name}.json")
            s = result_summary(data)
            s["horas"] = round((time.time() - entry["_t0"]) / 3600, 4)
            s["execucao"] = entry["execucoes"]
            entry["voltas"] += 1
            new += 1
            self._append_lap_csv(laps_dir.with_suffix(".csv"), s)
            if entry["voltas"] == 1:
                entry["configuracao_aplicada"] = {k: data.get(k) for k in APPLIED_KEYS}
                entry["versao_jogo"] = data.get("GameVer")
                probs = compare_applied(expected_ui, data)
                res = self.w.get("resolucao_esperada")
                if res and data.get("ScreenResolution"):
                    nums = re.findall(r"\d+", str(data["ScreenResolution"]))
                    if nums[:2] != [str(res[0]), str(res[1])]:
                        probs.append(f"resolucao: esperada {res[0]}x{res[1]}, jogo usou {data['ScreenResolution']}")
                for p in probs:
                    self.log.warning("Configuracao diferente do perfil: %s", p)
                entry["problemas"] += [f"configuracao: {p}" for p in probs]
                self.log.info("1a volta: FPS medio %.1f | Dlss=%s InsertFrame=%s Rtx=%s ImageQuality=%s",
                              float(data.get("FPSAvg") or 0), data.get("Dlss"), data.get("InsertFrame"),
                              data.get("Rtx"), data.get("ImageQuality"))
        return new

    @staticmethod
    def _append_lap_csv(path: Path, row: dict):
        import csv
        cols = ["horas", "execucao", "TimeStamp", "FPSAvg", "FPSMin", "FPSMax", "FPS95", "registros", "duracao_s",
                "Dlss", "InsertFrame", "Rtx", "ImageQuality", "QualityLevel", "ScreenResolution", "GameVer"]
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    # ---------------- teste
    def run_test(self, test: dict, duration_s: float) -> dict:
        from .eventos import export_events
        from .frames import FrameSampler, make_source
        from .monitor import ExternalMonitor, ProcessLog, TestMonitor

        run_cfg, mon_cfg = self.cfg.bench["run"], self.cfg.bench.get("monitor", {})
        sdir = self.session.dir
        raw_dir = sdir / ".tmp" / test["name"]
        raw_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": test["id"], "nome": test["name"], "features": test["features"],
            "arquivo": f"{test['name']}.csv", "status": "rodando",
            "inicio": datetime.now().astimezone().isoformat(timespec="seconds"), "fim": None,
            "horas": 0.0, "execucoes": 0, "reinicios": 0, "reaberturas_fim_de_volta": 0, "voltas": 0,
            "amostras": 0, "processos": f"{test['name']}_processos.csv",
            "eventos_sistema": f"{test['name']}_eventos_sistema.txt",
            "voltas_csv": f"{test['name']}_voltas.csv", "problemas": [], "_t0": time.time(),
        }
        self.session.data["testes"].append(entry)
        self.log.info("=" * 70)
        self.log.info("TESTE %s - %s | %.2f h | features: %s", test["id"], test["name"], duration_s / 3600,
                      ", ".join(test["features"]) or "nenhuma")
        ini = self.apply_profile(test, entry)
        expected_ui = ini.ui()
        self.session.save()

        current = {"pid": None}
        started_utc = datetime.now(timezone.utc)
        proc_log = ProcessLog(sdir / entry["processos"], started_utc, GAME_EXE,
                              interval_s=mon_cfg.get("processos_intervalo_s", 60),
                              min_cpu_pct=mon_cfg.get("processos_cpu_min_pct", 1.0),
                              min_mem_mb=mon_cfg.get("processos_mem_min_mb", 300))
        engine_csv = raw_dir / "engine_samples.csv"
        source = make_source(self.w.get("frames") or {}, GAME_EXE, raw_dir, self.log)
        sampler = FrameSampler(engine_csv, float(run_cfg["sample_interval_s"]), source,
                               lambda: self.alive(current["pid"]), self.log)
        monitor = TestMonitor(engine_csv, sdir / entry["arquivo"], GAME_EXE, self.gpu, started_utc, process_log=proc_log)
        external = ExternalMonitor(mon_cfg.get("external_cmd"), sdir)
        known = dict(self.inst.history_files())   # voltas antigas nao contam

        modo = self.w.get("modo_loop", "interno")
        idle_pct = float(self.w.get("parado_gpu_pct", 40))
        idle_s = float(self.w.get("parado_minutos", 3)) * 60
        max_restarts = int(run_cfg.get("max_restarts", 20))
        start = time.monotonic()
        deadline = start + duration_s
        try:
            monitor.start()
            sampler.start()
            external.start()
            while entry["execucoes"] == 0 or time.monotonic() < deadline - 60:
                entry["execucoes"] += 1
                self.log.info("Abrindo o Benchmark Tool (execucao %d, faltam %.2f h)",
                              entry["execucoes"], (deadline - time.monotonic()) / 3600)
                manual_now = self.manual and entry["execucoes"] == 1
                pid = self.wait_manual_open(test) if manual_now else self.launch()
                if not pid:
                    entry["problemas"].append("o Benchmark Tool nao abriu (Steam aberta e logada?)")
                    self.log.error("O Benchmark Tool nao abriu dentro do tempo limite.")
                    entry["status"] = "falhou (nao abriu)"
                    break
                current["pid"] = pid
                monitor.new_launch(pid, entry["execucoes"])
                self.session.save()
                if manual_now:
                    busy_timeout = float(self.w.get("manual_timeout_min", 60)) * 60
                else:
                    self.start_lap(pid, first=True)
                    busy_timeout = float(self.w.get("startup_timeout_s", 900))
                if not self.wait_gpu_busy(pid, busy_timeout):
                    if not self.alive(pid):
                        entry["problemas"].append("o jogo fechou antes do teste comecar")
                    else:
                        entry["problemas"].append("a GPU nao ficou ocupada: o teste nao comecou "
                                                  "(confira -benchmark / acoes_inicio com 'python wukong.py validar')")
                    entry["status"] = "falhou (nao comecou)"
                    break
                self.log.info("Teste rodando (GPU ocupada).")
                if manual_now:
                    # As horas do teste contam a partir daqui, nao do tempo esperando a pessoa
                    deadline = time.monotonic() + duration_s
                    start = time.monotonic()
                    entry["_t0"] = time.time()

                reason = self._watch(pid, deadline, known, test, entry, expected_ui, idle_pct, idle_s,
                                     can_restart_lap=(modo == "interno"))
                self.collect_laps(known, test, entry, expected_ui)
                if reason == "fim":
                    entry["status"] = "completo"
                    break
                if reason == "parado":
                    # A volta acabou e o jogo ficou parado na tela de resultados: o modo de
                    # repeticao nao esta ativo (ou as acoes de nova volta nao funcionaram)
                    msg = "GPU ociosa: a volta terminou e o jogo nao repetiu sozinho"
                    if modo == "interno" and not entry.get("_avisou_loop"):
                        entry["_avisou_loop"] = True
                        self.log.warning("%s. O modo de repeticao (loop) do Benchmark Tool nao esta ligado; "
                                         "o jogo sera REABERTO a cada volta (pior para medir aging). Veja WUKONG.md.", msg)
                        entry["problemas"].append(msg + " (modo de repeticao desligado?)")
                    entry["reaberturas_fim_de_volta"] += 1
                    kill_game(self.log)
                    time.sleep(5)
                    continue
                # fechou sozinho
                entry["reinicios"] += 1
                msg = f"o jogo fechou sozinho apos {(time.monotonic() - start) / 3600:.2f} h"
                self.log.warning(msg[0].upper() + msg[1:] + ".")
                entry["problemas"].append(msg)
                if entry["reinicios"] > max_restarts:
                    entry["status"] = "falhou (reinicios demais)"
                    break
                self.session.save()
                time.sleep(10)
            else:
                entry["status"] = "completo"
        except KeyboardInterrupt:
            self.log.warning("Interrompido pelo usuario (Ctrl+C).")
            entry["status"] = "interrompido"
            raise
        finally:
            kill_game(self.log)
            current["pid"] = None
            time.sleep(1)
            sampler.stop()
            monitor.stop()
            external.stop()
            self.collect_laps(known, test, entry, expected_ui)
            entry.pop("_t0", None)
            entry.pop("_avisou_loop", None)
            entry["fim"] = datetime.now().astimezone().isoformat(timespec="seconds")
            entry["horas"] = round((time.monotonic() - start) / 3600, 3)
            entry["amostras"] = monitor.samples
            try:
                n = export_events(started_utc, datetime.now(timezone.utc), sdir / entry["eventos_sistema"])
                entry["n_eventos_sistema"] = n
            except Exception as e:
                self.log.warning("Nao consegui exportar os eventos do sistema: %s", e)
            if entry["amostras"] and sampler.last_fps is None and (self.w.get("frames") or {}).get("fonte") != "nenhuma":
                entry["problemas"].append("nenhum FPS medido (PresentMon/MangoHud nao funcionou)")
            shutil.rmtree(sdir / ".tmp", ignore_errors=True)
            self.session.save()
            self.log.info("Teste %s terminou: %s (%.2f h, %d amostras, %d volta(s), aberto %d vez(es))",
                          test["name"], entry["status"], entry["horas"], entry["amostras"], entry["voltas"],
                          entry["execucoes"])
        return entry

    def _watch(self, pid, deadline, known, test, entry, expected_ui, idle_pct, idle_s, can_restart_lap) -> str:
        """Acompanha o processo ate: "fim" (acabou o tempo), "fechou" (o jogo fechou) ou
        "parado" (GPU ociosa por idle_s: a volta acabou e nao repetiu). Se houver
        acoes_nova_volta, tenta comecar outra volta no MESMO processo antes de desistir."""
        idle_since = None
        while True:
            now = time.monotonic()
            if now >= deadline:
                return "fim"
            if not self.alive(pid):
                return "fechou"
            if self.collect_laps(known, test, entry, expected_ui) and not can_restart_lap:
                return "parado"   # modo "relancar": cada volta concluida = reabrir o jogo
            util = (self.gpu.read() or {}).get("gpu_util_pct")
            if util is not None and util < idle_pct:
                idle_since = idle_since or now
                if now - idle_since >= idle_s:
                    if can_restart_lap and self.w.get("acoes_nova_volta"):
                        self.log.info("GPU ociosa por %.0f min: comecando outra volta pelas acoes.", idle_s / 60)
                        self.start_lap(pid, first=False)
                        if self.wait_gpu_busy(pid, 300):
                            entry["voltas_reiniciadas_por_acao"] = entry.get("voltas_reiniciadas_por_acao", 0) + 1
                            idle_since = None
                            continue
                    return "parado"
            else:
                idle_since = None
            time.sleep(5)


def run_session(cfg: WukongConfig, tests: list[dict], duration_s: float, manual: bool = False):
    from .monitor import GpuReader
    from .runner import keep_system_awake, setup_logging

    inst = WukongInstall.detect(cfg.w)
    gpu = GpuReader(cfg.bench.get("monitor", {}).get("gpu_index", 0))
    session = WukongSession(cfg, inst, tests, duration_s, gpu)
    log = setup_logging(session.dir)
    log.info("Sessao: %s", session.dir)
    backup = session.dir / "GameUserSettings.original.ini"
    shutil.copy2(inst.ini, backup)
    cooldown_s = float(cfg.bench["run"].get("cooldown_minutes", 10)) * 60
    runner = WukongRunner(cfg, inst, session, gpu, log)
    runner.manual = manual
    session.data["configuracao"]["abertura"] = "manual (loop ligado no menu)" if manual else "automatica"
    session.save()
    try:
        with keep_system_awake(log):
            for i, test in enumerate(tests):
                runner.run_test(test, duration_s)
                if i < len(tests) - 1 and cooldown_s > 0:
                    log.info("Pausa de %.0f min para a GPU esfriar antes do proximo teste...", cooldown_s / 60)
                    time.sleep(cooldown_s)
    except KeyboardInterrupt:
        log.warning("Sessao interrompida. Os dados ja gravados ficam em %s", session.dir)
    finally:
        kill_game()
        time.sleep(2)
        try:
            shutil.copy2(backup, inst.ini)
            log.info("Configuracoes originais do Benchmark Tool restauradas.")
        except OSError as e:
            log.warning("Nao consegui restaurar o GameUserSettings.ini: %s (copia em %s)", e, backup)
        session.data["fim"] = datetime.now().astimezone().isoformat(timespec="seconds")
        session.save()
    log.info("-" * 70)
    for r in session.data["testes"]:
        log.info("  %-18s %-22s %6.2f h %6d amostras %4d voltas %3d aberturas", r["nome"], r["status"], r["horas"],
                 r["amostras"], r["voltas"], r["execucoes"])
    log.info("Resultados em %s", session.dir)
    return session
