# Delta: knowledge-ingestion

## ADDED Requirements

### Requirement: Fatos escritos pelo orquestrador
O sistema SHALL registrar no grafo, sem uso de LLM, as sessões, insumos, experimentos,
resultados, abordagens aplicadas e suas relações, a partir dos artefatos e do resultado do
Validator.

#### Scenario: Subtarefa com métricas
- **GIVEN** uma subtarefa aprovada pelo Validator com `metrics.json` contendo `{"r2": 0.8}`, `baselines: {"r2": 0.7}` e `approach` "gradient boosting"
- **WHEN** a subtarefa é ingerida
- **THEN** existem `Experimento(status="sucesso")`, `Resultado(nome_original="r2", valor=0.8, baseline=0.7, status_validacao="validado")`
- **AND** as arestas `EXECUTADO_EM`, `PRODUZIU`, `MEDE` (para a métrica `r2`) e `APLICOU` (para a abordagem) existem

#### Scenario: Insumos do pesquisador
- **WHEN** o `input_snapshot/` contém `dados.csv` e `artigo.pdf`
- **THEN** existem `Insumo(tipo="dataset")` e `Insumo(tipo="artigo")` ligados ao projeto por `RECEBEU`

#### Scenario: Dataset usado
- **GIVEN** `params.json` com `datasets: ["dados.csv"]`
- **WHEN** o experimento é ingerido
- **THEN** existe `Experimento-USOU->Insumo` para `dados.csv` e `dataset_ids` contém o seu ID

#### Scenario: Fim de sessão
- **WHEN** a sessão termina por limite de tokens
- **THEN** a `Sessao` recebe `fim`, `motivo_parada="limite_tokens"` e `consumo`

### Requirement: Causa da falha classificada deterministicamente
O sistema SHALL classificar toda falha de experimento como `infraestrutura`, `abordagem` ou
`ambigua`, com assinatura, a partir de dados estruturados da execução.

#### Scenario: Exceção no código
- **WHEN** o código termina com `MemoryError` no sandbox
- **THEN** `causa_falha="abordagem"` e `assinatura_falha="MemoryError"`

#### Scenario: Sem métricas
- **WHEN** a execução termina sem `metrics.json`
- **THEN** `causa_falha="ambigua"` e `assinatura_falha="sem_metricas"`

#### Scenario: Provedor indisponível
- **WHEN** a subtarefa falha por erro de conexão com o provedor LLM após as retentativas
- **THEN** `causa_falha="infraestrutura"`

### Requirement: Configuração normalizada
O sistema SHALL registrar em `APLICOU.config` apenas os parâmetros que descrevem o método,
excluindo sementes, caminhos e identificadores de execução.

#### Scenario: Normalização
- **GIVEN** parâmetros `{"n_estimators": 200, "seed": 42, "data_path": "/x", "learning_rate": 0.1}`
- **WHEN** o experimento é ingerido
- **THEN** `config == {"learning_rate": 0.1, "n_estimators": 200}`

### Requirement: Ingestão idempotente
O sistema SHALL não duplicar nós ou arestas ao reingerir o mesmo evento.

#### Scenario: Reingestão
- **WHEN** a mesma subtarefa é ingerida duas vezes
- **THEN** existe um único `Experimento` com aquele `subtarefa_id`

### Requirement: Falha do grafo não interrompe a pesquisa
O sistema SHALL continuar a sessão quando o grafo estiver indisponível, guardando os eventos
para reenvio.

#### Scenario: Grafo indisponível
- **GIVEN** o banco do grafo fora do ar
- **WHEN** uma subtarefa termina
- **THEN** a sessão continua, o evento é gravado em `knowledge_pending.jsonl` e um aviso é registrado
- **AND** `geminiclaw knowledge sync` aplica o evento quando o banco volta

### Requirement: Contrato de artefatos retrocompatível
O sistema SHALL aceitar os novos campos `datasets` e `baselines` como opcionais.

#### Scenario: Artefatos antigos
- **WHEN** um `metrics.json` sem `datasets` nem `baselines` é ingerido
- **THEN** a ingestão conclui com `baseline` vazio e sem arestas `USOU`
