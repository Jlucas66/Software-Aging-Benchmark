"""Eventos do sistema operacional durante um teste.

Windows: o Visualizador de Eventos (logs "Sistema" e "Aplicativo"): avisos, erros e
eventos criticos, mais as instalacoes do Windows Update. Ex.: driver de video que parou
de responder e se recuperou (nvlddmkm), programa que travou, atualizacao instalada,
reinicio inesperado.
Linux: o journal do systemd (journalctl), avisos e erros.

Grava <teste>_eventos_sistema.txt na pasta da sessao. E o que permite dizer, depois,
se algo externo ao jogo aconteceu num ponto do teste.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import is_windows


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "oem", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace")


def _run(cmd: list[str], timeout: float = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"(falha ao executar {cmd[0]}: {e})"
    return r.returncode, _decode(r.stdout or b"") + _decode(r.stderr or b"")


def _windows(start: datetime, end: datetime) -> list[tuple[str, int, str]]:
    t0 = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    t1 = end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.999Z")
    when = f"TimeCreated[@SystemTime>='{t0}' and @SystemTime<='{t1}']"
    queries = [
        ("Sistema (avisos, erros e criticos; inclui o driver de video)", "System",
         f"*[System[(Level=1 or Level=2 or Level=3) and {when}]]"),
        ("Windows Update (downloads e instalacoes)", "System",
         f"*[System[Provider[@Name='Microsoft-Windows-WindowsUpdateClient'] and {when}]]"),
        ("Aplicativo (erros e criticos; inclui programas que travaram)", "Application",
         f"*[System[(Level=1 or Level=2) and {when}]]"),
    ]
    out = []
    for title, log, xpath in queries:
        code, text = _run(["wevtutil", "qe", log, f"/q:{xpath}", "/f:text", "/rd:false"])
        out.append((title, code, text.strip()))
    return out


def _linux(start: datetime, end: datetime) -> list[tuple[str, int, str]]:
    if not shutil.which("journalctl"):
        return [("journal", 1, "journalctl nao encontrado")]
    fmt = "%Y-%m-%d %H:%M:%S"
    code, text = _run(["journalctl", "--since", start.astimezone().strftime(fmt),
                       "--until", end.astimezone().strftime(fmt), "-p", "warning",
                       "--no-pager", "-o", "short-iso"])
    return [("journal do sistema (avisos e erros)", code, text.strip())]


def export_events(start: datetime, end: datetime, out_path: Path) -> int:
    """Grava os eventos entre start e end. Devolve quantos eventos foram encontrados (aprox.)."""
    sections = _windows(start, end) if is_windows() else _linux(start, end)
    count = 0
    lines = [f"Eventos do sistema de {start.astimezone():%Y-%m-%d %H:%M:%S} a {end.astimezone():%Y-%m-%d %H:%M:%S}", ""]
    for title, code, text in sections:
        if is_windows():
            n = len(re.findall(r"^Event\[\d+\]", text, re.MULTILINE))
        else:  # cada evento do journalctl comeca com a data: 2026-10-22T15:26:23-0300
            n = len(re.findall(r"^\d{4}-\d{2}-\d{2}T", text, re.MULTILINE))
        count += n
        if n:
            body = text
        elif code != 0 and text:
            body = f"(nao foi possivel consultar: {text})"
        else:
            body = "(nenhum)"
        lines += ["=" * 80, f"{title}: {n} evento(s)", "=" * 80, body, ""]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return count