# Design: Controle de Equipamentos Físicos

## 0. Estado atual (2026-10-01)

Nenhuma ferramenta de equipamento está implementada (ADR 019 §10). A G7
(`roadmaps/specs/G7_equipment_control_mhs.md`) é a referência funcional; este design mantém suas
primitivas, drivers e lista de permissão e muda o transporte (sem IPC), a autorização de escrita
e o tratamento dos dados.

| Item da G7 | Destino nesta mudança |
|---|---|
| Tarefa 1: `BaseEquipmentDriver`, `device_tags`, `safety_limits`, `SafetyLimitViolation` | Mantido (§1), com `estado_seguro` |
| Tarefa 2: drivers GPIO (`gpiod`), I2C (`smbus2`), serial (`pyserial`); log antes da escrita | Mantido (§2) |
| Tarefa 3: `EquipmentSkill` no host via IPC dedicado | Skill tipada em processo (ADR 014); sem IPC (§4) |
| Tarefa 3: `device_tags` no contexto do Developer | Mantido, sem valores de leitura (§4) |
| Tarefa 4: autorização de dispositivos e `allowlist` de escrita | Mantido, mais confirmação por comando em qualquer modo (§3, ADR 019 §10) |
| Fase MHS | Fora do escopo (condicional, como na G7) |

## 1. Driver

```python
class BaseEquipmentDriver(ABC):
    device_id: str
    device_tags: dict        # nome, protocolo, canais de leitura/escrita, unidades, faixas
    safety_limits: dict      # canal -> {"min": ..., "max": ..., "taxa_max_por_min": ...}
    estado_seguro: dict      # canal -> valor aplicado no fechamento (pode ser vazio)

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read(self, channel: str, params: dict | None = None) -> Reading: ...
    async def write(self, channel: str, value: Any, params: dict | None = None) -> None: ...
    async def list_channels(self) -> list[ChannelInfo]: ...

@dataclass(frozen=True)
class Reading:
    device_id: str; channel: str; value: float | int | str; unit: str | None
    timestamp: str  # ISO-8601 UTC
```

- `write` verifica `safety_limits` **antes** de qualquer operação e levanta
  `SafetyLimitViolation` (mantido da G7). `taxa_max_por_min` limita a frequência de escrita por
  canal.
- Os drivers não decidem autorização: isso fica na skill (§3), para que nenhum caminho de
  escrita contorne a confirmação.
- `FakeDriver` (canais em memória, falhas injetáveis) para testes e para desenvolvimento no Mac.

## 2. Configuração dos dispositivos (`equipment.yaml`)

Arquivo local (caminho em `EQUIPMENT_CONFIG_PATH`, padrão `equipment.yaml` na raiz, no
`.gitignore`), validado por esquema estrito:

```yaml
dispositivos:
  - id: sensor_temp_1
    driver: i2c                 # gpio | i2c | serial | fake
    endereco: {barramento: 1, endereco: 0x76}
    canais_leitura: [temperatura, umidade]
    canais_escrita: []          # vazio = dispositivo só de leitura
    safety_limits: {}
    estado_seguro: {}
  - id: led_status
    driver: gpio
    endereco: {chip: gpiochip0, linha: 17}
    canais_leitura: [nivel]
    canais_escrita: [nivel]
    safety_limits: {nivel: {min: 0, max: 1, taxa_max_por_min: 30}}
    estado_seguro: {nivel: 0}
```

Um canal só pode aparecer em `canais_escrita` se tiver `safety_limits`. Dispositivos sem
`canais_escrita` são somente leitura e a ferramenta de escrita nem é oferecida para eles.

## 3. Autorização (ADR 019 §10)

Três camadas, todas obrigatórias para uma escrita:

1. **Início da sessão (CLI):** lista os dispositivos configurados e detectados; o pesquisador
   autoriza o acesso de leitura (`[s/N]`) e, em pergunta separada, quais canais de escrita
   ficam liberados nesta sessão (padrão: nenhum). Sem resposta (ex.: execução não interativa),
   nada é autorizado. A autorização vai para `payload["equipment"]` e para o relatório final.
2. **Limites:** canal na lista liberada e valor em `safety_limits`, verificados pela skill
   antes de pedir a confirmação.
3. **Confirmação por comando, em qualquer `SessionMode`:** a skill pede ao pesquisador, no
   terminal, a confirmação daquele comando (dispositivo, canal, valor atual lido, valor novo,
   justificativa do agente). A sessão aguarda até `EQUIPMENT_WRITE_CONFIRM_TIMEOUT_SECONDS`
   (padrão 300); sem resposta, a escrita é **negada**. Em `semi`/`auto` isso é uma pausa
   explícita da autonomia, exigida pelo ADR. O Researcher consultor nunca responde essa
   confirmação (`autorizar_escrita_instrumento` é decisão reservada, `v18-researcher-consult`).

Toda negação (fora da lista, fora dos limites, confirmação negada ou expirada) volta ao agente
como erro tipado (`PermissionDeniedError`, `SafetyLimitViolation`, `ConfirmationDenied`) e é
registrada.

