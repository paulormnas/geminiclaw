# ADR 019 — Localidade dos Dados de Pesquisa e Proveniência dos Resultados

**Status:** Aprovado em 2026-10-01 pelo pesquisador responsável — implementação pendente (spec por spec, nas mudanças `v18.5-*`)
**Data:** 2026-09-29
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** implementação depois da V18 (incluindo as mudanças em andamento dos ADRs 017 e 018) e **antes da V19** (`roadmaps/roadmap_V19.md`); é também pré-requisito da federação (V20, ADR 013)
**ADRs relacionados:** ADR 009 e 015 (conhecimento), ADR 010 (propósito), ADR 011 (embeddings locais), ADR 012 (Curator), ADR 013 (federação), ADR 014 (sandbox), ADR 017 (catálogo e roteador), ADR 018 (imagem do sandbox)

---

## Contexto

O assistente formula hipóteses, gera código, executa experimentos e relata resultados (ADR 010).
Para que um laboratório confie nele, duas perguntas precisam ter resposta verificável, e não
apenas declarada:

1. **Que dados de pesquisa saíram do computador do laboratório, e para onde?**
2. **De onde veio cada número do relatório?**

Hoje nenhuma das duas tem essa resposta:

- **Dados brutos no prompt.** `ContextBundle.to_prompt_context()` (`src/context_loader.py`)
  injeta as 5 primeiras linhas de cada dataset de `input_context/` e estatísticas por coluna,
  inclusive mínimo e máximo, que são valores de registros. Imagens são descritas pelo Gemini
  Vision por chamada direta, fora da camada de provedores.
- **Saída do sandbox sem filtro.** A skill de código (`src/skills/code/skill.py`) devolve ao
  LLM o `stdout` completo, o `stderr` e a mensagem de erro. Um `print(df)` ou uma exceção como
  `could not convert string to float: '12,5'` envia dados ao provedor.
- **Sandbox com rede durante a execução.** `PythonSandbox` só desativa a rede quando não há
  comandos de instalação (`network_disabled=not bool(setup_commands)`). Com pacotes a instalar,
  o script roda com internet e com os dados.
- **A política atual decide para onde, não o quê.** `LLM_DATA_POLICY` (ADR 017) escolhe entre
  modelos `self_hosted` e `third_party`, mas não restringe o conteúdo enviado. Consultas de
  busca técnica também saem sem registro.
- **Números copiados pelo LLM.** O Summarizer escreve o relatório a partir dos `metrics.json`
  e é instruído a calcular divergências percentuais no texto. Nada confirma que o número
  impresso é o número medido.
- **Proveniência sem evidência de adulteração.** Existem `manifest.json`, `params.json`,
  `metrics.json` e os hashes do nó `Experimento` (ADR 015), mas nenhum registro encadeado
  permite detectar alteração posterior.
- **Versão do modelo não registrada.** O ADR 017 registra `provedor/modelo`, não a versão
  efetivamente servida.

O projeto já decidiu partes do caminho: código gerado roda em sandbox (ADR 014), embeddings
são locais (ADR 011) e conclusões exigem evidência em disco (ADR 009). Este ADR transforma esses
pontos em **garantias explícitas, com limites declarados**, e fecha as brechas acima.

---

## Decisão

### 1. Alocação das funções: o código vai aos dados

O sistema é descrito em quatro funções: **observação** (entrada de dados, documentos e
instruções), **raciocínio** (inferência dos modelos), **execução** (código e ferramentas) e
**memória** (bancos, artefatos e registros). O **nó de referência** é o computador onde residem
o estado da pesquisa e os dados.

- **Execução e memória nunca saem do nó de referência.** Código gerado roda no sandbox local
  (ADR 014); bancos, artefatos e registros ficam no nó.
- **Apenas o raciocínio pode ser remoto**, e só recebe o que o §3 permite.
- Execução de código em serviços do provedor (interpretadores remotos das APIs) não é usada.

A localidade de cada modelo é **declarada no catálogo** (ADR 017), como já ocorre com `trust`:

- `localidade`: `no_no` (roda no nó de referência) ou `fora_do_no` (padrão).
- `aceita_dados_brutos`: `false` por padrão; só pode ser `true` em entradas `self_hosted`
  (ex.: servidor de GPU da própria instituição). Entradas `no_no` são tratadas como `true`.

