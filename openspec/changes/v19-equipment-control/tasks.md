# Tarefas: v19-equipment-control

## 0. Pré-requisitos
- [ ] 0.1 V18.5 concluída (`v18.5-egress-gate`, `v18.5-execution-provenance`) e `v18-researcher-consult` no `dev`.
- [ ] 0.2 Respostas do pesquisador às questões em aberto do design §10.
- [ ] 0.3 Aprovação das dependências do extra `equipment` (`gpiod`, `smbus2`, `pyserial`).

## 1. Drivers
- [ ] 1.1 `src/skills/equipment/base.py`: `BaseEquipmentDriver`, `Reading`, `ChannelInfo`, `SafetyLimitViolation` (faixa e frequência).
- [ ] 1.2 `fake_driver.py` com falhas injetáveis.
- [ ] 1.3 `gpio_driver.py` (`gpiod`), `i2c_driver.py` (`smbus2`), `serial_driver.py` (`pyserial`).
- [ ] 1.4 `uv add --optional equipment gpiod smbus2 pyserial`.

## 2. Configuração e autorização
- [ ] 2.1 `config.py` da skill: esquema estrito do `equipment.yaml`; canal de escrita exige limites; entrada no `.gitignore`.
- [ ] 2.2 CLI: autorização de leitura e liberação de canais de escrita no início da sessão; `payload["equipment"]`.
- [ ] 2.3 `confirmation.py`: confirmação por comando no terminal com prazo; nunca respondida por agente.

## 3. Ferramentas e dados
- [ ] 3.1 `skill.py`: `equipment_list`, `equipment_read`, `equipment_write` com as três camadas do design §3.
- [ ] 3.2 Leituras em `.jsonl` da subtarefa; registro como artefato de execução; origem `dado_de_pesquisa` no `EgressGate`.
- [ ] 3.3 Log `logs/equipment_<session_id>.log` e eventos de telemetria; intenção antes da execução.
- [ ] 3.4 `device_tags` no contexto do Developer; instrução sobre confirmação.

## 4. Sessão e grafo
- [ ] 4.1 Estado seguro e desconexão no fechamento (todos os motivos de parada).
- [ ] 4.2 Teto de escritas por sessão; autorização não herdada na continuação.
- [ ] 4.3 `Abordagem(tipo="instrumento")` + `APLICOU`; causa `infraestrutura` para erro de driver.

## 5. Testes
- [ ] 5.1 Limites: faixa e frequência.
- [ ] 5.2 Somente leitura: nenhum canal liberado; canal sem limites; execução não interativa.
- [ ] 5.3 Confirmação: `auto` confirmado; prazo expirado; consultor não chamado.
- [ ] 5.4 Ordem do registro.
- [ ] 5.5 Sandbox sem dispositivos; chamada sem IPC.
- [ ] 5.6 Leituras com modelo sem dados brutos e no nó.
- [ ] 5.7 Estado seguro por limite de tempo; falha ao aplicar.
- [ ] 5.8 Grafo: instrumento e causa de infraestrutura.
- [ ] 5.9 Continuação e teto de escritas.

## 6. Fechamento
- [ ] 6.1 Marcar a Spec G7 como substituída por esta mudança; `SETUP.md` com grupos de hardware do Pi 5.
- [ ] 6.2 `.env.example`.
- [ ] 6.3 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 6.4 Validação no Pi 5 com um sensor I2C e um LED em GPIO.
- [ ] 6.5 Revisão do Analista de Segurança e do Pentester; revisão nos 7 eixos; PR para `dev`.

- [ ] X.1 **Gate humano** (de `v17-curator-agent` 6.99): ligar `autorizar_escrita_instrumento` ao `HumanGate` (`src/human_gate.py`, origem `Source.TERMINAL`/`Source.CLI`) quando existir a escrita em instrumento; a resposta de `ask_researcher`/consultor nunca autoriza; teste de integração do ponto de decisão.
