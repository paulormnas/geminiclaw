# Design System — "Bancada"

**Status:** Proposto (2026-10-24, variação 2 aprovada pelo pesquisador) · **Dono:** Designer de Produto · **Origem:** ADR 027 §5
**Exemplo visual:** [`exemplo.html`](exemplo.html) (abrir no navegador; usa Google Fonts só no exemplo, a aplicação hospeda as fontes).
**Vale para:** todo código em `frontend/`. Os agentes desenvolvedores seguem este documento; valor visual fora dele exige atualizar este documento antes (regra do `designer.md`).

---

## 1. Conceito

A interface é uma **bancada de laboratório digital**: um instrumento de precisão, não um site de marketing. Três ideias guiam tudo:

1. **Evidência em primeiro plano.** Todo número mostra de onde veio (sessão, experimento, registro) com um toque. Nada de métricas soltas.
2. **Calma e densidade ao mesmo tempo.** Superfícies claras ou marinho profundo, um único sinal forte (lima). Densidade alta nas telas de trabalho e mais folgada nas de leitura.
3. **Uma voz tipográfica.** Uma família só (Plus Jakarta Sans) para títulos, interface e números; a hierarquia vem de peso (400–800), tamanho e tracking negativo nos títulos, não de troca de família. Mono só para código, IDs e caminhos. Decisão do pesquisador em 2026-10-24, após rejeitar a v1 (serifa + sans + mono não conversavam).

### Referências pesquisadas (2026-10-24)

| Referência | O que aproveitamos |
|---|---|
| Linear (redesenho com temas gerados em espaço perceptual LCH) | superfícies por luminosidade em vez de sombras; tema gerado a partir de poucos parâmetros (base, acento, contraste); bordas finas como textura; atalhos e paleta de comandos |
| Painéis de referência em 2026 (Linear, PostHog, Grafana, Stripe) | cor só como sinal de estado; métrica principal em destaque e detalhe sob demanda (*progressive disclosure*); contraste legível à noite e seguro para daltonismo |
| Vencedores de prêmios de 2025–2026 (Awwwards SOTY: Lando Norris / OFF+BRAND, Messenger / abeto; Webby 2026 Best Visual Design–Function: FOLLOW.ART) | tipografia como elemento principal, contraste forte entre texto de exposição enorme e texto de apoio discreto; movimento com propósito, nunca gratuito |
| Sollytch (sollytch.com, cliente futuro) | paleta marinho + lima, Plus Jakarta Sans, sombra de cartão suave |
| Vercel Geist, guias de pareamento para painéis | uma família com algarismos tabulares é melhor que mono para colunas; mono reservada a dados técnicos |
| Ferramentas de dados científicos (Observable, Hex) | separar a "vista de leitura" da "vista de trabalho"; painéis laterais de contexto (arquivos, variáveis, conexões) |

O que **não** aproveitamos dos sites premiados: rolagem cinematográfica, WebGL, cursores customizados, tipografia cinética no conteúdo. São bons para marca e ruins para trabalho diário de pesquisa.

---

## 2. Cor

Tokens em **HSL**, derivados da Sollytch. Os valores canônicos estão em `exemplo.html` (`:root` e `[data-theme="dark"]`); nenhum componente usa cor fora deles. Tema **claro por padrão**, escuro com o mesmo cuidado, e "Sistema" segue `prefers-color-scheme`.

| Token | Claro | Escuro | Uso |
|---|---|---|---|
| `--bg` | `220 30% 98%` | `230 60% 6%` | fundo |
| `--surface` / `-2` / `-3` | `0 0% 100%` / `220 40% 96.5%` / `220 45% 93%` | `230 50% 9.5%` / `230 42% 12.5%` / `230 38% 16%` | cartões, hover, campo |
| `--border` / `-strong` | `220 22% 88%` / `222 20% 78%` | `230 30% 18%` / `230 25% 27%` | bordas 1 px |
| `--text` / `-muted` / `-faint` | `230 60% 14%` / `230 18% 40%` / `230 12% 46%` | `220 30% 95%` / `220 18% 70%` / `220 14% 60%` | texto (`-faint` só em rótulos) |
| `--primary` | marinho `230 80% 25%` | lima `72 100% 50%` | ação primária |
| `--accent` | lima `72 100% 50%` | lima | sinal: pendências, envio, destaque |
| `--focus` | `230 80% 45%` | lima | anel de foco 2 px |

**Sinais de estado** (sempre com rótulo ou forma), cada um com `-bg`: `--pos` validada/sucesso, `--neg` refutada/falha, `--warn` aguarda você/limite, `--info` em teste/executando, `--neu` proposta/inconclusiva/arquivado. Valores por tema no exemplo.

**Grafo:** Problema marinho (quadrado com marca lima), Hipótese `--info` (círculo), Experimento `--g-exp` (quadrado), Resultado `--pos`/`--neg` (triângulo), Abordagem `--g-abo` (hexágono); forma sempre junto da cor.

### 2.1 Regras

- Sombra de cartão suave (`--shadow`, a da Sollytch); profundidade também por superfícies.
- Lima em no máximo um elemento de ação por região; no tema claro, lima nunca como cor de texto (usar `--accent-ink`).
- Contraste conferido por teste automático (`tokens.test.ts`): texto ≥ 4,5:1; interface e bordas de campo ≥ 3:1, nos dois temas.

---

## 3. Tipografia

Fontes **hospedadas pelo backend** (CSP `font-src 'self'`; Google Fonts só no exemplo), via `@fontsource-variable/plus-jakarta-sans` e `@fontsource-variable/jetbrains-mono` (OFL).

| Papel | Família | Token |
|---|---|---|
| Títulos, interface, texto e números | **Plus Jakarta Sans** com `font-feature-settings: "tnum"` | `--font` |
| Código, IDs, caminhos (nunca métricas) | **JetBrains Mono** | `--font-code` |

| Token | Tamanho / altura | Uso |
|---|---|---|
| `--text-display` | clamp(1.75rem, 3.4vw, 2.5rem) / 1.08, 800, `-0.035em` | título de página |
| `--text-metric` | 2.125rem / 1, 800, `-0.04em` | número de destaque |
| `--text-h2` | 0.9375rem / 1.3, 700 | título de seção/cartão |
| `--text-body` | 0.875rem / 1.55, 500 | conversa, leitura |
| `--text-ui` | 0.8125rem / 1.45, 500–650 | tabelas, menus, botões |
| `--text-label` | 0.6875rem / 1.3, 700, caixa alta, `0.07em` | rótulos |
| `--text-code` | 0.75rem / 1.4, mono | código, IDs |

Regras: números com algarismos tabulares, alinhados à direita em tabelas; IDs longos cortados no meio (`a1b2…f9e0`) com o valor inteiro na dica; leitura longa com até `66ch`.

---

## 4. Espaço, forma e grade

- **Espaçamento** em escala de 4 px: `--space-1` 4 px, `-2` 8, `-3` 12, `-4` 16, `-5` 24, `-6` 32, `-7` 48, `-8` 64.
- **Raio:** `--r-sm` 6 px, `--r-md` 10 px (botões, campos), `--r-lg` 14 px (cartões, diálogos); etiquetas de estado em pílula.
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
