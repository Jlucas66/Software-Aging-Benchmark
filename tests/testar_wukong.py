"""Testes rapidos (sem o jogo) das pecas do orquestrador do Wukong.

Uso: python tests/testar_wukong.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.frames import MangoHudSource, PresentMonSource, percentile  # noqa: E402
from bench.wukong import GameIni, compare_applied, format_ui, parse_ui  # noqa: E402

INI = """[/Script/GSGameSettings.GSGameUserSettings]
DesiredScreenWidth=1113
UISettingData=(("MainDisplay", "0"),("Dlss", "1"),("InsertFrame", "0"),("Rtx", "0"),("RtxLevel", "0"))
LastGPUBenchmarkSteps=1.0
LastGPUBenchmarkSteps=2.0
bUseVSync=True
FrameRateLimit=60.000000

[ScalabilityGroups]
sg.ResolutionQuality=58
"""


class Log:
    def info(self, *a): pass
    def warning(self, *a): pass
    def debug(self, *a): pass


def test_ini():
    ini = GameIni(INI)
    assert ini.ui()["Dlss"] == "1"
    ini.set_ui({"InsertFrame": "1", "Vsync": "0"})
    ini.set("/Script/GSGameSettings.GSGameUserSettings", "bUseVSync", "False")
    ini.set("ScalabilityGroups", "sg.RayTracingQuality", "2")
    again = GameIni(ini.text())
    ui = again.ui()
    assert ui["InsertFrame"] == "1" and ui["Vsync"] == "0" and list(ui)[0] == "MainDisplay"
    assert again.get("/Script/GSGameSettings.GSGameUserSettings", "bUseVSync") == "False"
    assert again.scalability()["sg.RayTracingQuality"] == "2"
    assert ini.text().count("LastGPUBenchmarkSteps") == 2   # linhas repetidas preservadas
    assert parse_ui(format_ui({"A": "1", "B": "x"})) == {"A": "1", "B": "x"}
    assert compare_applied({"Dlss": "1", "InsertFrame": "1"}, {"Dlss": 1, "InsertFrame": 0}) == \
        ["InsertFrame: perfil=1, jogo usou=0"]


def _rows(lines):
    import csv as _csv
    r = list(_csv.reader(lines))
    return [dict(zip(r[0], v)) for v in r[1:]]


def test_presentmon_fg():
    # Colunas do PresentMon 2.4+ (Ms*), 100 renderizados a 20 ms + 100 gerados (FG 2x)
    lines = ["Application,ProcessID,FrameType,CPUStartTime,MsBetweenPresents,MsGPUBusy,DisplayedTime"]
    t = 0.0
    for i in range(100):
        lines.append(f"b1-Win64-Shipping.exe,1,Application,{t:.3f},10,15,10")
        lines.append(f"b1-Win64-Shipping.exe,1,NVIDIA,{t + 10:.3f},10,0,10")
        t += 20.0
    lines.append("outro.exe,2,Application,0,5,5,5")
    src = PresentMonSource("x", "b1-Win64-Shipping.exe", Path("pm.csv"), [], Log())
    out = src.summarize(_rows(lines), 2.0)
    assert out["avg_fps"] == 50.0, out          # renderizados / 2 s
    assert out["dlssg_fps"] == 100.0, out       # exibidos / 2 s
    assert out["dlssg_frames_presented"] == 2.0
    assert abs(out["p99_frametime_ms"] - 20.0) < 1e-6, out
    assert out["gpu_time_ms"] == 15.0
    assert src.summarize([], 5.0) == {}


def test_presentmon_v1_sem_fg():
    lines = ["Application,ProcessID,TimeInSeconds,MsBetweenPresents,MsBetweenDisplayChange,MsGPUActive"]
    lines += [f"b1-Win64-Shipping.exe,1,{i * 0.0125:.4f},12.5,12.5,10" for i in range(80)]
    out = PresentMonSource("x", "b1-Win64-Shipping.exe", Path("pm.csv"), [], Log()).summarize(_rows(lines), 1.0)
    assert out["avg_fps"] == 80.0 and "dlssg_fps" not in out, out


def test_presentmon_stdout():
    """Le o CSV pelo stdout de um PresentMon falso (com BOM e uma mensagem antes)."""
    import os
    import time as _t
    if os.name == "nt":
        return
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "pm.sh"
        fake.write_text("#!/bin/sh\nprintf 'Aviso qualquer\\n'\nprintf '\\357\\273\\277Application,ProcessID,MsBetweenPresents\\n'\n"
                        "i=0; while [ $i -lt 60 ]; do echo 'b1-Win64-Shipping.exe,1,16.6'; i=$((i+1)); done\nsleep 30\n")
        fake.chmod(0o755)
        src = PresentMonSource(str(fake), "b1-Win64-Shipping.exe", Path(d) / "x.csv", [], Log(), diag_prefix=Path(d) / "t")
        src.start()
        _t.sleep(1.0)
        out = src.aggregate(1.0)
        src.stop()
        assert out["avg_fps"] == 60.0, out
        assert "Aviso qualquer" in (Path(d) / "t_presentmon.log").read_text()
        assert (Path(d) / "t_presentmon_amostra.csv").read_text().startswith("Aviso")


def test_mangohud():
    with tempfile.TemporaryDirectory() as d:
        src = MangoHudSource(Path(d), Log())
        src.start()
        f = Path(d) / "b1-Win64-Shipping_2026-11-12_10-00-00.csv"
        f.write_text("os,cpu,gpu,ram,kernel,driver,cpuscheduler\nLinux,i9,RTX 5070,32,6.8,575,x\n"
                     "fps,frametime,cpu_load,gpu_load,elapsed\n60,16.6,30,99,1\n62,16.1,30,99,2\n")
        out = src.aggregate(5.0)
        assert out["avg_fps"] == 61.0 and out["p99_frametime_ms"] > 16.1, out


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2.5 and percentile([], 99) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
