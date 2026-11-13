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


def test_presentmon_fg():
    with tempfile.TemporaryDirectory() as d:
        csv = Path(d) / "pm.csv"
        rows = ["Application,ProcessID,FrameType,CPUStartTime,FrameTime,GPUBusy,DisplayedTime"]
        t = 0.0
        for i in range(100):           # 100 renderizados a 20 ms + 100 gerados (FG 2x)
            rows.append(f"b1-Win64-Shipping.exe,1,Application,{t:.3f},10,15,10")
            rows.append(f"b1-Win64-Shipping.exe,1,NVIDIA,{t + 10:.3f},10,0,10")
            t += 20.0
        rows.append("outro.exe,2,Application,0,5,5,5")
        csv.write_text("\n".join(rows) + "\n")
        src = PresentMonSource("x", "b1-Win64-Shipping.exe", csv, [], Log())
        out = src.aggregate(2.0)
        assert out["avg_fps"] == 50.0, out          # renderizados / 2 s
        assert out["dlssg_fps"] == 100.0, out       # exibidos / 2 s
        assert out["dlssg_frames_presented"] == 2.0
        assert abs(out["p99_frametime_ms"] - 20.0) < 1e-6, out
        assert out["gpu_time_ms"] == 15.0
        assert src.aggregate(5.0) == {}             # nada novo


def test_presentmon_v1_sem_fg():
    with tempfile.TemporaryDirectory() as d:
        csv = Path(d) / "pm.csv"
        rows = ["Application,ProcessID,TimeInSeconds,MsBetweenPresents,MsBetweenDisplayChange,MsGPUActive"]
        rows += [f"b1-Win64-Shipping.exe,1,{i * 0.0125:.4f},12.5,12.5,10" for i in range(80)]
        csv.write_text("\n".join(rows) + "\n")
        out = PresentMonSource("x", "b1-Win64-Shipping.exe", csv, [], Log()).aggregate(1.0)
        assert out["avg_fps"] == 80.0 and "dlssg_fps" not in out, out


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
