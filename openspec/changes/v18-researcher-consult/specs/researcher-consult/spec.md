# Delta: researcher-consult

## ADDED Requirements

### Requirement: Researcher responde nos modos autônomos
O sistema SHALL, nos modos `semi` e `auto`, encaminhar cada chamada de `ask_researcher` ao
Researcher consultor e devolver ao agente a resposta dele, e SHALL, no modo `assisted`,
manter a pergunta ao pesquisador humano (ADR 012 §8).

#### Scenario: Modo auto
- **GIVEN** uma sessão `auto` e o provedor do Researcher simulado respondendo `{"resposta": "Use stratify=y", "confianca": "alta", "fontes": [], "suposicoes": []}`
- **WHEN** o Developer chama `ask_researcher` com a pergunta "Devo estratificar o split?"
- **THEN** o Developer recebe um texto que começa com `[Resposta do Researcher (consultor), confiança alta]` e contém "Use stratify=y"
- **AND** nada é lido do terminal

#### Scenario: Modo assisted
- **GIVEN** uma sessão `assisted`
- **WHEN** um agente chama `ask_researcher`
- **THEN** a pergunta é exibida ao pesquisador, como na Spec G5, e o consultor não é chamado

#### Scenario: Consultor desligado
- **GIVEN** `RESEARCHER_CONSULT_ENABLED=false` numa sessão `semi`
- **WHEN** um agente chama `ask_researcher`
- **THEN** o agente recebe a suposição documentada atual e a interação tem `respondido_por="suposicao"` e `motivo_fallback="desligado"`

### Requirement: Ferramentas restritas do consultor
O consultor SHALL ter acesso somente a `quick_search` e `web_reader`, com no máximo
`RESEARCHER_CONSULT_MAX_SEARCHES` buscas e `RESEARCHER_CONSULT_MAX_READS` leituras por consulta,
e MUST NOT ter acesso a `ask_researcher`, ao sandbox de código, à escrita de arquivos ou à
escrita no grafo.

#### Scenario: Lista de ferramentas
- **WHEN** o consultor é montado
- **THEN** as ferramentas expostas ao modelo são exatamente `quick_search` e `web_reader`

#### Scenario: Excesso de buscas
- **GIVEN** `RESEARCHER_CONSULT_MAX_SEARCHES=3` e um modelo simulado que pede 5 buscas
- **WHEN** a consulta roda
- **THEN** só 3 buscas são executadas e as demais recebem erro de limite

#### Scenario: Web desligada
- **GIVEN** `RESEARCHER_CONSULT_WEB_ENABLED=false`
- **WHEN** o consultor é montado
- **THEN** nenhuma ferramenta é exposta e a resposta vem só do modelo

### Requirement: Guarda de consulta antes do buscador
O sistema SHALL verificar toda consulta e toda URL do consultor antes de saírem do nó e SHALL
recusar, sem enviar, as que contenham número com casas decimais, sequência de 4 ou mais dígitos
que não seja ano, nome de arquivo da sessão, mais de `RESEARCHER_CONSULT_QUERY_MAX_CHARS`
caracteres ou mais de 3 linhas, registrando o motivo (ADR 010 item 9, ADR 019 §3).

#### Scenario: Valor de medição
- **WHEN** o consultor pede a busca "acurácia 0,953 iris svm"
- **THEN** a busca não é enviada ao backend e a recusa tem motivo `numero_decimal`

#### Scenario: Nome de arquivo do projeto
- **GIVEN** `input_snapshot/` contém `medicoes_lote7.csv`
- **WHEN** o consultor pede a busca "medicoes_lote7 formato"
- **THEN** a busca é recusada com motivo `nome_de_arquivo`

#### Scenario: Ano permitido
- **WHEN** o consultor pede a busca "scikit-learn train_test_split stratify 2026"
- **THEN** a busca é enviada

#### Scenario: URL com dado
- **WHEN** o consultor pede `web_reader` para `https://exemplo.org/q?v=12.75`
- **THEN** a leitura é recusada com motivo `numero_decimal`

### Requirement: Decisões reservadas ao pesquisador
O consultor MUST NOT responder perguntas que peçam aprovar `Oportunidade`, confirmar
`Problema`, aprovar termo de vocabulário, autorizar escrita em instrumento ou ativar o modo sem
limite. O sistema SHALL registrar essas perguntas como `pendente_pesquisador` e informar ao
agente que a decisão é do pesquisador.

