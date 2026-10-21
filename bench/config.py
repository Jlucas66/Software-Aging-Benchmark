"""Leitura dos arquivos de configuracao (config/bench.json e config/tests.json)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _strip_jsonc(text: str) -> str:
    """Remove comentarios // (linha inteira ou no fim da linha) e virgulas sobrando antes
    de } ou ]. Mantem as quebras de linha, entao o numero da linha continua igual ao do editor."""
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path: Path) -> dict:
    """Le JSON aceitando comentarios // e virgula sobrando no fim de listas/blocos."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(_strip_jsonc(text))
    except json.JSONDecodeError as e:
        original = text.splitlines()
        shown = original[e.lineno - 1].strip() if 0 < e.lineno <= len(original) else ""
        raise SystemExit(
            f"Erro de sintaxe em {path.name}, linha {e.lineno} (a mesma do VS Code): {e.msg}\n"
            f"  > {shown}\n"
            f"  Confira aspas duplas no nome do campo, a virgula no fim e se falta ou sobra uma chave {{ }}."
        ) from e


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
    # Caminhos relativos (ex.: "UE5Benchmark") sao contados a partir da pasta do repositorio,
    # entao o mesmo bench.json funciona em qualquer maquina que clonar o projeto.
    @staticmethod
    def _path(value: str) -> Path:
        if re.match(r"^[A-Za-z]:[\\/]", value):  # "C:/..." e absoluto mesmo fora do Windows
            return Path(value)
        p = Path(value).expanduser()
        return p if p.is_absolute() else (ROOT / p).resolve()

    @property
    def engine_dir(self) -> Path:
        return self._path(self.bench["unreal"]["engine_dir"])

    @property
    def project_dir(self) -> Path:
        return self._path(self.bench["unreal"]["project_dir"])

    @property
    def uproject(self) -> Path:
        found = sorted(self.project_dir.glob("*.uproject"))
        return found[0] if found else self.project_dir / "Benchmark.uproject"

    @property
    def project_name(self) -> str:
        return self.uproject.stem

    @property
    def package_dir(self) -> Path:
        return self._path(self.bench["unreal"]["package_dir"])

    @property
    def output_dir(self) -> Path:
        return self._path(self.bench["run"]["output_dir"])

    def game_exe(self) -> Path:
        explicit = (self.bench["game"].get("exe") or "").strip()
        if explicit:
            return self._path(explicit)
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


def platform_name() -> str:
    """'windows' ou 'linux' (usado no nome da pasta da sessao e como rotulo nas analises)."""
    return "windows" if is_windows() else "linux"