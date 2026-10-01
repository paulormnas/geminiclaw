# Proposta: Validação por Reprodução entre Nós

**ID:** `v20-reproduction-validation` · **Versão:** V20 · **Capacidade:** `reproduction-validation`
**ADRs de origem:** [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) §2
(validação mútua), §3 (validação por reprodução em vez de consenso; confiança cresce com
reproduções independentes), §4 (reproduzir consome recursos e só ocorre por decisão do
pesquisador) e as questões "Custo computacional" e "Variação de hardware";
[ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md) (código só no
sandbox); [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§5 (execução sem rede)
**Depende de:** `v20-federated-records` (tipo `experimento`), `v20-remote-knowledge-intake`,
`v18.5-sandbox-phases` (ativos declarados com sha256, execução sem rede),
`v18.5-execution-provenance`

## Por quê

O ADR 013 troca consenso caro por prática científica: um nó reexecuta o experimento publicado
por outro e publica, assinada, a confirmação ou a refutação. Faltava definir quando isso
acontece, quanto pode custar, como se compara um resultado obtido num Pi com outro obtido numa
estação com GPU, e o que é publicado.

## O que muda

- **Novo:** `geminiclaw federation reproduce <cid>`: o pesquisador escolhe um registro
  `experimento` e confirma depois de ver o resumo (código, pacotes, datasets, custo estimado).
  Nunca automático.
- **Novo:** execução **determinística e sem LLM**: o código publicado roda como está no sandbox
  (instalação e ativos com rede, execução sem rede), com os parâmetros e a seed publicados.
  Sem modelo de linguagem, não há custo de tokens nem risco de injeção de prompt.
- **Novo:** comparação de métricas com tolerância declarada pelo autor ou padrão do nó
  (relativa e absoluta), resultando em `confirmada`, `refutada` ou `inconclusiva` (falha de
  infraestrutura, dado privado, código ausente ou hash divergente).
- **Novo:** registro `reproducao` assinado com o resultado, as métricas obtidas, as diferenças,
  as tolerâncias usadas e o ambiente; publicado pela caixa de saída com revisão humana.
- **Novo:** limites próprios: tempo por reprodução e número por dia.
- **Fora do escopo:** reproduzir experimentos que dependem de dados privados ou de equipamentos
  (resultam em `inconclusiva` com motivo); reputação (calculada em
  `v20-remote-knowledge-intake` a partir destes registros).

## Impacto

- **Código:** `src/federation/reproduction.py` (planejamento, execução, comparação, registro),
  `src/federation/records.py` (tipo `reproducao`), `src/cli.py`, `src/config.py`, `.env.example`.
- **Recursos:** CPU, memória e disco do nó durante a reprodução, limitados pelo sandbox e pelos
  limites desta mudança.

## Aprovações necessárias

- **Execução de código vindo de outro nó** (não gerado localmente): mesma fronteira do sandbox
  (ADR 014), mas com origem não confiável. Revisão do Analista de Segurança e do Pentester
  antes do merge.
- Nenhuma alteração de schema além do tipo novo de registro (JSONB).
