# Proposta: Controle de Equipamentos Físicos (conversão da Spec G7)

**ID:** `v19-equipment-control` · **Versão:** V19 · **Capacidade:** `equipment-control`
**ADRs de origem:** [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md)
§10 (somente leitura por padrão; confirmação humana para toda escrita em qualquer
`SessionMode`), §3 (leituras são dados de pesquisa), §2 (origem dos números);
[ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md) §3 (ferramenta
tipada no host, nunca código gerado no host); [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md)
§2/§4 (`Abordagem` do tipo `instrumento`) e §9.3 (falha de equipamento = causa
`infraestrutura`); [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
(limites de uso e continuidade valem para experimentos físicos)
**Substitui:** a Spec G7 (`roadmaps/specs/G7_equipment_control_mhs.md`), fase V19. A fase de
migração para o padrão MHS continua condicional e fora desta mudança.
**Depende de:** V18 e V18.5 concluídas (`v18-usage-limits`, `v18.5-egress-gate`,
`v18.5-execution-provenance`); `v18-researcher-consult` (decisão `autorizar_escrita_instrumento`
reservada ao humano)

## Por quê

A G7 foi escrita antes de quatro decisões que mudam o desenho:

- **ADR 014:** não há mais container de agente nem IPC. A G7 previa "comunicação entre o
  container do Developer e a `EquipmentSkill` via socket IPC dedicado" (Tarefa 3); agora a
  ferramenta é uma skill tipada no processo do host, como as demais.
- **ADR 019 §10:** ferramentas de instrumento são **somente leitura por padrão** e toda escrita
  exige **confirmação do pesquisador em qualquer modo**, além da lista de permissão e dos
  limites de segurança da G7. A G7 só exigia a lista de permissão (Tarefa 4).
- **ADR 019 §3 e §2:** leituras de instrumentos são dados de pesquisa: não vão a modelos sem
  `aceita_dados_brutos`, e todo número relatado precisa de origem rastreável.
- **ADR 015:** instrumentos entram no grafo como `Abordagem(tipo="instrumento")`, e falhas de
  equipamento não afetam o veredito de hipóteses (causa `infraestrutura`).

## O que muda

- **Novo:** `BaseEquipmentDriver` com primitivas `read`/`write`/`list_channels` e
  `device_tags`/`safety_limits` (mantido da G7), mais `estado_seguro` declarado por dispositivo.
- **Novo:** drivers GPIO (`gpiod`), I2C (`smbus2`) e serial (`pyserial`), num extra opcional
  `equipment` do `pyproject.toml`; driver simulado para testes.
- **Novo:** configuração local de dispositivos (`equipment.yaml`, não versionado): protocolo,
  endereço, canais, limites, canais em que a escrita pode ser pedida e estado seguro.
- **Novo:** autorização no início da sessão: a CLI lista os dispositivos e o pesquisador
  autoriza o acesso (leitura) e, separadamente, a lista de canais de escrita.
- **Novo:** ferramentas tipadas `equipment_read` e `equipment_write` no host. Escrita só com:
  canal na lista autorizada, valor dentro de `safety_limits` e **confirmação do pesquisador para
  aquele comando**, em qualquer `SessionMode`; sem confirmação dentro do prazo, a escrita é
  negada.
- **Novo:** leituras gravadas em arquivo da subtarefa com carimbo de tempo e devolvidas ao
  agente como `dado_de_pesquisa` pelo `EgressGate`; registro de todas as operações, com a
  escrita registrada antes de executar.
- **Novo:** estado seguro aplicado ao fim da sessão, em parada por limite e em interrupção.
- **Novo:** instrumentos como `Abordagem(tipo="instrumento")` nos fatos estruturais; falha de
  comunicação com equipamento classificada como `infraestrutura`.
- **Removido (em relação à G7):** IPC dedicado; execução da skill "fora do container do
  Developer" (não há mais container de agente).
- **Fora do escopo:** migração para MHS; controle por código gerado no sandbox (o sandbox não
  tem acesso a hardware); dispositivos de rede (TCP/VISA), a avaliar depois.

## Impacto

- **Código:** `src/skills/equipment/` (novo: `base.py`, `config.py`, `gpio_driver.py`,
  `i2c_driver.py`, `serial_driver.py`, `fake_driver.py`, `skill.py`, `confirmation.py`),
  `src/cli.py` (autorização e confirmação), `src/orchestrator.py` (estado seguro no
  fechamento, payload), `src/knowledge/` (ingestão de `Abordagem` instrumento e causa de falha),
  `src/egress/classification.py` (origem das leituras), `agents/developer/agent.py`,
  `pyproject.toml` (extra `equipment`), `src/config.py`, `.env.example`.
- **Hardware:** o processo do orquestrador precisa de permissão de grupo (`gpio`, `i2c`,
  `dialout`) no Pi 5; nunca root.
- **Testes:** sem hardware no CI (driver simulado); validação real no Pi 5 com um sensor I2C e
  um LED em GPIO.

## Aprovações necessárias

1. **Acesso a hardware pelo processo do host:** revisão obrigatória do Analista de Segurança e
   do Pentester (`.agents/rules/pentester.md`) antes do merge.
2. **Dependências novas** (`gpiod`, `smbus2`, `pyserial`) num extra opcional.
3. **Spec G7:** marcar `roadmaps/specs/G7_equipment_control_mhs.md` como substituída por esta
   mudança (sem apagar o arquivo).