Uma declaração `no_no` com endpoint fora de loopback, ou o contrário, gera `WARNING` na
inicialização. A declaração não é inferida da URL, porque um endpoint em loopback pode ser um
túnel ou proxy para terceiros.

Cada sessão registra seu **perfil de alocação**: para cada papel, `provedor/modelo`, `trust`,
`localidade` e `aceita_dados_brutos`, **como declarados**. O perfil aparece no banner, no
registro da sessão e no relatório final.

### 2. Todo número é rastreável até uma origem

Todo valor quantitativo de um artefato entregue (relatório, nós `Resultado` e vereditos do
grafo, conclusões de hipóteses) deve ter uma destas origens, exibida junto ao valor:

- **Execução registrada** (§4): o valor vem do registro da execução que o produziu.
- **Cálculo determinístico** sobre valores registrados: diferenças, razões, percentuais e
  intervalos são **expressões** avaliadas pelo orquestrador, nunca pelo modelo.
- **Fonte citada**: valor vindo de um `Insumo` fornecido pelo pesquisador ou de uma página da
  busca técnica, com referência e trecho de origem.

Para isso, o LLM **não escreve números medidos nem calculados**: escreve **referências**
(ex.: `{{res:<id>}}`) e **expressões** (ex.: `{{calc:(res:a - res:b) / res:b}}`), que o
orquestrador renderiza com valor, unidade e origem. A sintaxe fica para a spec.

Um verificador determinístico percorre o texto final, incluindo números por extenso e
multiplicadores ("três vezes", "3x"). Números sem origem **não são apagados nem corrigidos**:
são marcados visivelmente como "não verificado" no relatório e contados nas métricas (§8).
Números estruturais (anos, numeração de seções, contagens vindas do orquestrador) ficam de fora
por regra explícita da spec.

**Limite declarado:** o `metrics.json` é escrito por código gerado pelo modelo. O §2 garante
que cada número é rastreável até uma execução com código e entradas registrados, não que a
métrica foi calculada corretamente. Uma verificação estática sinaliza no relatório métricas
gravadas como literais no código (ex.: `metrics = {"acc": 0.95}`).

### 3. Dados brutos de pesquisa não saem do nó

**Dados de pesquisa** são os datasets e imagens de `input_context/`, os arquivos de dados
produzidos pelas execuções e qualquer outro arquivo que o pesquisador marcar como tal (ex.: PDF
ou caderno de laboratório com tabelas de medição). Os demais documentos textuais (artigos,
protocolos) seguem a `LLM_DATA_POLICY` do ADR 017, como hoje.

1. **O que pode ir a um modelo sem `aceita_dados_brutos`:** esquemas (colunas, tipos, unidades),
   metadados (tamanho, origem, formato), descritores de formato sem valores (ex.: "decimal com
   vírgula, separador `;`, codificação latin-1") e estatísticas agregadas (média, desvio,
   contagens) sobre grupos com pelo menos **k** registros (`LOCALITY_MIN_GROUP_SIZE`,
   configurável e registrado na sessão; o valor padrão fica em aberto e será definido na
   spec). Abaixo de k, vão só contagem e tipo. **Mínimo, máximo e quantis são valores de
   registros**: nunca vão exatos, em qualquer tamanho de grupo; no máximo como faixa
   arredondada. **Linhas, registros e pixels brutos, não.**
2. **Modelo com `aceita_dados_brutos`** (no nó ou servidor próprio declarado) pode receber
   amostras e saídas integrais.
3. **Exceção por arquivo:** o pesquisador pode marcar arquivos específicos como compartilháveis
   (ex.: dataset público). A marcação é registrada na sessão e no relatório.
4. **Saída do sandbox:** antes de voltar a um modelo sem `aceita_dados_brutos`, `stdout`,
   `stderr`, mensagens de erro e nomes de artefatos passam por um **filtro de egresso**:
   - tracebacks mantêm tipo da exceção, arquivo, linha e a forma da mensagem, com literais
     substituídos por marcadores tipados (ex.: `<str len=4 padrão=dd,d>`), preservando o
     sinal de depuração;
   - despejos tabulares são retidos e trocados por um resumo e um aviso de retenção, e as
     estatísticas impressas seguem a mesma regra do item 1 (tamanho mínimo de grupo, extremos
     não exatos), na medida em que o filtro as reconheça;
   - saídas não tabulares acima de um limite configurável (ex.: log de treino por época) vão
     com início e fim e um marcador de trecho omitido, preservando a tendência;
   - a saída integral fica no nó.

   O Developer é instruído a imprimir agregados, não dados (prompts da spec
   `v16-research-assistant-prompts`).
