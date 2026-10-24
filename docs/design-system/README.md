# Design System — "Bancada"

**Status:** Proposto (2026-10-24) · **Dono:** Designer de Produto · **Origem:** ADR 027 §5
**Vale para:** todo código em `frontend/`. Os agentes desenvolvedores seguem este documento; valor visual fora dele exige atualizar este documento antes (regra do `designer.md`).

---

## 1. Conceito

A interface é uma **bancada de laboratório digital**: um instrumento de precisão, não um site de marketing. Três ideias guiam tudo:

1. **Evidência em primeiro plano.** Todo número mostra de onde veio (sessão, experimento, registro) com um toque. Nada de métricas soltas.
2. **Calma e densidade ao mesmo tempo.** Fundo escuro quase preto, superfícies que sobem por pequenas mudanças de luminosidade, um único acento. A densidade é alta nas telas de trabalho (tabelas, grafo, conversa) e mais folgada nas telas de leitura (relatório, detalhe de hipótese).
3. **Caráter editorial.** Uma serifa de exposição só nos títulos de página e nos números de destaque, contra uma sans técnica no corpo e uma mono para dados. É o contraste "caderno de laboratório × instrumento" que dá identidade única, sem decoração.

### Referências pesquisadas (2026-10-24)

| Referência | O que aproveitamos |
|---|---|
| Linear (redesenho com temas gerados em espaço perceptual LCH) | superfícies por luminosidade em vez de sombras; tema gerado a partir de poucos parâmetros (base, acento, contraste); bordas finas como textura; atalhos e paleta de comandos |
| Painéis de referência em 2026 (Linear, PostHog, Grafana, Stripe) | cor só como sinal de estado; métrica principal em destaque e detalhe sob demanda (*progressive disclosure*); contraste legível à noite e seguro para daltonismo |
| Vencedores de prêmios de 2025–2026 (Awwwards SOTY: Lando Norris / OFF+BRAND, Messenger / abeto; Webby 2026 Best Visual Design–Function: FOLLOW.ART) | tipografia como elemento principal, contraste forte entre texto de exposição enorme e texto de apoio discreto; movimento com propósito, nunca gratuito |
| Ferramentas de dados científicos (Observable, Hex) | separar a "vista de leitura" da "vista de trabalho"; painéis laterais de contexto (arquivos, variáveis, conexões) |

O que **não** aproveitamos dos sites premiados: rolagem cinematográfica, WebGL, cursores customizados, tipografia cinética no conteúdo. São bons para marca e ruins para trabalho diário de pesquisa.

---

## 2. Cor

Cores definidas em **OKLCH** (perceptualmente uniforme: mesma luminosidade parece igualmente clara em qualquer matiz). Os valores abaixo são os tokens; nenhum componente usa cor fora deles.

### 2.1 Tema escuro (padrão)

| Token | Valor | Uso |
|---|---|---|
| `--color-bg` | `oklch(0.155 0.006 265)` | fundo da aplicação |
| `--color-surface-1` | `oklch(0.185 0.007 265)` | barra lateral, cartões |
| `--color-surface-2` | `oklch(0.215 0.008 265)` | cartão elevado, menu, popover |
| `--color-surface-3` | `oklch(0.255 0.009 265)` | linha em foco/hover, campo de entrada |
| `--color-border` | `oklch(0.29 0.008 265)` | bordas finas (1 px) |
| `--color-border-strong` | `oklch(0.38 0.01 265)` | divisores de seção, campo em foco |
| `--color-text` | `oklch(0.95 0.004 265)` | texto principal |
| `--color-text-muted` | `oklch(0.74 0.01 265)` | texto secundário (≥ 4,5:1 sobre `--color-surface-2`) |
| `--color-text-faint` | `oklch(0.60 0.01 265)` | **só** rótulos ≥ 12 px em caixa alta e marcas de eixo; nunca texto corrido |
| `--color-accent` | `oklch(0.80 0.15 85)` | acento único: "âmbar de instrumento" — ação primária, seleção, foco |
| `--color-accent-contrast` | `oklch(0.20 0.03 85)` | texto sobre o acento |
| `--color-focus` | `oklch(0.85 0.16 85)` | anel de foco (2 px + 2 px de afastamento) |

**Sinais de estado** (cor nunca sozinha: sempre com rótulo ou forma):

| Token | Valor | Significa |
|---|---|---|
| `--color-signal-positive` | `oklch(0.78 0.14 160)` | validada, sucesso, atingiu o alvo |
| `--color-signal-negative` | `oklch(0.72 0.16 25)` | refutada, falha |
| `--color-signal-warning` | `oklch(0.82 0.14 70)` | aguarda pesquisador, limite próximo |
| `--color-signal-info` | `oklch(0.76 0.10 240)` | em teste, executando |
| `--color-signal-neutral` | `oklch(0.70 0.01 265)` | proposta, inconclusiva, arquivado |

Cada sinal tem a variante `-bg` (mesma matiz, `L 0.25`, `C 0.04`) para fundo de etiqueta.

