# Vocabulário controlado

Arquivos de carga inicial do grafo de conhecimento (`openspec/changes/v17-controlled-vocabulary`,
ADR 015 §4 e §8).

## `metrics.yaml`

Catálogo inicial de métricas (nome canônico, sinônimos, sentido, faixa, família), conforme o design
da mudança. Ampliável pelo processo de candidatos (`geminiclaw vocab ...`).

## `cnpq_areas.csv`

Tabela de Áreas do Conhecimento do CNPq, extraída **do PDF oficial** publicado pelo CNPq (Plataforma
Lattes), sem reconstrução de memória. A extração só separa código e denominação de cada linha e deriva
nível e pai pelo próprio código (formato `G AA SS EE D`: grande área, área, subárea, especialidade e
dígito verificador).

Formato (UTF-8, cabeçalho obrigatório):

| coluna | descrição |
|---|---|
| `codigo_cnpq` | código oficial da área (chave de idempotência) |
| `termo` | denominação oficial |
| `nivel` | `grande_area`, `area`, `subarea` ou `especialidade` |
| `codigo_pai` | `codigo_cnpq` do pai; vazio para `grande_area` |

### Versão da fonte

- Fonte (URL oficial do CNPq): <https://lattes.cnpq.br/documents/11871/24930/TabeladeAreasdoConhecimento.pdf>
- Versão/data da tabela: "Áreas do Conhecimento", relatório gerado em 30/06/2025 15:01 (41 páginas)
- Data da obtenção: 2026-10-06
- SHA-256 do PDF obtido: `a99cc8f943d8e96e47662c953083cec304748f41889d0bea663cc74d651c09ab`
- Conteúdo: 9 grandes áreas, 88 áreas, 366 subáreas e 872 especialidades (1335 linhas)