5. **Ponto único de saída:** toda comunicação externa passa por uma camada comum que aplica as
   regras acima e grava o **registro de egresso** (§8). Isso vale para chamadas de LLM e
   também para visão e consultas de busca técnica. Cada trecho injetado no prompt carrega sua
   origem (instrução, documento, esquema/agregado, código, saída de execução, grafo), para que
   o registro diga o que foi enviado, e não só quanto. Visão sobre dados de pesquisa usa modelo
   com `aceita_dados_brutos` ou arquivo marcado como compartilhável.
6. **Leitura no host:** ferramentas do host não leem conteúdo de dados de pesquisa para prompts.
   Só a camada de ingestão pode fazê-lo, e sob as regras acima. É uma restrição nova sobre o
   ADR 014 §3, que hoje permite ler qualquer arquivo do diretório da sessão.
7. **Volume acumulado:** o egresso de saídas de execução por sessão tem limite configurável.
   Atingido o limite, a execução para de forma graciosa, como os demais limites de uso da V18,
   e a pesquisa pode ser retomada. O pesquisador pode desligar o limite pelo modo sem limite
   (§11).
8. **Contaminação entre papéis:** o que um modelo com `aceita_dados_brutos` produz (código,
   comentários, respostas, contexto persistido da sessão) é tratado como **dado de pesquisa**.
   A camada de saída reaplica as regras deste parágrafo sobre o prompt inteiro, inclusive o
   histórico, a cada envio e para cada destino. Em texto livre contaminado, números literais
   que não vêm de referência ou expressão (§2) são trocados por marcadores tipados antes de
   ir a um modelo sem `aceita_dados_brutos`. Isso vale também na retomada de uma sessão
   com outro catálogo. Um perfil de alocação que mistura papéis com e sem
   `aceita_dados_brutos` gera aviso no banner, porque nele a filtragem entre papéis é
   frequente.

**Limite declarado:** com um modelo de raciocínio sem `aceita_dados_brutos`, o §3 **reduz e
registra** o egresso, mas não o impede de forma absoluta. Um modelo induzido por injeção pode
tentar extrair valores aos poucos, e os filtros dos itens 4 e 8 são heurísticos. A prevenção é por camadas (ingestão restrita, filtro,
sandbox sem rede, limite de volume) e a auditoria é completa. Prevenção total só existe com
raciocínio em modelo `no_no`.

### 4. Registro de execuções encadeado por hash

Cada execução no sandbox, inclusive as que falham ou estouram o tempo, gera registros
**somente-acréscimo**:

- **Registro de início**, gravado antes de a execução começar.
- **Registro de término** com, no mínimo: projeto, sessão, subtarefa, hash do código, hash de
  `params.json`, semente, hashes dos arquivos de entrada e de saída, digest da imagem do
  sandbox, pacotes instalados com versões, ativos baixados (§5), código de saída, instantes de
  início e fim, e o **hash do registro anterior**.

Regras da cadeia:

- A cadeia é **por projeto** e continua entre execuções retomadas. A ponta da cadeia entra no
  `checkpoint.json` da V18.
- **Acréscimo serializado** por projeto (ex.: *advisory lock* do PostgreSQL), porque subtarefas
  do DAG rodam em paralelo e mais de uma sessão pode usar o mesmo projeto.
- **Verificação** por um comando (ex.: `geminiclaw provenance verify <projeto>`), que recalcula
  a cadeia, confere os arquivos em disco e lista execuções órfãs (início sem término, como
  depois de uma queda).
- Os campos `hash_codigo`, `hash_params`, `seed` e `ambiente` do `Experimento` (ADR 015)
  passam a ser **derivados** do registro de execução, e `Experimento` e `Resultado` apontam
  para ele.
- Os hashes de arquivos grandes usam cache por tamanho e data de modificação, para não
  sobrecarregar o armazenamento do Pi 5.

**Limite declarado:** no próprio nó, a cadeia detecta edições acidentais ou parciais. Contra
quem controla o banco **e** o disco, a garantia exige a ponta ancorada **fora do nó**. O
relatório final e a exportação da sessão trazem a ponta, e a assinatura com a chave do nó
virá com a federação (ADR 013 §2), sobre esta mesma cadeia.