**Paleta categórica do grafo** (rótulos de nó; validada para daltonismo junto com a forma do nó): `--graph-problema` `oklch(0.80 0.15 85)`, `--graph-hipotese` `oklch(0.76 0.10 240)`, `--graph-experimento` `oklch(0.75 0.12 300)`, `--graph-resultado` `oklch(0.78 0.14 160)`, `--graph-abordagem` `oklch(0.75 0.13 200)`, `--graph-descoberta` `oklch(0.80 0.13 120)`, `--graph-dominio` `oklch(0.70 0.01 265)`, `--graph-outro` `oklch(0.62 0.02 265)`.

### 2.2 Tema claro

Mesma matiz e croma, luminosidade espelhada: `--color-bg` `oklch(0.985 0.003 265)`, superfícies `0.97 / 0.955 / 0.93`, borda `0.88`, texto `0.22`, texto secundário `0.45`, acento `oklch(0.58 0.14 70)` (o âmbar escurece para manter 4,5:1 sobre o fundo claro), sinais com `L` entre `0.50` e `0.58`.

### 2.3 Regras

- Profundidade por luminosidade das superfícies; sombra só em menus e diálogos flutuantes (`--shadow-float: 0 8px 24px oklch(0 0 0 / 0.35)`).
- O acento aparece em no máximo **um** elemento de ação por região da tela.
- Contraste conferido por teste automático (`tokens.test.ts`): texto ≥ 4,5:1; elementos de interface e bordas de campo ≥ 3:1.

---

## 3. Tipografia

Fontes **hospedadas pelo próprio backend** (CSP `font-src 'self'`; nada de Google Fonts em produção), instaladas por pacotes `@fontsource-variable/*` com licença OFL:

| Papel | Família | Token |
|---|---|---|
| Exposição (títulos de página, número de destaque do painel) | **Instrument Serif** | `--font-display` |
| Interface e texto | **Geist** (variável) | `--font-sans` |
| Dados, IDs, código, valores de métrica | **Geist Mono** (variável) | `--font-mono` |

Escala (rem sobre 16 px; corpo da interface em 13–14 px, como nas ferramentas de trabalho densas):

| Token | Tamanho / altura de linha | Uso |
|---|---|---|
| `--text-display` | 2.75rem / 1.05, `--font-display` | título de página |
| `--text-metric` | 2.25rem / 1, `--font-display`, algarismos tabulares | número de destaque |
| `--text-h2` | 1.125rem / 1.3, sans 600 | título de seção |
| `--text-h3` | 0.9375rem / 1.35, sans 600 | título de cartão |
| `--text-body` | 0.875rem / 1.5, sans 400 | texto corrido, conversa |
| `--text-ui` | 0.8125rem / 1.4, sans 450 | tabelas, menus, botões |
| `--text-label` | 0.6875rem / 1.3, sans 550, caixa alta, `letter-spacing: 0.06em` | rótulos de campo e de coluna |
| `--text-mono` | 0.8125rem / 1.45, mono, `font-variant-numeric: tabular-nums` | números, IDs, caminhos |

Regras: números sempre com algarismos tabulares e alinhados à direita em tabelas; IDs longos cortados no meio (`a1b2…f9e0`) com o valor inteiro na dica e no botão copiar; leitura longa (relatório, resposta do Researcher) com largura máxima de `68ch`.

---

## 4. Espaço, forma e grade

- **Espaçamento** em escala de 4 px: `--space-1` 4 px, `-2` 8, `-3` 12, `-4` 16, `-5` 24, `-6` 32, `-7` 48, `-8` 64.
- **Raio:** `--radius-sm` 4 px (etiquetas, campos), `--radius-md` 6 px (botões, cartões), `--radius-lg` 10 px (diálogos). Nada de pílulas grandes nem cantos muito arredondados.
- **Densidade:** linha de tabela de 32 px (compacta) ou 40 px (confortável, escolha do pesquisador); padding de célula 6 × 12 px.
- **Grade:** barra lateral de 240 px (recolhível para 56 px), conteúdo em grade de 12 colunas com gutter de 24 px; telas de trabalho com painéis redimensionáveis (lista | conteúdo | detalhe).
- **Bordas:** 1 px `--color-border`; divisores de seção com uma linha fina e um rótulo em `--text-label`, como cabeçalho de caderno de laboratório.

Pontos de quebra: `--bp-sm` 640 px (telefone: barra vira menu, painéis viram abas), `--bp-md` 1024 px (tablet: detalhe vira gaveta), `--bp-lg` 1440 px (1080p e acima: três painéis). Margem lateral mínima de 16 px; nenhuma rolagem horizontal da página (só dentro de tabelas largas, com cabeçalho e primeira coluna fixos).

---

## 5. Movimento

