"""Leitura dos resultados gravados (sessao.json + um CSV por teste).

Usado pelo relatorio (bench/report.py) e pelo Mann-Kendall (bench/aging.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class TestResult:
    session: str          # nome da pasta da sessao
    platform: str         # "windows" / "linux" (do sessao.json)
    meta: dict            # entrada do teste no sessao.json
    df: pd.DataFrame      # amostras (vazio se o teste nao gravou nada)
    path: Path            # CSV do teste

    @property
    def id(self) -> int:
        return int(self.meta.get("id", 0))

    @property
    def name(self) -> str:
        return self.meta.get("nome", self.path.stem)

    @property
    def launches(self) -> list[int]:
        """Numeros das execucoes que gravaram amostras (mais de uma = o jogo foi reaberto)."""
        if self.df.empty or "execucao" not in self.df:
            return []
        return sorted(int(x) for x in self.df["execucao"].dropna().unique())


def find_sessions(path: Path) -> list[Path]:
    """Aceita a pasta de uma sessao ou uma pasta com varias sessoes (ex.: BenchmarkRuns)."""
    path = Path(path)
    if (path / "sessao.json").exists():
        return [path]
    found = {p.parent for pattern in ("*/sessao.json", "*/*/sessao.json") for p in path.glob(pattern)}
    return sorted(found)


def read_samples(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    if df.empty:
        return df
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, format="ISO8601")
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def load_session(session_dir: Path) -> tuple[dict, list[TestResult]]:
    session_dir = Path(session_dir)
    meta = json.loads((session_dir / "sessao.json").read_text(encoding="utf-8"))
    tests = []
    for t in meta.get("testes", []):
        csv_path = session_dir / t.get("arquivo", f"{t.get('nome')}.csv")
        tests.append(TestResult(session=session_dir.name, platform=meta.get("plataforma", "?"),
                                meta=t, df=read_samples(csv_path), path=csv_path))
    return meta, tests