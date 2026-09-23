# ADR 003 — Containerização Docker com Sandbox DinD Resiliente

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap.md` (Etapa 5), `roadmaps/roadmap_V10_stability.md` (V10.1)

---

## Contexto

Agentes que executam código arbitrário representam um risco de segurança e instabilidade. Precisamos de isolamento entre:
- O processo do orquestrador (host)
- Os agentes LLM (que manipulam contexto, fazem tool calls)
- O sandbox de execução de código Python (que executa código gerado pelo LLM)

Adicionalmente, o orquestrador em si pode rodar dentro de um container Docker (Docker-in-Docker / DinD), o que impõe restrições especiais ao mapeamento de volumes.

---

## Decisão

### 1. Agentes como Containers Efêmeros

Cada agente (base, researcher, planner, validator, summarizer) executa em um container Docker efêmero gerenciado pelo `ContainerRunner` (`src/runner.py`):

```python
client.containers.run(
    image="geminiclaw-<tipo>:latest",
    mem_limit="384m",          # 256m para agentes leves, 384m para pesados
    nano_cpus=1_000_000_000,   # 1 core ARM (Raspberry Pi 5)
    network="geminiclaw-net",
    user="appuser",            # non-root obrigatório
    remove=True,               # container destruído ao terminar
    detach=True,
)
```

Limites de recursos são calibrados para o Raspberry Pi 5 (8GB RAM, ARM Cortex-A76).

### 2. Sandbox de Código via `put_archive`/`get_archive` (Sem Bind Mounts)

O `PythonSandbox` (`src/skills/code/sandbox.py`) executa código Python em containers isolados usando transferência de arquivos por stream (tar archive):

- **`put_archive`:** Injeta o script Python dentro do container antes da execução, sem bind mounts.
- **`get_archive`:** Extrai os artefatos gerados após a execução.
- **Sem rede:** `network_disabled=True` — o container de código não tem acesso à rede.
- **Sem volumes persistentes:** O filesystem do container é efêmero; apenas os artefatos extraídos via `get_archive` são preservados no `output_dir` da sessão.

### 3. Rede Isolada

Todos os containers de agente operam na rede `geminiclaw-net` (criada em `docker-compose.yml`). Esta rede oferece:
- Acesso ao PostgreSQL e Qdrant (serviços da infraestrutura)
- Acesso ao host via IPC socket montado como volume
- Isolamento de redes externas (exceto quando a skill de busca web está ativa)

### 4. Controle de Concorrência

```python
asyncio.Semaphore(MAX_LOCAL_LLM_CONCURRENT)  # default: 3
```

Máximo de 3 agentes simultâneos para preservar recursos do Pi 5 (evita thrashing de memória e sobrecarga térmica).

---

## Causa Raiz que Motivou a Abordagem de `put_archive`/`get_archive`

**Problema original (diagnosticado em V10):** O `PythonSandbox` usava bind mounts com caminhos absolutos do host. Quando o orquestrador rodava dentro de um container Docker (DinD), o daemon Docker local recebia caminhos que só existiam dentro do container do orquestrador — resultando em volumes vazios silenciosos e erro `python: can't open file '/outputs/script.py'` 100% das vezes.

**Solução adotada:** Eliminar bind mounts do sandbox. Usar `put_archive` e `get_archive` do Docker SDK, que funcionam via socket Unix e são completamente imunes a problemas de resolução de caminhos em DinD.

---

## Alternativas Consideradas

### Alternativa A: Bind mounts para sandbox

Montar o diretório de output diretamente no container do sandbox via `volumes` parameter.

**Descartado porque:**
- Falha silenciosa em ambiente DinD (causa raiz documentada em V10)
- Dependência de caminhos absolutos do host — frágil em diferentes ambientes
- Impossível de testar unitariamente sem Docker real

### Alternativa B: subprocess local (sem container)

Executar o código Python diretamente como subprocesso no processo do orquestrador.

**Descartado porque:**
- Sem isolamento: código malicioso ou com bug pode corromper o estado do orquestrador
- Sem limite de recursos (sem mem_limit, sem CPU limit)
- Incompatível com o requisito de segurança (escape de sandbox)

### Alternativa C: Firecracker / gVisor para sandboxing

Usar microVMs (Firecracker) ou sandbox de kernel (gVisor) para isolamento mais forte.

**Descartado porque:**
- Overhead excessivo para o Raspberry Pi 5
- Complexidade de setup e manutenção muito alta
- Docker com `network_disabled=True` e usuário non-root é suficiente para o caso de uso

---

## Consequências

### Positivas

- **Isolamento garantido:** Falha de agente não afeta o orquestrador.
- **Segurança:** Código gerado por LLM executa sem acesso à rede e como usuário não privilegiado.
- **Compatibilidade DinD:** `put_archive`/`get_archive` funciona em qualquer ambiente Docker, incluindo CI/CD.
- **Footprint controlado:** Limites de RAM e CPU são enforced pelo kernel Linux via cgroups.

### Negativas / Trade-offs

- **Overhead de startup:** Cada container leva ~1-3 segundos para iniciar — relevante para tarefas com muitas tool calls de código.
- **Transferência de arquivos:** `put_archive`/`get_archive` adiciona overhead de serialização/desserialização de tar archives.
- **Complexidade de debugging:** Logs de execução dentro do container precisam ser extraídos ou enviados via IPC.

---

## Revisão

Este ADR deve ser revisado quando:
- V14 for implementado (containers por sessão em vez de efêmeros por subtarefa)
- O hardware alvo mudar (ex: migrar do Pi 5 para servidor com mais recursos)
- Novos requisitos de isolamento surgirem (ex: multi-tenant)