- Durações: `--motion-fast` 120 ms (hover, foco), `--motion-base` 180 ms (abrir menu, gaveta), `--motion-slow` 280 ms (troca de painel). Curva `--ease-out: cubic-bezier(0.2, 0.8, 0.2, 1)`.
- Movimento só para explicar mudança de estado (algo chegou, abriu, foi resolvido). Evento novo na conversa entra com um leve deslize de 4 px e destaque de fundo que esvai em 1,2 s.
- `prefers-reduced-motion: reduce` zera todas as durações e desliga a animação do layout do grafo.

---

## 6. Componentes

Cada componente documenta e testa os estados **padrão, hover, foco, ativo, desabilitado, carregando, vazio e erro** quando se aplicam.

| Componente | Notas |
|---|---|
| `Button` | variantes `primary` (acento), `secondary` (superfície 2 + borda), `ghost`, `danger` (texto e borda `--signal-negative`, nunca fundo vermelho cheio); tamanhos 28/32 px; atalho opcional mostrado à direita (`⌘↵`) |
| `TextField`, `TextArea`, `Select` | rótulo acima em `--text-label`; ajuda e erro abaixo ligados por `aria-describedby`; erro com ícone + texto, não só cor |
| `StatusBadge` | ponto (ou forma) + rótulo em `--text-label`, fundo `-bg` do sinal; estados de projeto (`ativo`, `pausado`, `concluido`, `arquivado`), de sessão (`executando`, `aguarda_pesquisador`, `suspensa`, `interrompida`, `encerrada`), de hipótese |
| `MetricCard` | rótulo, número em `--text-metric`, variação ou contexto em mono, e o **chip de proveniência** (§7) |
| `DataTable` | cabeçalho fixo, ordenação por coluna com `aria-sort`, números à direita, seleção por teclado (↑/↓, Enter abre), densidade compacta/confortável |
| `ProvenanceChip` | ícone + "sessão iris-01 · exp 7"; abre a origem no painel de detalhe |
| `CommandPalette` | `⌘K`/`Ctrl+K`: buscar projeto, nó, artefato e qualquer ação; mostra o atalho de cada ação; foco preso no diálogo |
| `Timeline` (conversa) | itens: mensagem do pesquisador (alinhada à direita, superfície 3), resposta do Researcher (largura de leitura, sem balão), evento (uma linha mono com o apelido em `--text-label`), `DecisionCard` |
| `DecisionCard` | borda esquerda de 3 px em `--signal-warning`, pergunta em `--text-body`, opções como botões, campo de senha quando a decisão é reservada; após resolvida, recolhe para uma linha "resolvida por você, 14:02" |
| `GraphCanvas` + `NodeList` | canvas e lista acessível sincronizados; forma por rótulo (círculo, losango, quadrado, triângulo, hexágono) além da cor; seleção com anel `--color-focus` |
| `FileTree` / `ArtifactViewer` | árvore com setas; visualizador com barra de ferramentas (nome em mono, tamanho, Baixar) |
| `EmptyState` / `ErrorState` | frase curta do que aconteceu e uma ação; sem ilustrações decorativas |
| `Dialog`, `Drawer`, `Toast` | `Toast` só para confirmações transitórias; erro que exige ação nunca vai para toast |

---

## 7. Padrões de interação

- **Teclado primeiro:** `⌘K` paleta; `g p` projetos, `g d` painel, `g c` conversa, `g a` artefatos, `g g` grafo; `/` busca na tela; `Esc` fecha o painel de detalhe. Nada fica escondido só no hover.
- **Proveniência a um toque:** todo número do painel e do grafo leva à sessão/experimento/registro de origem.
- **Divulgação progressiva:** visão geral → lista → detalhe no painel lateral, sem trocar de página.
- **Estados honestos:** dado ausente aparece como "—" com dica ("sem custo registrado"), nunca zero inventado (AGENTS.md §1.6); cortes mostram o que ficou de fora e como ver ("Carregar mais").
- **Texto vindo de agentes** é sempre texto (nunca HTML) e leva uma marca discreta de autoria ("Researcher", "Curator").
- **Confirmações:** ações irreversíveis ou reservadas pedem confirmação no próprio contexto (diálogo com o nome do objeto), nunca um `confirm()` do navegador.

---

## 8. Acessibilidade

WCAG 2.2 AA: contraste de §2.3; alvos de toque ≥ 24 × 24 px (32 px em telas de toque); foco sempre visível; navegação completa por teclado; regiões `aria-live` para eventos e decisões; idioma `pt-BR` no documento; formatação de números e datas por `Intl` em `pt-BR`.

---

## 9. Implementação

- Tokens em `frontend/src/styles/tokens.css` (`:root` = escuro; `[data-theme="light"]`), espelhados em `frontend/src/styles/tokens.ts` só para o Cytoscape (que não lê variáveis CSS). Um teste confere que os dois arquivos têm os mesmos valores.
- CSS Modules por componente; proibido valor literal de cor, espaçamento, raio, fonte ou duração fora dos tokens (regra de lint `stylelint-declaration-strict-value`, se aprovada como dependência, ou teste que procura literais nos `.module.css`).
- Página interna `/_design` (só em desenvolvimento) com todos os componentes e estados, usada como referência visual e nos testes.
