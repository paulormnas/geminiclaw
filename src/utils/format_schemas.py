"""Esquemas únicos dos formatos de comunicação dos agentes (v18.7-agent-system-prompts, ADR 022 §5).

Cada formato estruturado (plano, pareceres do Validator, rascunho do Problema, resposta do consultor, narrativa do
Summarizer e ``metrics.json``) é declarado uma vez aqui. O texto dos prompts é renderizado deste esquema, e o código
que valida o formato lê as mesmas listas de campos; um teste confere que os dois lados coincidem.

Módulo sem dependências do projeto (camada ``utils``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Campo:
    """Um campo de um formato.

    Args:
        nome: Nome do campo no JSON.
        tipo: Tipo em texto curto (``string``, ``list[str]``, ``objeto``...).
        descricao: O que o campo significa, em uma frase.
        obrigatorio: Se o código recusa o formato sem o campo.
        valores: Valores aceitos, quando o campo é uma enumeração.
        exemplo: Fragmento JSON do campo no esqueleto de saída (usado só pelos pareceres e pela narrativa).
        grupo: Nome do grupo condicional; o campo só aparece quando o grupo é pedido na renderização.
        nao_reprova: O campo faz parte do formato e a falta ou o valor dele nunca é motivo de reprovação.
    """

    nome: str
    tipo: str
    descricao: str
    obrigatorio: bool = False
    valores: tuple[str, ...] = ()
    exemplo: str = ""
    grupo: str = ""
    nao_reprova: bool = False


@dataclass(frozen=True)
class Esquema:
    """Formato declarado: lista de campos e as renderizações usadas nos prompts."""

    id: str
    campos: tuple[Campo, ...]

    def nomes(self) -> tuple[str, ...]:
        """Nomes de todos os campos, na ordem declarada."""
        return tuple(c.nome for c in self.campos)

    def obrigatorios(self) -> tuple[str, ...]:
        """Nomes dos campos obrigatórios, na ordem declarada."""
        return tuple(c.nome for c in self.campos if c.obrigatorio)

    def lista(self, *, grupos: tuple[str, ...] = ()) -> str:
        """Uma linha por campo: ``- "nome" (tipo, obrigatório): descrição``."""
        linhas = []
        for c in self.campos:
            if c.grupo and c.grupo not in grupos:
                continue
            marca = "obrigatório" if c.obrigatorio else "opcional"
            valores = f" Valores: {', '.join(c.valores)}." if c.valores else ""
            linhas.append(f'- "{c.nome}" ({c.tipo}, {marca}): {c.descricao}{valores}')
        return "\n".join(linhas)

    def json_de_saida(self, *, grupos: tuple[str, ...] = (), exemplos: dict[str, str] | None = None) -> str:
        """Esqueleto JSON da resposta, com o ``exemplo`` de cada campo (``exemplos`` troca o de campos nomeados)."""
        trocas = exemplos or {}
        itens = [
            f'  "{c.nome}": {trocas.get(c.nome, c.exemplo or "...")}'
            for c in self.campos
            if not c.grupo or c.grupo in grupos
        ]
        return "{\n" + ",\n".join(itens) + "\n}"


# --- Plano ---------------------------------------------------------------------------------------------------------

TIPOS_TAREFA = ("reproduction", "eda", "model_impl", "validation", "synthesis")
PAPEIS_PLANO = ("teste", "preparacao", "referencia")
TIPOS_ABORDAGEM = (
    "arquitetura", "algoritmo", "teste_estatistico", "pipeline", "protocolo", "instrumento", "biblioteca",
    "configuracao", "outro",
)

SUBTAREFA = Esquema(
    "subtarefa",
    (
        Campo("agent_id", "string", "developer para código e análise de dados; researcher para pesquisa técnica",
              obrigatorio=True),
        Campo("task_name", "string", "nome único em snake_case, por exemplo preparar_dados", obrigatorio=True),
        Campo("task_type", "string", "o tipo da tarefa", valores=TIPOS_TAREFA),
        Campo("prompt", "string", "instrução completa para o agente executor", obrigatorio=True),
        Campo("hypothesis", "string", "o que a subtarefa testa ou produz, em uma frase afirmativa"),
        Campo("scientific_rationale", "string", "por que a etapa é metodologicamente necessária"),
        Campo(
            "validation_criteria", "list[str]",
            "ao menos um critério verificável de aceite; em reproduction, ou em validation com hypothesis_ref, ao "
            "menos um critério com limiar numérico, por exemplo \"acurácia > 0.85\" (uma validation sem hipótese, "
            "como um baseline, dispensa o limiar)",
            obrigatorio=True,
        ),
        Campo("expected_artifacts", "list[str]", "nomes dos arquivos que a subtarefa deve gerar em /outputs/"),
        Campo("depends_on", "list[str]", "task_name das subtarefas das quais esta depende"),
        Campo("hypothesis_ref", "string", "referência (h1, h2...) ou id da hipótese que a subtarefa testa",
              nao_reprova=True),
        Campo(
            "papel", "string",
            "papel da subtarefa no experimento; sem ele o sistema decide pela estrutura do plano. Uma validation "
            "com papel referencia é o baseline do Problema e dispensa limiar numérico",
            valores=PAPEIS_PLANO, nao_reprova=True,
        ),
        Campo(
            "approach", "objeto",
            "método aplicado, {\"nome\": \"gradient boosting\", \"tipo\": \"algoritmo\"}; omita quando a subtarefa não "
            "aplica um método", valores=TIPOS_ABORDAGEM, nao_reprova=True,
        ),
        Campo("preferred_model", "string", "dica de modelo no formato provedor/modelo", nao_reprova=True),
        Campo(
            "discrimina", "list[str]",
            "só quando o objetivo do Problema é de discriminação: referências ou ids das hipóteses concorrentes que o "
            "resultado permite distinguir", nao_reprova=True,
        ),
        Campo(
            "experimento_fisico", "bool",
            "true quando distinguir as concorrentes exige bancada ou equipamento que o sandbox não tem; a subtarefa "
            "não é executada e vira pedido ao pesquisador", nao_reprova=True,
        ),
    ),
)

# Envelope do plano em projeto com exploração ativa (a lista de subtarefas vai em "subtarefas").
PLANO_EXPLORACAO = Esquema(
    "plano_exploracao",
    (
        Campo(
            "hipoteses", "list[objeto]",
            "cada item {\"ref\": \"h1\", \"id\": null, \"enunciado\": \"...\", \"justificativa\": \"...\", "
            "\"origem\": \"researcher\", \"derivada_de\": [\"<id de Descoberta|Oportunidade|Insumo>\"], "
            "\"custo_estimado\": \"baixo|medio|alto\", \"abordagem\": {\"nome\": \"...\", \"tipo\": \"algoritmo\"}}. "
            "Use id para continuar uma hipótese existente e ref para as novas; a origem real é decidida pelo sistema",
            obrigatorio=True,
        ),
        Campo(
            "decisoes", "list[objeto]",
            "toda escolha entre alternativas gera uma decisão {\"contexto\": \"...\", \"escolhido\": {\"tipo\": "
            "\"Hipotese\", \"ref\": \"h1\"}, \"descartados\": [{\"tipo\": \"Abordagem\", \"nome\": \"...\", "
            "\"motivo\": \"...\"}], \"criterio\": \"evidencia_previa\", \"justificativa\": \"...\", \"informada_por\": "
            "[\"<id de Descoberta>\"]}; inclua ao menos uma ao introduzir hipótese nova", obrigatorio=True,
        ),
        Campo(
            "respostas_sugestoes", "list[objeto]",
            "uma resposta a cada sugestão pendente do Curator, {\"sugestao_id\": \"...\", \"decisao\": \"aceita\" ou "
            "\"recusada\", \"motivo\": \"...\", \"hipotese_ref\": \"h2\"}; aceita exige a hipótese correspondente em "
            "hipoteses", obrigatorio=True,
        ),
        Campo("subtarefas", "list[objeto]", "as subtarefas do plano, no formato de subtarefa acima", obrigatorio=True),
        Campo(
            "objetivo", "objeto",
            "só para propor outro tipo de objetivo ao Problema, {\"tipo\": \"limiar\" | \"discriminacao\" | "
            "\"cobertura\", \"justificativa\": \"...\"}; no assisted e no semi vira pedido ao pesquisador. Nunca "
            "inclua a política ao atingir o objetivo",
        ),
    ),
)

# --- Pareceres do Validator ----------------------------------------------------------------------------------------

PARECER_PLANO = Esquema(
    "parecer_plano",
    (
        Campo("status", "string", "approved ou revision_needed", obrigatorio=True,
              exemplo='"approved" | "revision_needed"', valores=("approved", "revision_needed")),
        Campo("reason", "string", "explicação curta", exemplo='"explicação curta"'),
        Campo("issues", "list[str]", "problemas que o planejador consiga corrigir", exemplo='["problema 1", ...]'),
        Campo("metricas_status", "string", "parecer sobre a definição de métricas", grupo="metricas",
              exemplo='"approved" | "revision_needed"'),
        Campo("metricas_issues", "list[str]", "problemas da definição de métricas", grupo="metricas",
              exemplo='["problema 1", ...]'),
        Campo("objetivo_status", "string", "parecer sobre a proposta de objetivo", grupo="objetivo",
              exemplo='"approved" | "revision_needed"'),
        Campo("objetivo_issues", "list[str]", "problemas da proposta de objetivo", grupo="objetivo",
              exemplo='["problema 1", ...]'),
        Campo("restricoes_duvidosas", "list[objeto]", "subtarefas cuja direção pode cair numa restrição ativa",
              grupo="restricoes", exemplo='[{"task_name": "...", "restricao_id": "...", "motivo": "..."}]'),
    ),
)

PARECER_REVISAO = Esquema(
    "parecer_revisao",
    (
        Campo("status", "string", "pass ou fail", obrigatorio=True, exemplo='"pass" | "fail"',
              valores=("pass", "fail")),
        Campo("feedback", "string", "explicação do parecer", exemplo='"explicação do parecer"'),
        Campo(
            "issues", "list[objeto]", "um item por problema, citando o critério ou a regra de integridade",
            exemplo='[{"tipo": "aceite", "item": "c2", "texto": "..."}, {"tipo": "integridade", "regra": '
                    '"<id da regra>", "texto": "..."}]',
        ),
        Campo("observacoes", "list[str]", "o que você viu e não reprova", exemplo='["..."]'),
        Campo("viola_restricao", "string|null", "id da restrição de direção seguida pela subtarefa, ou null",
              grupo="restricoes", exemplo='"<id da restrição>" | null'),
        Campo("predicoes", "list[objeto]", "conferência do resultado contra a predição de cada hipótese concorrente",
              grupo="predicoes",
              exemplo='[{"hipotese_id": "...", "conferencia": "confirma" | "contraria" | "inconclusiva", '
                      '"justificativa": "..."}]'),
    ),
)

# --- Rascunho do Problema ------------------------------------------------------------------------------------------

RASCUNHO_PROBLEMA = Esquema(
    "rascunho_problema",
    (
        Campo("titulo", "string", "título curto do problema", obrigatorio=True),
        Campo("resumo", "string", "contexto, lacuna, objetivo e o que seria um avanço", obrigatorio=True),
        Campo("classe", "string", "classe do problema"),
        Campo("caracteristicas_dados", "objeto", "características dos dados"),
        Campo("dominios", "list[str]", "termos de área do conhecimento, no máximo 10"),
        Campo("criterio_sucesso", "objeto", "o objetivo do problema, com o campo tipo (ver as regras do papel)"),
    ),
)

# --- Resposta do consultor -----------------------------------------------------------------------------------------

RESPOSTA_CONSULTOR = Esquema(
    "resposta_consultor",
    (
        Campo("resposta", "string", "resposta curta e verificável", obrigatorio=True, exemplo='"..."'),
        Campo("confianca", "string", "alta, media ou baixa", exemplo='"alta|media|baixa"',
              valores=("alta", "media", "baixa")),
        Campo("fontes", "list[objeto]", "páginas consultadas", exemplo='[{"url": "https://...", "titulo": "..."}]'),
        Campo("suposicoes", "list[str]", "suposições feitas", exemplo='["..."]'),
        Campo("recomendacao", "string", "o que fazer a seguir", exemplo='"..."'),
    ),
)

# --- Resposta da consulta do terminal (v18.7-session-events-terminal) ---------------------------------------------

RESPOSTA_CONSULTA_TERMINAL = Esquema(
    "consulta_terminal",
    (
        Campo("resposta", "string", "resposta ao pesquisador, com base no contexto fornecido", obrigatorio=True,
              exemplo='"..."'),
        Campo("orientacao_sugerida", "string|null",
              "mensagem para a pesquisa só quando o pesquisador pediu mudança de rumo; senão null",
              exemplo='"..." | null'),
    ),
)

# --- Narrativa do Summarizer ---------------------------------------------------------------------------------------

NARRATIVA = Esquema(
    "narrativa",
    (
        Campo("resumo_executivo", "string", "3 a 5 frases com o essencial dos resultados", obrigatorio=True),
        Campo("contexto_e_objetivo", "string",
              "o que foi solicitado e quais dados ou documentos de referência fundamentaram a tarefa",
              obrigatorio=True),
        Campo("metodologia", "string",
              "como as subtarefas foram decompostas e executadas; hipóteses e justificativas científicas",
              obrigatorio=True),
        Campo("analise_divergencias", "string",
              "hipótese de causa de cada divergência e se foi investigada; ou declare que não houve",
              obrigatorio=True),
        Campo("limitacoes", "string", "limitações dos dados, do método ou do escopo", obrigatorio=True),
        Campo("proximos_passos", "string",
              "extensões concretas baseadas nos resultados, inclusive experimentos para divergências",
              obrigatorio=True),
        Campo("confianca_nivel", "string", "alto, medio ou baixo", obrigatorio=True, valores=("alto", "medio", "baixo"),
              exemplo='"alto" | "medio" | "baixo"'),
        Campo("confianca_justificativa", "string", "por que esse nível de confiança", obrigatorio=True),
    ),
)

# --- metrics.json --------------------------------------------------------------------------------------------------

# Argumentos de ``save_experiment_artifacts`` que o Developer informa (``src/skills/code/scientific_helpers.py``).
METRICS_JSON = Esquema(
    "metrics_json",
    (
        Campo("task_name", "string", "nome da subtarefa", obrigatorio=True),
        Campo("params", "objeto", "parâmetros e hiperparâmetros usados, com a seed", obrigatorio=True),
        Campo("metrics", "objeto",
              "métricas calculadas a partir dos dados, nunca literais; nomes com letras, dígitos, _, . e -, "
              "começando por letra ou _", obrigatorio=True),
        Campo("seed", "int", "seed de aleatoriedade usada"),
        Campo("divergence_note", "string", "nota honesta quando o resultado diverge do esperado"),
        Campo("datasets", "list[str]", "nomes (sem caminho) dos arquivos de /inputs/ que o script leu"),
        Campo("baselines", "objeto", "valor de referência por métrica, quando houver"),
        Campo("unidades", "objeto", "unidade de cada métrica que tiver uma"),
    ),
)

ESQUEMAS = (SUBTAREFA, PLANO_EXPLORACAO, PARECER_PLANO, PARECER_REVISAO, RASCUNHO_PROBLEMA, RESPOSTA_CONSULTOR,
            RESPOSTA_CONSULTA_TERMINAL, NARRATIVA, METRICS_JSON)

MANDATORY_KEYS = list(SUBTAREFA.obrigatorios())  # agent_id, task_name, prompt, validation_criteria
NARRATIVE_FIELDS = NARRATIVA.nomes()

TITULO_FORMATO_PLANO = "FORMATO DO PLANO"


def formato_do_plano() -> str:
    """Texto do formato do plano, gerado dos esquemas; entra uma única vez no prompt do Researcher."""
    return (
        f"{TITULO_FORMATO_PLANO}\n"
        "Cada subtarefa é um objeto JSON com estes campos:\n"
        f"{SUBTAREFA.lista()}\n"
        "Fora de projeto com exploração ativa, devolva a lista de subtarefas em JSON.\n"
        "Em projeto com exploração ativa, devolva um objeto JSON com estas chaves, e a lista de subtarefas vai em "
        "subtarefas:\n"
        f"{PLANO_EXPLORACAO.lista()}"
    )


def formato_da_subtarefa() -> str:
    """Lista dos campos da subtarefa para o Validator do plano."""
    obrigatorios = ", ".join(SUBTAREFA.obrigatorios())
    return (
        f"Cada subtarefa do plano é um objeto JSON; os campos obrigatórios são {obrigatorios}. Os campos:\n"
        f"{SUBTAREFA.lista()}\n"
        "Os campos opcionais do orquestrador (hypothesis_ref, papel, approach, preferred_model, discrimina e "
        "experimento_fisico) fazem parte do formato e nunca são motivo de reprovação."
    )