O registro fica no PostgreSQL, com exportação para o diretório da sessão no encerramento. A
tabela nova é mudança de schema e exige aprovação explícita na spec (AGENTS.md).

Falhas de gravação seguem o princípio *fail-fast*. Sem registro de início, a execução não
começa. Se o registro de término falhar, ele fica guardado no diretório da sessão e é
acrescentado na próxima gravação possível; o `verify` informa a pendência.

### 5. Sandbox: fases separadas de rede e dados

1. **Instalação:** com rede, **sem** dados montados. Falha de instalação falha a execução; não
   é apenas registrada em log.
2. **Busca de ativos:** com rede, **sem** dados montados. Pesos pré-treinados, corpora e
   datasets públicos declarados são baixados aqui, e URL e hash de cada ativo entram no
   registro (§4).
3. **Execução:** **sem rede**. Os dados de pesquisa entram por cópia (`put_archive`) ou por
   montagem somente leitura, e o diretório de saída é gravável. Um download não declarado
   que falhe nesta fase gera erro acionável ("declare o ativo na fase de busca"), não um erro
   de rede genérico.

Nenhum script com acesso a dados de pesquisa roda com rede. A única exceção é a execução em
que todas as entradas montadas estão marcadas como compartilháveis (§3.3). Isso decide a
política de rede que o ADR 014 §5 deixou para a spec e restringe a ideia de acesso à internet
registrada no ADR 018 §2.

### 6. Verificação das conclusões por afirmações

O Validator passa a verificar também as conclusões, e não só os planos. Cada conclusão é
decomposta em afirmações atômicas, conferidas contra a evidência registrada (registros de
execução, `metrics.json`, insumos). Cada afirmação recebe um status:

O status é um atributo novo da afirmação (`status_afirmacao`). **Não** substitui nem
redefine o `validation` do ADR 015 e da `v17-evidence-verdict`, que continua descrevendo o
cumprimento do contrato do experimento. Efeitos:

| Status da afirmação | Efeito |
|---|---|
| suportada | Entra no relatório como conclusão. |
| parcialmente suportada | Entra no relatório como achado parcial, com a parte não suportada indicada. A evidência do grafo não muda. |
| refutada por comparação determinística | A direção da evidência segue os valores registrados, não o texto da afirmação. |
| refutada apenas pelo modelo verificador | Marcada como **contestada** para revisão do pesquisador. A direção da evidência não muda por julgamento de LLM. |
| não verificável | Sem efeito no veredito (equivale a `nao_validado`, q = 0). Aparece no relatório com o status. |
| pendente (orçamento esgotado) | Sem efeito no veredito. É verificada na retomada (V18), sem penalizar a hipótese (ADR 015 §9.3). |

- **Todo `Resultado` com registro de execução entra no grafo.** O status da afirmação não é
  filtro de admissão. Resultados negativos e inconclusivos continuam sendo conhecimento de
  primeira classe (ADR 009).
- O relatório apresenta **todas** as afirmações, cada uma com seu status.
- Afirmações que só comparam referências (§2) são conferidas de forma determinística, sem LLM.
  As demais são verificadas em lote por conclusão.
- As chamadas contam no orçamento da V18. Esgotar o orçamento não bloqueia a sessão.

**Diversidade de modelo:** o catálogo ganha o campo `familia_modelo`. Ele serve como
**critério de desempate**: entre modelos de mesma posição de preferência para o Validator,
escolhe-se o de família diferente da do autor da afirmação, para reduzir erros correlacionados.
Um modelo de outra família, mas de preferência inferior, não substitui o preferido. A escolha
é registrada. *(Atualização 2026-10-01: o Validator deixou de exigir `trust: self_hosted`, ADR 017
§2; a família diferente continua como desempate, e o que o verificador recebe passa pela camada
de saída do §3, como para qualquer destino.)*

### 7. Versão efetiva do modelo

Cada chamada registra, além de `provedor/modelo`, a **versão efetivamente servida**. A fonte é
definida por provedor na spec (ex.: identificador retornado pela API, digest obtido do Ollama
no início da sessão). Quando o provedor não informa, o registro diz explicitamente
"desconhecida".

