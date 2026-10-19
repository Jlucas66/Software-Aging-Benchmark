"""Leitura dos arquivos de configuracao (config/bench.json e config/tests.json)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_jsonc(path: Path) -> dict:
    """Le JSON aceitando linhas de comentario que comecam com //."""
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    try:
        return json.loads("\n".join(lines))
    except json.JSONDecodeError as e:
        raise SystemExit(f"Erro de sintaxe em {path.name}, linha ~{e.lineno}: {e.msg}") from e


@dataclass
class TestDef:
    id: int
    name: str
    features: list[str]
    cvars: dict[str, str] = field(default_factory=dict)

    def cvars_arg(self) -> str:
        return ";".join(f"{k}={v}" for k, v in self.cvars.items())


class Config:
    def __init__(self, bench_path: Path | None = None, tests_path: Path | None = None):
        self.bench_path = bench_path or CONFIG_DIR / "bench.json"
        self.tests_path = tests_path or CONFIG_DIR / "tests.json"
        self.bench = load_jsonc(self.bench_path)
        self.tests_raw = load_jsonc(self.tests_path)
        self.tests = self._build_tests()

    # ---------------- caminhos ----------------
    @property
    def engine_dir(self) -> Path:
        return Path(self.bench["unreal"]["engine_dir"])

    @property
    def project_dir(self) -> Path:
        return Path(self.bench["unreal"]["project_dir"])

    @property
    def uproject(self) -> Path:
        found = sorted(self.project_dir.glob("*.uproject"))
        return found[0] if found else self.project_dir / "Benchmark.uproject"

    @property
    def project_name(self) -> str:
        return self.uproject.stem

    @property
    def package_dir(self) -> Path:
        return Path(self.bench["unreal"]["package_dir"])

    @property
    def output_dir(self) -> Path:
        return Path(self.bench["run"]["output_dir"])

    def game_exe(self) -> Path:
        explicit = (self.bench["game"].get("exe") or "").strip()
        if explicit:
            return Path(explicit)
        # Executavel "de verdade" (o Benchmark.exe da raiz e so um lancador que abre este)
        name = self.project_name
        candidates = [
            self.package_dir / "Windows" / name / "Binaries" / "Win64" / f"{name}.exe",
            self.package_dir / "Windows" / name / "Binaries" / "Win64" / f"{name}-Win64-Shipping.exe",
            self.package_dir / name / "Binaries" / "Win64" / f"{name}.exe",
            self.package_dir / "Windows" / f"{name}.exe",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    # ---------------- testes ----------------
    def _build_tests(self) -> list[TestDef]:
        raw = self.tests_raw
        features = raw.get("features", {})
        tests: list[TestDef] = []
        for t in raw["tests"]:
            cvars: dict[str, str] = {}
            cvars.update({k: str(v) for k, v in raw.get("base_cvars", {}).items()})
            cvars.update({k: str(v) for k, v in raw.get("all_off", {}).items()})
            for feat in t.get("features", []):
                if feat not in features:
                    raise SystemExit(f"tests.json: o teste '{t['name']}' usa a feature '{feat}', que nao existe em 'features'.")
                cvars.update({k: str(v) for k, v in features[feat].items()})
            for k, v in cvars.items():
                if re.search(r"[;\s\"]", k + v):
                    raise SystemExit(f"tests.json: cvar invalida '{k}={v}' (nao use espacos, aspas ou ';').")
            tests.append(TestDef(id=int(t["id"]), name=t["name"], features=list(t.get("features", [])), cvars=cvars))
        names = [t.name for t in tests]
        if len(names) != len(set(names)):
            raise SystemExit("tests.json: existem testes com o mesmo nome.")
        return tests

    def select_tests(self, spec: str | None) -> list[TestDef]:
        """spec: 'all' ou lista '1,3,5' (ids) ou nomes."""
        if not spec or spec.lower() == "all":
            return list(self.tests)
        wanted = [s.strip() for s in spec.split(",") if s.strip()]
        out = []
        for w in wanted:
            match = [t for t in self.tests if str(t.id) == w or t.name == w]
            if not match:
                raise SystemExit(f"Teste '{w}' nao encontrado. Use 'python run.py list' para ver os disponiveis.")
            out.extend(match)
        return out


def is_windows() -> bool:
    return os.name == "nt"
