"""Linha de comando das explorações controladas (``v18.8-verdict-controlled-sessions``; ADR 026: sem veredito).

Uso (na raiz do repositório)::

    uv run python -m scripts.verdict_lab.controlled orcamento --plano PLANO [--piloto exploracoes.json] [--saida DIR]
    uv run python -m scripts.verdict_lab.controlled gerar --regime P --semente 7 --saida DIR
    uv run python -m scripts.verdict_lab.controlled explorar --plano PLANO --saida DIR            # ensaio (padrão)
    uv run python -m scripts.verdict_lab.controlled explorar --plano PLANO --saida DIR --executar \\
        --reset-stores --confirm-target BANCO@HOST [--no-pre-reset-dump] [--retomar]

``orcamento``, ``gerar`` e o ensaio de ``explorar`` não chamam LLM nem tocam
em banco. ``--executar`` roda sessões com
LLM e **só deve ser usado com a confirmação do pesquisador** e a tabela de orçamento aprovada. Códigos de saída:
2 recusa
(guarda do reset, plano, combinação ou saída ocupada), 3 exceção numa exploração, 4 reset ou conferência falhou.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.verdict_lab.controlled import budget, generator, regimes

EXIT_REFUSED = 2
EXIT_EXCEPTION = 3
EXIT_RESET_FAILED = 4


class SaidaOcupada(RuntimeError):
    """O diretório de saída já tem ``manifesto.json`` (``--sobrescrever`` ou ``--retomar`` libera)."""


def sha256_de(path: Path) -> str:
    return generator.sha256_arquivo(path)


def commit_atual() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip() or "desconhecido"
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def preparar_saida(saida: Path, *, sobrescrever: bool, retomar: bool) -> bool:
    """``True`` se é uma retomada (manifesto existente aceito).

    Raises:
        SaidaOcupada: Já existe ``manifesto.json`` e nem ``--sobrescrever`` nem ``--retomar`` foram passados.
    """
    existe = (saida / "manifesto.json").exists()
    if existe and not (sobrescrever or retomar):
        raise SaidaOcupada(
            f"{saida} já tem manifesto.json; use --retomar (continua a mesma rodada) ou --sobrescrever, "
            "ou outro --saida."
        )
    return existe and retomar and not sobrescrever


def escrever_manifesto(saida: Path, argv: list[str], plano_path: Path, plano: dict[str, Any], matriz_path: Path,
                       sementes: list[int]) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    manifesto = {
        "versao": 1,
        "commit": commit_atual(),
        "data_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "comando": argv,
        "python": sys.version.split()[0],
        "plataforma": platform.platform(),
        "entradas": {"plano": {"caminho": str(plano_path), "sha256": sha256_de(plano_path)},
                     "matriz": {"caminho": str(matriz_path), "sha256": sha256_de(matriz_path)}},
        "semente": plano["semente"],
        "sementes_dos_dados": sementes,
        "regimes": {nome: plano["repeticoes"][nome] for nome in plano["repeticoes"]},
    }
    (saida / "manifesto.json").write_text(json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_orcamento(args: argparse.Namespace) -> int:
    try:
        plano = budget.carregar_plano(args.plano)
        piloto = json.loads(args.piloto.read_text(encoding="utf-8")) if args.piloto else None
    except (budget.PlanError, OSError, ValueError) as exc:
        print(f"[controlled] RECUSADO: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    orcamento = budget.calcular(plano, piloto)
    print(budget.markdown(orcamento))
    if args.saida:
        args.saida.mkdir(parents=True, exist_ok=True)
        (args.saida / "orcamento.json").write_text(
            json.dumps(orcamento, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


def cmd_gerar(args: argparse.Namespace) -> int:
    try:
        conteudo = regimes.preparar_entrada(
            args.regime, args.semente, args.saida / "input_context", args.saida / "verdade"
        )
    except regimes.RegimeError as exc:
        print(f"[controlled] RECUSADO: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"regime {args.regime} semente {args.semente}: sha256 {conteudo['sha256_dados']}")
    return 0


def cmd_explorar(args: argparse.Namespace, argv: list[str]) -> int:
    from scripts.benchmark import reset_stores as rs
    from scripts.benchmark import run_benchmark as rb
    from scripts.verdict_lab.controlled import runner

    try:
        plano = budget.carregar_plano(args.plano)
        matriz_path = Path(plano["matriz"])
        matriz = json.loads(matriz_path.read_text(encoding="utf-8"))
        rb.validate_matrix(matriz)
        combos = {c["name"]: c for c in matriz["combinations"]}
        for nome in {c["nome"] for c in plano["combinacoes"]}:
            if nome not in combos:
                raise rb.CombinationRefused(f"combinação '{nome}' do plano não existe na matriz.")
            rb.validate_combination(combos[nome])
        maximo = max(plano["repeticoes"].values(), default=0)
        sementes = generator.sementes_das_repeticoes(plano["semente"], maximo)
        itens = runner.itens_do_plano(plano, combos, sementes)
    except (budget.PlanError, rb.CombinationRefused, ValueError, OSError) as exc:
        print(f"[controlled] RECUSADO: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    orcamento = budget.calcular(plano)
    if not args.executar:
        print("[controlled] ENSAIO (nenhum processo, banco ou arquivo); --executar só com confirmação do pesquisador.")
        for item in itens:
            print(f"  {item.nome}  semente {item.semente}  teto US$ {item.teto.usd:.2f}")
        print(budget.markdown(orcamento))
        return 0

    env_base = {**os.environ, **{k: v for k, v in _dotenv().items() if v is not None}}
    try:
        if not args.reset_stores:
            raise rs.ResetRefused("--executar exige --reset-stores (as explorações precisam de bancos isolados).")
        target = rs.BenchmarkTarget.from_env(env_base)
        rs.check_guards(target, reset_requested=True, confirm_target=args.confirm_target)
        retomada = preparar_saida(args.saida, sobrescrever=args.sobrescrever, retomar=args.retomar)
    except (rs.ResetRefused, SaidaOcupada) as exc:
        print(f"[controlled] RECUSADO: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    env_base = rs.target_env(target, env_base)
    runner.aplicar_alvo_ao_processo(env_base)
    print(f"[controlled] alvo: {target.label} ({target.safe_url})", flush=True)
    if not retomada:
        escrever_manifesto(args.saida, argv, args.plano, plano, matriz_path, sementes)
    output_dir = Path(env_base.get("OUTPUT_BASE_DIR", "outputs"))
    for item in itens:
        pasta = runner.diretorio_da(args.saida, item)
        if (pasta / "exploracao.json").exists():
            print(f"[controlled] {item.nome}: já executada, pulando", flush=True)
            continue
        exigido = item.combo.get("requires")
        if exigido and not env_base.get(exigido):
            print(f"[controlled] {item.nome}: {exigido} ausente, pulando", flush=True)
            continue
        print(f"[controlled] {item.nome} ...", flush=True)
        try:
            resultado = runner.executar_item(
                item, saida=args.saida, env_base=env_base, matriz=matriz, output_dir=output_dir, target=target,
                reset=True, dump=not args.no_pre_reset_dump,
            )
        except rs.ResetError as exc:
            print(f"[controlled] INTERROMPIDO em {item.nome}: reset falhou: {exc}", file=sys.stderr)
            return EXIT_RESET_FAILED
        except Exception as exc:  # noqa: BLE001 - registrado e interrompe: banco ou provedor fora do ar se repetiria
            print(f"[controlled] INTERROMPIDO em {item.nome}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return EXIT_EXCEPTION
        print(f"[controlled] {item.nome}: fim={resultado['fim']} ({resultado['motivo_final']}) "
              f"US$ {resultado['custo_total_usd']:.2f} sessões={resultado['n_sessoes']}", flush=True)
    return 0


def _dotenv() -> dict[str, str | None]:
    from dotenv import dotenv_values

    return dict(dotenv_values(".env"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    p_orc = sub.add_parser("orcamento", help="tabela de orçamento (sem LLM nem banco)")
    p_orc.add_argument("--plano", type=Path, required=True)
    p_orc.add_argument("--piloto", type=Path, default=None, help="JSON com a lista de exploracao.json do piloto")
    p_orc.add_argument("--saida", type=Path, default=None, help="grava orcamento.json neste diretório")
    p_ger = sub.add_parser("gerar", help="gera dados.csv, dados.yaml e verdade.json de um regime")
    p_ger.add_argument("--regime", choices=sorted(regimes.REGIMES), required=True)
    p_ger.add_argument("--semente", type=int, required=True)
    p_ger.add_argument("--saida", type=Path, required=True)
    p_exp = sub.add_parser("explorar", help="ensaio por padrão; --executar roda sessões com LLM")
    p_exp.add_argument("--plano", type=Path, required=True)
    p_exp.add_argument("--saida", type=Path, required=True)
    p_exp.add_argument("--executar", action="store_true", help="RODA SESSÕES COM LLM (custo)")
    p_exp.add_argument("--reset-stores", action="store_true",
                       help="OPERAÇÃO DESTRUTIVA: recria o banco e o Qdrant de benchmark antes de cada exploração")
    p_exp.add_argument("--confirm-target", default=None, help="banco@host de BENCHMARK_DATABASE_URL")
    p_exp.add_argument("--no-pre-reset-dump", action="store_true")
    p_exp.add_argument("--retomar", action="store_true", help="continua uma rodada interrompida (pula as já feitas)")
    p_exp.add_argument("--sobrescrever", action="store_true")
    args = parser.parse_args(argv)
    if args.comando == "orcamento":
        return cmd_orcamento(args)
    if args.comando == "gerar":
        return cmd_gerar(args)
    return cmd_explorar(args, argv)


if __name__ == "__main__":
    sys.exit(main())
