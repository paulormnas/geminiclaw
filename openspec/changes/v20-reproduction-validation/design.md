# Design: Validação por Reprodução entre Nós

## 1. Fluxo

```
pesquisador: federation reproduce <cid>
  1. registro `experimento` válido e na caixa de entrada (ou buscado por cid)
  2. pré-checagem: código inline presente? hash do código confere? datasets públicos com
     sha256? → senão, `inconclusiva` sem executar (motivo registrado)
  3. resumo exibido: autor e confiança, código (paginado), pacotes, datasets e tamanhos,
     tempo estimado (do `ambiente` publicado), limites locais → confirmação [s/N]
  4. execução no sandbox: install (rede, sem dados) → fetch_assets (datasets com sha256)
     → execute (sem rede, params e seed publicados)
  5. comparação de métricas (§3)
  6. registro `reproducao` montado → caixa de saída (revisão humana) → publicação
```

Não há LLM em nenhum passo. Uma reprodução que quebra por diferença de API de biblioteca não é
"consertada" por agente: é `inconclusiva` com motivo `erro_execucao` e o log fica disponível.
Consertar e rodar de novo é uma pesquisa nova, com o fluxo normal.

## 2. Execução

- Código: o `codigo` inline do registro, gravado como `script.py` da reprodução; o sha256 tem de
  bater com `hash_codigo`, senão `inconclusiva` (`hash_divergente`).
- Pacotes: os de `ambiente.pacotes`, com as versões publicadas (`nome==versão`), validados pela
  gramática PEP 508 (`v16-sandbox-slim-image`). Versão indisponível para a arquitetura local →
  `inconclusiva` (`pacote_indisponivel`).
- Datasets: só referências `{nome, sha256, url}`, baixadas como ativos com hash obrigatório
  (`v18.5-sandbox-phases`); dataset `privado` → `inconclusiva` (`dado_privado`).
- `params.json` reconstruído a partir do registro, com a mesma seed.
- Diretório próprio: `outputs/federation/reproducoes/<cid_curto>/`.
- Limites: `FEDERATION_REPRO_MAX_MINUTES` (padrão 30) no total da reprodução, além dos timeouts
  do sandbox; `FEDERATION_REPRO_MAX_PER_DAY` (padrão 3).

## 3. Comparação (proposta para "Variação de hardware")

Para cada métrica publicada `m` com valor `p` e valor obtido `o`:

```
tol_abs = tolerancias[m].abs  se declarada, senão FEDERATION_REPRO_ABS_TOL (1e-9)
tol_rel = tolerancias[m].rel  se declarada, senão FEDERATION_REPRO_REL_TOL (0.02)
dentro  = |o - p| ≤ max(tol_abs, tol_rel × |p|)
```

- `confirmada`: execução concluída e todas as métricas publicadas dentro da tolerância.
- `refutada`: execução concluída e ao menos uma métrica fora da tolerância.
- `inconclusiva`: execução não concluída, métrica publicada ausente na saída, ou pré-checagem
  falhou. Corresponde à causa `infraestrutura` do ADR 015 §9.3: não depõe contra o autor.
- O autor pode declarar tolerância por métrica no `experimento` (ex.: métricas com GPU não
  determinística). Tolerância declarada acima de `FEDERATION_REPRO_MAX_REL_TOL` (0.2) é limitada
  a esse valor e o registro de reprodução informa o limite aplicado.
- Arquitetura, versão do Python e pacotes efetivos (introspecção do sandbox) vão no registro,
  para que terceiros julguem diferenças de hardware.

## 4. Registro `reproducao`

```json
{"tipo": "reproducao", "refs": ["sha256:<experimento>"],
 "conteudo": {"resultado": "confirmada|refutada|inconclusiva", "motivo": null,
   "metricas": {"accuracy": {"publicado": "0.953", "obtido": "0.947", "dentro": true,
                              "tol_rel": "0.02", "tol_abs": "1e-9"}},
   "ambiente": {"arquitetura": "arm64", "python": "3.11.x", "pacotes": {"scikit-learn": "1.8.0"}},
   "hash_codigo_verificado": "sha256:…", "duracao_s": 412}}
```

Publicado pela caixa de saída (`v20-federated-records` §3.6), com revisão humana. O pesquisador
pode guardar o resultado só localmente (rejeitar a publicação).

## 5. Segurança

- Código remoto é tratado como hostil: só roda no sandbox endurecido (usuário sem privilégios,
  sem capacidades, raiz somente leitura, execução sem rede), com limites de CPU, memória,
  processos e tempo.
- A fase com rede (instalação e ativos) não vê o código nem dados locais; pacotes com versão
  fixa; ativos com sha256 obrigatório.
- Nenhum dado local do pesquisador é montado na reprodução.
- Saída do script volta só para o diretório da reprodução; nada vai a LLM.

## 6. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `FEDERATION_REPRO_MAX_MINUTES` | 30 | Tempo máximo por reprodução |
| `FEDERATION_REPRO_MAX_PER_DAY` | 3 | Reproduções por dia |
| `FEDERATION_REPRO_REL_TOL` | 0.02 | Tolerância relativa padrão |
| `FEDERATION_REPRO_ABS_TOL` | 1e-9 | Tolerância absoluta padrão |
| `FEDERATION_REPRO_MAX_REL_TOL` | 0.2 | Teto da tolerância declarada pelo autor |

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Fluxo próprio fora das sessões de pesquisa. |
| Agentes & Prompts | Nenhum (sem LLM). |
| Sandboxes & Containers | Executa código remoto no sandbox; reaproveita fases de rede e ativos. |
| Persistência | Diretório de reproduções; registros `reproducao` em `federation_records`. |
| Segurança | Código hostil contido pelo sandbox; sem dados locais; sem rede na execução. |
| Testes & Telemetria | Registros de teste com código conhecido; evento `federation_reproduce`. |

## 8. Questões em aberto para o pesquisador

1. Tolerâncias padrão (2% relativa) e teto da tolerância declarada (20%).
2. Limites de custo (30 min e 3 por dia) para o Pi 5.
3. Publicar reproduções `inconclusiva`? A proposta é permitir, porque informa a rede sobre
   reprodutibilidade, mas elas não afetam a reputação.
