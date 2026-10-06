# Vocabulário controlado

Arquivos de carga inicial do grafo de conhecimento (`openspec/changes/v17-controlled-vocabulary`,
ADR 015 §4 e §8).

## `metrics.yaml`

Catálogo inicial de métricas (nome canônico, sinônimos, sentido, faixa, família), conforme o design
da mudança. Ampliável pelo processo de candidatos (`geminiclaw vocab ...`).

## `cnpq_areas.csv` — PENDENTE (não versionado ainda)

A Tabela de Áreas do Conhecimento do CNPq **deve ser obtida da fonte oficial do CNPq** e não pode ser
reconstruída de memória (aprovação pendente da proposta). Enquanto o arquivo não existir, a carga
(`scripts/seed_vocabulary.py`) falha de forma explícita.

Formato esperado (UTF-8, cabeçalho obrigatório):

| coluna | descrição |
|---|---|
| `codigo_cnpq` | código oficial da área (chave de idempotência) |
| `termo` | denominação oficial |
| `nivel` | `grande_area`, `area`, `subarea` ou `especialidade` |
| `codigo_pai` | `codigo_cnpq` do pai; vazio para `grande_area` |

### Versão da fonte (preencher ao adicionar o arquivo)

- Fonte (URL oficial do CNPq): _a registrar_
- Versão/data da tabela: _a registrar_
- Data da obtenção: _a registrar_
