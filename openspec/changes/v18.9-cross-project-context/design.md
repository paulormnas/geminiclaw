# Design: v18.9-cross-project-context

## 1. Estado atual
- `project_session` monta o primeiro plano só com título, resumo e critério do Problema.
- `resume_context.py:167` usa `related_experience` apenas na retomada.
- `related_experience` (`semantic_index.py:856`) faz o ranking por similaridade × max(confiança, piso) × recência sobre `FUNCIONOU_PARA`/`FALHOU_PARA`/`Descoberta`.
- `similarity_queue` recebe duplicatas e relacionados, e o Curator revisa `CURATOR_QUEUE_BATCH` pares por execução.

## 2. Bloco de experiência

Modelo fixo por registro:

```
[<problema de origem> | classe <classe> | <n_linhas> linhas, <n_atributos> atributos]
<abordagem> (<config resumida>): <metrica> <melhor_valor> (alvo <alvo>; Δbase <delta_base>; réplicas <n>) — <qualificacao>
Limite: <limite_aplicabilidade ou "não qualificado">
Este problema: <classe> | <n_linhas> linhas, <n_atributos> atributos
```

- **Seleção:** os registros vêm dos `RELATED_RECORDS_K` Problemas mais semelhantes (§3). Por Problema, entram o melhor registro `atingiu_alvo` e o registro `restricao` mais recente. Registros `retido` ficam de fora.
- **Teto:** `RELATED_RECORDS_MAX_CHARS`.
- **Visibilidade:** só registros de projetos visíveis (regra de visibilidade atual).
- **Instrução que acompanha o bloco:** "experiência de outro problema é hipótese a testar, não conclusão".

## 3. Semelhança de Problemas

`sem = RELATED_TEXT_WEIGHT · cos(texto) + (1 − RELATED_TEXT_WEIGHT) · sim_dados`.

- `sim_dados` é a média, sobre as características presentes nos dois Problemas, de `1 − |log(a/b)| / log(10)` (limitada a [0, 1]) para contagens (linhas, atributos e classes) e de igualdade para categorias (tipo de tarefa).
- Sem `caracteristicas_dados`, vale `sem = cos(texto)`.

| Variável | Padrão |
|---|---|
| `RELATED_RECORDS_K` | 5 |
| `RELATED_RECORDS_MAX_CHARS` | 2500 |
| `RELATED_TEXT_WEIGHT` | 0.5 |
| `CROSS_PROJECT_CANDIDATES` | `false` |

## 4. Candidatos no ciclo

Ao fim de cada ciclo, `candidates.generate` roda sobre o grafo:
- **Mesmo projeto:** os candidatos entram em `sugestoes_pendentes_do_curator` (bloco já existente em `exploration.py:276`), com `tipo` e atributos em texto.
- **Outro projeto:** quando `CROSS_PROJECT_CANDIDATES=true`, o candidato vira `Oportunidade` com `origem = "grafo"`, a propriedade `registro_origem_id` e status `documentada` (aguarda o pesquisador). Nunca vira hipótese sem aprovação (ADR 013).

## 5. Fila de similaridade

- **Varredura:** classifica só duplicatas. A faixa de relacionados não é enfileirada.
- **Migração:** os pares `relacionado` pendentes passam a `descartado` com `motivo = "ADR 026: relação sob demanda"`, por `UPDATE`, sem apagar linhas.
- **Arestas:** as `SEMELHANTE_A` já confirmadas continuam válidas.

## 6. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Domínio | A correlação passa a operar sem depender do Curator |
| Camadas | `orchestration` lê de `knowledge`, como hoje |
| Dados | Ver §5 |
| Segurança | Ver §7 |
| Desempenho | Uma busca vetorial de Problemas por plano; a fila deixa de crescer com relacionados |
| Testes | Unitários com índice em memória |

## 7. Segurança
- **Texto vindo de outros projetos:** a semelhança, o limite e a lição são escritos pelo Curator de outro projeto. Entram só por `wrap_data`, com teto, e nunca como instrução.
- **Visibilidade:** a regra atual continua valendo. Registros privados de outro projeto não entram.
- **Egresso:** o bloco segue para o provedor como qualquer contexto do plano, e o registro de egresso o documenta.

## 8. Questões em aberto
1. Ativar `CROSS_PROJECT_CANDIDATES` só depois do E0, ou já no E2. Proposta: depois do E0.