A garantia é "registrada como informada", não "imutável": a Anthropic pode devolver em
`response.model` o próprio alias pedido (e não um identificador datado), e outros provedores
podem informar só um alias estável. Nesses casos uma troca silenciosa por trás do alias não é
detectável pela versão registrada.

Uma mudança de versão dentro da sessão gera evento e aviso no relatório. Com
`LLM_ROUTING=strict` (ADR 017 §7), versão desconhecida ou alterada encerra a execução **no
próximo checkpoint** (V18), com retomada possível, sem perder o trabalho feito.

### 8. Métricas de operação registradas por sessão

Cada sessão registra:

- **Egresso:** volume por provedor, `trust`, `localidade` e categoria de conteúdo (§3.5);
  intervenções do filtro de saída; e consultas de busca e de visão.
- **Proveniência:** números por origem (execução, cálculo, fonte citada) e não verificados
  (§2); métricas literais no código; resultado da verificação da cadeia (§4).
- **Verificação:** afirmações por status (§6) e ciclos de correção até a aprovação.
- **Custo e recursos:** tokens e custo por tarefa, e uso de CPU, RAM e temperatura do nó (já
  coletado pela telemetria).
- **Intervenções humanas:** aprovações, rejeições e edições feitas pelo pesquisador.

### 9. Conteúdo observado é dado, nunca instrução

Documentos, resultados de busca técnica, saídas de execução, conteúdo do grafo e, no futuro,
registros de outros nós são entregues aos agentes delimitados e identificados como **dado**.
Instruções contidas neles não são seguidas. Isso generaliza o ADR 013 §5 para toda entrada. A
defesa efetiva contra extração induzida está nas camadas do §3 e no §5, não apenas no prompt.

### 10. Atuação sobre instrumentos

A Spec G7 (V19.1) já prevê escrita em equipamentos (`equipment_write`) sob lista de permissão e
limites de segurança. Este ADR acrescenta duas regras:

- ferramentas de instrumento são **somente leitura por padrão**;
- todo comando que altere o estado de um instrumento exige **confirmação do pesquisador em
  qualquer `SessionMode`**, além da lista de permissão e dos limites da G7.

Nenhuma ferramenta desse tipo está implementada hoje.

### 11. Limites de uso respeitados, com modo sem limite explícito

Os limites de uso (V18: tokens, tempo, retentativas) e o limite de volume de egresso (§3.7)
existem para que a pesquisa não gere custos além do planejado. Por padrão, **todos são
condições de parada**.

O pesquisador pode optar pelo **modo sem limite**, para que o sistema continue até encontrar um
resultado:

- A opção é **explícita** por sessão ou projeto e exige confirmação no início da execução.
  Nunca é ativada por padrão nem por decisão de um agente.
- Ela remove os limites de **tokens, tempo, custo e volume de egresso**. Os limites de
  retentativas da mesma tarefa e de conexão continuam valendo, porque protegem contra laços
  de falha, não contra custo.
- A execução continua parando quando uma solução é encontrada ou quando não há mais caminhos
  promissores (critérios de parada da V18), e o pesquisador pode interrompê-la a qualquer
  momento sem perder o avanço.
- O modo aparece no banner, no registro da sessão e no relatório. Tokens, custo e egresso
  continuam registrados (§8), e o pesquisador é avisado periodicamente do consumo acumulado.
- As regras de localidade (§3) **não** são afetadas: o modo sem limite remove limites de
  quantidade, nunca as restrições sobre o que pode sair do nó.

---

## Impacto em ADRs e specs anteriores

As ADRs anteriores **não são alteradas agora**. Quando este ADR for implementado, recebem os
ajustes abaixo:

| ADR / spec | Ajuste |
|---|---|
| ADR 015, `v17-graph-store`, `v17-evidence-verdict` | `Experimento` e `Resultado` apontam para o registro de execução, e os hashes do `Experimento` passam a ser derivados dele (§4). Novo atributo `status_afirmacao`, sem alterar os valores de `validation`; status "contestada" para revisão humana (§6). `Insumo` ganha referência ao trecho de origem de valores citados (§2). |
| `v17-structural-fact-ingestion` | Valores de `Resultado` vêm do registro de execução, não direto do `metrics.json`. |
| ADR 012, `v17-curator-agent` | O Curator cita valores por referência (§2). |
| ADR 010 item 4, Spec G2 | O contrato de reprodutibilidade passa a ser ancorado no registro encadeado (§4). |
| ADR 013 | Regra de publicação: dados brutos nunca são publicados, só registros, agregados e hashes. Assinatura sobre a cadeia do §4. Resolve parte da questão aberta de privacidade. |
| ADR 014 §2, §3 e §5, `v16-in-process-agents` (fase 2) | Nova restrição de leitura no host (§3.6); ponto único de saída com reaplicação por destino (§3.5, §3.8); filtro sobre a saída do sandbox (§3.4); política de rede do sandbox decidida (§5); dados por `put_archive` ou montagem somente leitura (§5, ver também ADR 018 §3). |
| ADR 017 §1, §5, §9 e §10, `v16-provider-registry` | Campos `localidade`, `aceita_dados_brutos` e `familia_modelo` no catálogo. `familia_modelo` só orienta preferência, o que é um novo tipo de campo. O roteador resolve o Validator depois de Researcher e Developer. Versão efetiva e perfil de alocação no banner, nos logs e na telemetria. |
| ADR 018 §2 | Instalação e busca de ativos com rede e execução sem rede, em fases separadas (§5). |
| `v16-research-assistant-prompts` | Developer imprime agregados; Summarizer e Curator escrevem referências e expressões (§2, §3.4). |
| Spec G9 (`input_context/`) | Fim das amostras de linhas e de mínimo/máximo para modelos sem `aceita_dados_brutos`; tamanho mínimo de grupo; marcação de arquivos como compartilháveis ou como dados de pesquisa; visão passa pela camada de saída (§3). |
| Spec G8 (relatório) | Renderização por referências e expressões; marcação de números não verificados; afirmações com status; ponta da cadeia e perfil de alocação no relatório. |
| Spec G5 | Limite de volume de egresso como condição de parada, ao lado dos demais limites (§3.7). |
| Spec G7 (V19.1), `roadmap_V19.md` | Somente leitura por padrão e confirmação humana para escrita em qualquer modo (§10), na revisão da G7 já prevista no roadmap. |
| `v18-usage-limits` | Chamadas de verificação e métricas de custo no orçamento (§6, §8); limite de egresso como condição de parada (§3.7); modo sem limite explícito, já que hoje `UsageBudget` exige todos os limites positivos (§11). |
| `v18-research-continuity` | Ponta da cadeia e registros de término pendentes no `checkpoint.json` (§4); verificações pendentes retomadas (§6); marca de contaminação preservada no contexto retomado (§3.8); encerramento no checkpoint em modo `strict` (§7). |

---

### Mapa de implementação (2026-10-01)

| Seção do ADR | Mudança OpenSpec |
|---|---|
| §1 (alocação das funções), §7 (versão efetiva), `familia_modelo` do §6 | `v18.5-model-catalog-locality` (depende do catálogo do ADR 017, ainda sem spec própria) |
| §2 (números rastreáveis) | `v18.5-numeric-references` |
| §3.1 a §3.3 (dados de pesquisa no contexto) | `v18.5-research-data-ingestion` |
| §3.4 a §3.8 e §9 (saída única, filtro, conteúdo como dado) | `v18.5-egress-gate` |
| §4 (registro encadeado por hash) | `v18.5-execution-provenance` |
| §5 (sandbox por fases) | `v18.5-sandbox-phases` |
| §6 (verificação por afirmações) | `v18.5-claim-verification` |
| §8 e §11 (métricas e modo sem limite) | `v18.5-operation-metrics` |
| §10 (atuação sobre instrumentos) | Sem spec: entra na revisão da Spec G7 (V19) |

---

## Alternativas Consideradas

### Alternativa A: Confiar apenas na política de provedor (`LLM_DATA_POLICY`)

**Descartado porque:** decide para onde os dados vão, não quais dados vão. O prompt atual já
envia linhas brutas a qualquer modelo permitido, sem registro.

### Alternativa B: Anonimizar ou pseudonimizar os dados antes de enviar

**Descartado porque:** em dados de medição, os próprios valores são a informação sensível.
Mascarar identificadores não os protege, e mascarar valores inutiliza a amostra.

### Alternativa C: Usar apenas modelos no próprio nó

**Descartado como regra única porque:** os modelos que cabem num Raspberry Pi 5 limitam a
qualidade do planejamento e do código. Continua sendo a configuração de maior proteção, e o
§3.2 a favorece.