#### Scenario: Aprovação de oportunidade em modo auto
- **GIVEN** uma sessão `auto`
- **WHEN** um agente chama `ask_researcher` com `decisao_reservada="aprovar_oportunidade"`
- **THEN** o consultor não é chamado
- **AND** a interação tem `respondido_por="pendente_pesquisador"` e o agente recebe a mensagem de decisão reservada

#### Scenario: Classificação pelo consultor
- **GIVEN** o consultor simulado devolve `{"reservada": true}` para uma pergunta sem `decisao_reservada`
- **WHEN** a consulta termina
- **THEN** a interação é registrada como `pendente_pesquisador`

### Requirement: Registro auditável das consultas
O sistema SHALL registrar cada interação de `ask_researcher` em
`payload["researcher_interactions"]` com `respondido_por`, o agente e a subtarefa que
perguntaram, a pergunta, o motivo, a resposta, as fontes, as buscas realizadas, as recusas da
guarda, o modelo, os tokens, a duração e `motivo_fallback`, e SHALL emitir o evento de
telemetria `researcher_consult` (ADR 012 §8).

#### Scenario: Consulta com busca
- **GIVEN** uma consulta em que o consultor fez 2 buscas e leu 1 página
- **WHEN** a consulta termina
- **THEN** a interação registrada tem `respondido_por="researcher"`, 2 itens em `buscas_realizadas` e 1 em `leituras`
- **AND** um evento `researcher_consult` foi gravado sem o texto da página lida

#### Scenario: Pergunta repetida
- **GIVEN** uma pergunta já respondida pelo consultor nesta sessão
- **WHEN** uma pergunta com similaridade acima de `ASK_RESEARCHER_DEDUP_SIMILARITY` é feita
- **THEN** a resposta anterior é reutilizada e o consultor não é chamado

### Requirement: Consultas dentro dos limites de uso
O sistema SHALL contar os tokens do consultor no orçamento da sessão, SHALL limitar as
consultas a `RESEARCHER_CONSULT_MAX_PER_SESSION`, e SHALL voltar à suposição documentada, com
`motivo_fallback` registrado, quando o limite, o orçamento, o timeout ou um erro impedirem a
consulta (ADR 012 §5).

#### Scenario: Tokens contados
- **GIVEN** o consultor simulado consome 1200 tokens
- **WHEN** o `UsageTracker` é consultado depois da consulta
- **THEN** o total de tokens da sessão aumentou em 1200

#### Scenario: Limite por sessão
- **GIVEN** `RESEARCHER_CONSULT_MAX_PER_SESSION=1` e uma consulta já feita
- **WHEN** outro agente chama `ask_researcher` com uma pergunta diferente
- **THEN** o agente recebe a suposição documentada e a interação tem `motivo_fallback="limite_consultas"`

#### Scenario: Orçamento em fechamento
- **GIVEN** o `UsageTracker` indica fechamento por tokens
- **WHEN** um agente chama `ask_researcher`
- **THEN** o consultor não é chamado e `motivo_fallback="orcamento"`

#### Scenario: Timeout
- **GIVEN** `RESEARCHER_CONSULT_TIMEOUT_SECONDS=1` e um consultor simulado que demora 5 s
- **WHEN** a consulta roda
- **THEN** o agente recebe a suposição documentada e `motivo_fallback="timeout"`

## MODIFIED Requirements

### Requirement: ask_researcher não bloqueante em semi/auto (Spec G5)
Nos modos `semi` e `auto`, `ask_researcher` SHALL continuar sem bloquear à espera de um
humano, mas SHALL devolver a resposta do Researcher consultor quando ele estiver habilitado e
dentro dos limites; a suposição documentada passa a ser o comportamento de fallback, não o
padrão.

#### Scenario: Nenhuma leitura de terminal em semi
- **GIVEN** uma sessão `semi` com duas perguntas de agentes
- **WHEN** as duas perguntas são feitas
- **THEN** nenhuma leitura de `stdin` ocorre
- **AND** as duas interações têm `respondido_por` igual a `researcher` ou `suposicao`