## 4. Ferramentas e fluxo de dados

- `equipment_list()` → dispositivos autorizados com `device_tags` (sem valores).
- `equipment_read(device, channel, n=1, intervalo_s=0)` → grava as leituras em
  `outputs/<sessão>/<tarefa>/equipment/<device>_<channel>_<timestamp>.jsonl` e devolve ao agente
  um `PromptFragment` com origem `dado_de_pesquisa` contendo os valores. Pelo `EgressGate`
  (V18.5), modelos sem `aceita_dados_brutos` recebem só metadados (`n`, unidade, caminho do
  arquivo); modelos no nó recebem os valores.
- `equipment_write(device, channel, value, justificativa)` → camadas do §3; registra a intenção
  no log **antes** de executar; executa; lê o canal de volta quando ele também é de leitura e
  registra o resultado.
- O Developer analisa leituras escrevendo código que lê os arquivos `.jsonl` no sandbox; o
  sandbox não tem acesso a hardware.
- `device_tags` dos dispositivos autorizados entram no contexto do Developer (G7 Tarefa 3).

## 5. Registro, proveniência e grafo

- Log `logs/equipment_<session_id>.log` (mantido da G7) e eventos de telemetria
  `equipment_read`, `equipment_write_requested`, `equipment_write_decision`,
  `equipment_write_done`.
- Os arquivos de leitura são registrados como artefatos de execução
  (`v18.5-execution-provenance`), o que dá origem rastreável a números derivados deles (ADR 019
  §2).
- Fatos estruturais: cada dispositivo usado numa subtarefa vira
  `Abordagem(tipo="instrumento", nome=<device_tags.nome>)` e
  `Experimento-APLICOU->Abordagem`; erro de comunicação ou de driver na subtarefa classifica a
  falha como `infraestrutura` (ADR 015 §9.3), que não afeta o veredito.

## 6. Estado seguro e limites de uso

- Ao fechar a sessão (fim normal, limite de uso do `UsageTracker`, `Ctrl+C`, exceção), o
  orquestrador aplica `estado_seguro` dos dispositivos com canais de escrita liberados e depois
  `disconnect()`. Essa escrita foi aprovada pelo pesquisador ao autorizar o dispositivo no
  início da sessão e não pede nova confirmação; falha ao aplicar gera `ERROR` e aparece no
  relatório.
- `EQUIPMENT_MAX_WRITES_PER_SESSION` (padrão 50) limita o total de escritas; atingido, novas
  escritas são negadas (a sessão continua).
- Continuidade (ADR 010): a autorização **não** é herdada por uma sessão que continua outra;
  é pedida de novo.

## 7. Configuração

| Variável | Padrão | Uso |
|---|---|---|
| `EQUIPMENT_ENABLED` | `false` | Liga as ferramentas de equipamento |
| `EQUIPMENT_CONFIG_PATH` | `equipment.yaml` | Configuração local dos dispositivos |
| `EQUIPMENT_WRITE_CONFIRM_TIMEOUT_SECONDS` | 300 | Prazo da confirmação por comando |
| `EQUIPMENT_MAX_WRITES_PER_SESSION` | 50 | Teto de escritas por sessão |
| `EQUIPMENT_READ_MAX_SAMPLES` | 1000 | Máximo de amostras por chamada de leitura |

## 8. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Autorização no início; estado seguro no fechamento; pausa para confirmação de escrita. |
| Agentes & Prompts | Developer recebe `device_tags` e as ferramentas; instrução de que escrita sempre pede confirmação. |
| Sandboxes & Containers | Nenhum acesso a hardware no sandbox; leituras chegam como arquivos. |
| Persistência | `payload["equipment"]`; arquivos `.jsonl` de leitura; log dedicado. |
| Segurança | Somente leitura por padrão; três camadas para escrita; nenhuma escrita por código gerado; processo sem root. |
| Testes & Telemetria | Driver simulado; eventos por operação; validação real no Pi 5. |

## 9. Segurança (para o Analista de Segurança e o Pentester)

- **Injeção de prompt** induzindo escrita: barrada pela confirmação humana por comando; a
  justificativa do agente é exibida como texto do agente, não como instrução.
- **Contorno pela skill de código:** o sandbox não monta `/dev/gpiochip*`, `/dev/i2c-*` nem
  `/dev/tty*` (teste explícito).
- **Negação por exaustão de confirmações** em `auto`: `EQUIPMENT_MAX_WRITES_PER_SESSION` e
  `taxa_max_por_min`.
- **Permissões do processo:** grupos de hardware, nunca root; documentado no `SETUP.md`.

## 10. Questões em aberto para o pesquisador

1. **Confirmação por comando** (proposta, ADR 019 §10 ao pé da letra) ou confirmação de um
   **plano de escrita** (lista de comandos e valores) de uma vez? Experimentos com muitas
   escritas ficam lentos com a confirmação por comando.
2. Confirmação só no terminal ou também por outro canal (ex.: notificação), para sessões `auto`
   longas?
3. Valores de `EQUIPMENT_MAX_WRITES_PER_SESSION` e do prazo de confirmação.
