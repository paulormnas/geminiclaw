# Design: v18.10-web-dashboard

## 1. Leitura só leitura (ADR 027 §6.4)

`src/web/deps.py` ganha `read_only_store()` (o `GraphStore` da fábrica envolto em `ReadOnlyGraphStore`) e `read_only_connection()` (conexão de `src/db.py` com `SET TRANSACTION READ ONLY` antes da primeira consulta). Todas as rotas desta mudança usam só essas duas dependências; um teste estático confere que `routes/dashboard.py` e `queries/dashboard.py` não importam `get_connection` nem a fábrica de escrita.

## 2. Contrato

`GET /api/projects/{id}/dashboard` → 200:

```json
{
  "projeto": {"projeto_id": "...", "titulo": "...", "status": "ativo"},
  "contagens": {
    "Hipotese": {"total": 12, "por_estado": {"proposta": 2, "em_teste": 1, "validada": 4, "refutada": 3, "inconclusiva": 1, "abandonada": 1}},
    "Experimento": {"total": 9, "por_estado": {"sucesso": 7, "falha": 2, "divergente_documentado": 0}},
    "Resultado": {"total": 85}, "RegistroResultado": {"total": 3}, "Abordagem": {"total": 10},
    "Descoberta": {"total": 2}, "Oportunidade": {"total": 1}, "Dominio": {"total": 6}
  },
  "sessoes": {"total": 4, "por_estado": {"completed": 3, "interrompida": 1},
              "recentes": [{"session_id": "...", "alias": "iris-01", "status": "completed", "modo": "auto",
                            "inicio": "...", "fim": "...", "motivo_parada": "solucao_encontrada",
                            "tokens": 123456, "custo_usd": 1.23, "ultimo_evento": "..."}]},
  "custo": {"tokens": 456789, "custo_usd": 4.56, "sem_custo_registrado": 0},
  "ultima_atividade": "2026-10-22T13:05:00Z"
}
```

`GET /api/dashboard` → os mesmos blocos somados para todos os projetos, mais `projetos: [{projeto_id, titulo, status, hipoteses, experimentos, resultados, ultima_atividade}]`.

- **Escopo por projeto:** nós ligados ao projeto pelo caminho do modelo (ADR 015): `Projeto-INVESTIGA->Problema`, `Sessao-PERTENCE_A->Projeto`, `Experimento-EXECUTADO_EM->Sessao`, e os demais pela propriedade `projeto_id` quando o rótulo a tem. A consulta Cypher de cada contagem fica em `queries/dashboard.py`, uma por rótulo, parametrizada só por `projeto_id`. O desenvolvedor confere os caminhos contra o grafo real antes de implementar (tarefa 0.1); onde o caminho não estiver claro, a tarefa volta ao Arquiteto.
- **Rótulos:** todos os de `src/knowledge/schema.py` (lidos dele, não de lista própria), em dois grupos na interface: principais (`Problema`, `Hipotese`, `Experimento`, `Resultado`, `RegistroResultado`, `Abordagem`, `Descoberta`, `Oportunidade`) e demais (`Dominio`, `Insumo`, `Restricao`, `Decisao` etc.). Uma mudança de esquema da trilha 1 aparece no painel sem código novo.
- **Estados** listados com todos os valores do `enum` do esquema, inclusive zero, para a interface não esconder estados vazios.
- **Custo:** soma de `token_usage` por `execution_id` das sessões do projeto; `estimated_cost_usd` nulo conta em `sem_custo_registrado` e nunca vira zero.
- **Rótulos inexistentes** (por exemplo, `RegistroResultado` num banco sem a V18.9): contagem 0 e `"rotulo_ausente": true`, sem erro.
- **Tempo:** `WEB_DASHBOARD_CACHE_SECONDS` (padrão 15) guarda a resposta por projeto em memória; `?atualizar=1` ignora o cache.

## 3. Frontend (Designer)

- Página `/p/:projetoId/painel` e `/painel` (global).
- Linha de cartões (Hipóteses, Experimentos, Resultados, Registros, Abordagens, Sessões, Custo) com número grande e rótulo; cada cartão leva à seção correspondente (o de Hipóteses leva ao grafo filtrado por `Hipotese`, quando `v18.10-web-graph` existir).
- Barras horizontais em SVG por estado (hipóteses e experimentos), com o valor escrito ao lado da barra e tabela equivalente oculta visualmente mas lida por leitor de tela.
- Tabela de sessões recentes (apelido, modo, estado com `StatusBadge`, início, duração, motivo de parada, tokens, custo).
- Custo em US$ com duas casas e "sem custo registrado em N chamadas" quando houver.
- No painel global, tabela de projetos ordenável por coluna.

## 4. Impacto nos 6 eixos

Orquestrador, agentes e sandbox: nenhum. Persistência: só leitura. Segurança: dados do grafo exibidos como texto (§5). Testes: unidade com `InMemoryGraphStore` populado e fixture relacional; integração com AGE real no banco de teste.

## 5. Segurança

- Só leitura por papel, transação e invólucro.
- Títulos e textos vindos do grafo podem ter sido escritos por LLM: exibidos como texto (React escapa), limitados a 300 caracteres na resposta, saneados por `sanitize_text` (sequências de controle).
- Consulta por projeto parametrizada; `projeto_id` validado por `validate_project_id` (400 se malformado).
- Custo de consulta: as contagens são agregadas no banco; cache curto evita repetir consultas pesadas no `geminiclaw_bench`.

## 6. Questões em aberto

Nenhuma (os rótulos vêm do esquema; revisão adversarial de 2026-10-24). A página mostra "atualizado há N s" junto do botão Atualizar.
