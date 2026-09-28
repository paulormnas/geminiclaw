# ADR 013 — Federação: Rede Pública de Conhecimento entre Nós (Princípios)

**Status:** Proposto — princípios apenas; tecnologia a definir
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**ADRs relacionados:** ADR 004 (IPC local), ADR 009 (conhecimento), ADR 010 (propósito), ADR 011 (embeddings)

---

## Contexto

O pesquisador responsável deseja que nós do GeminiClaw (Raspberry Pis ou outros computadores)
correlacionem ideias entre projetos diferentes, encontrem sinergias e explorem hipóteses em
conjunto, para avançar a pesquisa científica.

Os nós **não estarão na mesma instituição**, o que torna inviável qualquer configuração
manual entre eles. Hoje o sistema é estritamente local: o IPC usa Unix sockets sem
autenticação (ADR 004) e não existe nenhum mecanismo de rede, descoberta ou sincronização.

Esta é a funcionalidade mais complexa do roadmap e será a **última** a ser implementada,
depois que todas as funcionalidades de pesquisa estiverem completas e validadas (ADR 010).
Este ADR registra apenas os princípios, para que as camadas anteriores já sejam construídas
de forma compatível.

---

## Decisão (princípios)

### 1. Plug-and-play

Um novo nó deve entrar na rede sem configuração manual: **conectar-se à internet, validar-se
junto a um servidor e começar a sincronizar** com os demais nós. O servidor serve para
entrada e descoberta de pares; ele não é a fonte da verdade do conhecimento.

### 2. Rede pública, inspirada em blockchains

- **Participação aberta:** qualquer novo nó pode se conectar.
- **Identidade criptográfica:** cada nó tem um par de chaves e assina tudo o que publica —
  cada descoberta tem autoria verificável, funcionando também como crédito científico.
- **Histórico somente-acréscimo:** registros publicados não são reescritos; correções são
  novos registros assinados.
- **Validação mútua:** os nós validam o trabalho uns dos outros.

### 3. Validação por reprodução

Em vez de mecanismos de consenso computacionalmente caros (prova de trabalho ou de
participação, inviáveis no Pi 5), a validação entre nós deve se basear em **reprodução
científica**: nós reexecutam experimentos publicados por outros — o que os contratos de
reprodutibilidade da Spec G2 (`params.json`, seed, `metrics.json`) tornam possível — e
publicam confirmações ou refutações assinadas. A confiança em uma descoberta cresce com
reproduções independentes, e a reputação de um nó cresce quando suas descobertas se
sustentam.

### 4. Oportunidades de pesquisa: documentar, e o humano decide

Cada nó publica descobertas e **oportunidades de pesquisa** (hipóteses abertas, possíveis
transferências entre problemas). Essas oportunidades podem ter valor para áreas muito
diferentes da que as gerou: pesquisas de um instituto de química podem abrir oportunidades
para um instituto de história — e o instituto de química pode não ter interesse em investir
recursos e esforço para desenvolvê-las.

Por isso:

- **Um nó nunca inicia pesquisas por conta própria** a partir de oportunidades vindas da
  rede, nem de oportunidades que ele mesmo publicou para outras áreas.
- O nó **documenta a oportunidade** — o que foi observado, a evidência de origem e por que
  pode ser relevante — e a apresenta ao **pesquisador responsável, que decide** se ela será
  investigada.
- Se decidir prosseguir, a nova pesquisa segue o fluxo normal (insumos, limites de uso,
  `SessionMode`) e fica ligada ao registro de origem.

O mesmo vale para a validação por reprodução (§3): reproduzir experimentos de outros nós
consome recursos e só ocorre com a decisão do pesquisador responsável.

### 5. Conhecimento remoto é sempre dado não confiável

Nada vindo de outro nó é tratado como instrução para os agentes — apenas como dado a ser
avaliado. Isso é essencial numa rede aberta, sujeita a nós maliciosos e injeção de prompt.

### 6. Requisitos para as camadas anteriores (desde já)

Mesmo sem implementar a federação agora, as camadas anteriores devem prever:

- **Identificadores estáveis** para cada registro de conhecimento (ex.: baseados em conteúdo).
- **Proveniência obrigatória** (já exigida pelo ADR 009).
- **Embeddings versionados**, com texto de origem preservado (ADR 011). Vetores não são
  compartilhados: cada nó gera os seus localmente a partir dos registros recebidos.
- **Separação entre conhecimento privado e compartilhável.**

---

## Questões em Aberto (a discutir antes da spec)

- **Privacidade e propriedade intelectual:** o que é publicado (resumos, código, dados)? O
  compartilhamento é opcional por projeto e desativado por padrão? Há restrições para dados
  sensíveis (ex.: médicos)?
- **Nós maliciosos:** como mitigar descobertas falsas, spam e ataques Sybil numa rede aberta?
- **Custo computacional:** quanto de seu hardware cada nó aceita dedicar, quando o
  pesquisador responsável decide reproduzir experimentos ou explorar oportunidades de outros?
- **Descoberta de oportunidades:** como apresentar ao pesquisador responsável as
  oportunidades relevantes para a sua área, sem sobrecarregá-lo?
- **Governança:** quem opera os servidores de entrada? Quem define e evolui o formato dos
  registros?
- **Variação de hardware:** qual tolerância define que um resultado foi "reproduzido" entre um
  Pi e uma estação com GPU?
- **Tecnologia:** protocolos de rede, descoberta e sincronização (ex.: modelos como Git, IPFS,
  Nostr ou libp2p).

---

## Alternativas Consideradas

### Alternativa A: Pares configurados manualmente

**Descartado porque:** nós em instituições diferentes tornariam a configuração inviável; não é
plug-and-play.

### Alternativa B: Servidor central como fonte da verdade

**Descartado porque:** cria um ponto único de falha e de controle, contrário a uma rede
pública e aberta.

### Alternativa C: Blockchain com consenso global (prova de trabalho / participação)

**Descartado porque:** o consenso global sobre um único estado é caro e desnecessário —
compartilhar conhecimento não exige que todos concordem sobre uma ordem única de registros,
apenas que registros assinados se propaguem e se acumulem.

---

## Consequências

### Positivas

- Pesquisas em instituições diferentes podem se beneficiar umas das outras.
- Validação por reprodução alinha a rede com a prática científica de revisão por pares.
- Autoria assinada dá crédito verificável às descobertas.

### Negativas / Trade-offs

- **Maior superfície de ataque do projeto:** exigirá avaliação completa do Analista de
  Segurança (STRIDE) e testes do Pentester antes de qualquer implementação.
- **Complexidade alta:** rede, identidade, sincronização e reputação são sistemas inteiros.
- **Dependência de governança comunitária** para servidores de entrada e evolução do formato.

---

## Revisão

Este ADR deve ser revisado quando:
- Todas as funcionalidades de pesquisa (V16–V19) estiverem implementadas e validadas.
- As questões em aberto forem discutidas com o pesquisador responsável — nesse momento, a
  tecnologia será escolhida e este ADR detalhado ou substituído.