### Alternativa D: Proibir amostras para qualquer modelo fora do nó, inclusive os da instituição

**Descartado porque:** um servidor de GPU da própria instituição reúne modelo forte e custódia
dos dados. Proibi-lo força o Developer a adivinhar formatos com um modelo mais fraco.
`aceita_dados_brutos` torna a decisão explícita, desligada por padrão e registrada.

### Alternativa E: Deduzir a localidade pela URL do endpoint

**Descartado porque:** loopback pode ser túnel ou proxy para terceiros, e em Docker um modelo
local nem sempre está em loopback. A declaração no catálogo segue o critério do ADR 017 para
`trust`.

### Alternativa F: Verificar os números só por comparação textual no relatório final

**Descartado porque:** casar números do texto com os de `metrics.json` falha com arredondamento,
unidades e valores derivados, e não diz de onde veio o número. Referências e expressões
renderizadas pelo orquestrador tornam a origem parte do artefato.

### Alternativa G: Admitir no grafo apenas afirmações suportadas

**Descartado porque:** enviesaria o veredito do ADR 015 a favor do apoio, ao descartar
resultados negativos e inconclusivos, que o ADR 009 trata como conhecimento de primeira classe.

### Alternativa G2: Exigir o mesmo `aceita_dados_brutos` em todos os papéis da sessão

**Descartado porque:** impediria combinações úteis, como um Developer num servidor próprio com
acesso aos dados e um planejador remoto mais forte. A marca de contaminação (§3.8) mantém a
garantia e permite a combinação, ao custo de mais filtragem entre papéis.

### Alternativa H: Proveniência apenas nos arquivos da sessão, sem encadeamento

**Descartado porque:** os arquivos podem ser editados sem deixar rastro. O encadeamento torna a
adulteração detectável a baixo custo e prepara a assinatura.

### Alternativa I: Assinar cada registro com a chave do nó desde já

**Adiado:** exige gestão de chaves, que só se justifica com a federação (ADR 013). A cadeia é
compatível com a assinatura posterior.

---

## Consequências

### Positivas

- Duas garantias auditáveis para o pesquisador: **o que saiu do nó, e para onde**, e **de onde
  veio cada número**, com registro e comando de verificação.
- Fecha brechas concretas: amostras e extremos no prompt, saída do sandbox sem filtro, visão e
  busca fora da camada de provedores, e sandbox com rede durante a execução.
- Reprodutibilidade mais precisa: versão efetiva do modelo, imagem, pacotes, ativos e hashes de
  entrada e saída.
- Resultados negativos e inconclusivos continuam no grafo, agora com o status da verificação.
- A federação (ADR 013) ganha uma base segura de publicação e assinatura.
- As métricas do §8 permitem medir o custo real de cada configuração de provedores.

### Negativas / Trade-offs

- **Menos contexto para modelos sem `aceita_dados_brutos`:** o código de leitura pode exigir
  mais tentativas. Descritores de formato, tracebacks com marcadores tipados e a opção
  `aceita_dados_brutos` reduzem o efeito, mas não o eliminam.
- **Filtro de saída heurístico:** pode reter saídas legítimas ou deixar passar dados em formato
  incomum. As intervenções e o volume ficam visíveis nas métricas.
- **Mais ciclos de container** quando há pacotes ou ativos a baixar. Um cache de pacotes, ainda
  em aberto no ADR 018, atenuaria.
- **Mudança de schema no PostgreSQL** para o registro de execuções, que exige aprovação.
- **Contrato novo para Summarizer e Curator** (referências e expressões); prompts e testes
  precisam ser revistos.
- **Validator com papel ampliado:** a verificação de conclusões é capacidade nova e consome
  orçamento.
- **Três campos novos no catálogo**, dois deles declarativos, que dependem de o operador
  declará-los corretamente.

---

## Revisão

Reabrir quando:

- modelos que rodam no nó atingirem qualidade suficiente para dispensar o raciocínio remoto;
- as métricas do §8 mostrarem retenção frequente de saídas legítimas pelo filtro, ou muitos
  números não verificados em relatórios corretos;
- a spec da federação (ADR 013) começar, para incorporar a assinatura e a ancoragem externa da
  cadeia;
- a Spec G7 for implementada, para confirmar o §10 na prática.
