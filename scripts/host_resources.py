"""Identifica o sistema e mede o consumo de recursos (Linux, Raspberry Pi 5 e macOS).

Escolhe sozinho o leitor certo (``/proc`` no Linux, ``psutil`` no macOS) a partir da identificação da plataforma
(``src.host.platform_info``). Não toca em banco, rede nem LLM.

Uso::

    uv run python scripts/host_resources.py                       # identificação + uma amostra (JSON)
    uv run python scripts/host_resources.py --watch 30            # amostra por 30 s e mostra picos e médias
    uv run python scripts/host_resources.py --watch 60 --pid 1234 # inclui a árvore de processos do PID
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Garante que src/ e scripts/ sejam importáveis quando executado como script solto.
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from scripts.benchmark.resources import make_sampler  # noqa: E402
from src.host.platform_info import detect_current  # noqa: E402


def identify() -> dict:
    """Plataforma atual e qual leitor de recursos será usado."""
    info = detect_current()
    return {**info.to_dict(), "leitor_de_recursos": "proc" if info.host_os == "linux" else "psutil"}


def sample(seconds: float, interval: float, pid: int | None) -> dict:
    """Amostra por ``seconds`` e devolve o resumo (picos e médias) do amostrador do sistema."""
    sampler = make_sampler(root_pid=pid, interval=interval)
    sampler.start()
    time.sleep(max(seconds, interval * 2))
    sampler.stop()
    sampler.join(timeout=5)
    return sampler.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", type=float, default=0.0, help="segundos de amostragem (0: uma amostra rápida)")
    parser.add_argument("--interval", type=float, default=1.0, help="intervalo entre amostras, em segundos")
    parser.add_argument("--pid", type=int, default=None, help="processo cuja árvore também é medida")
    args = parser.parse_args(argv)
    seconds = args.watch if args.watch > 0 else args.interval * 2.5
    report = {"sistema": identify(), "consumo": sample(seconds, args.interval, args.pid)}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
