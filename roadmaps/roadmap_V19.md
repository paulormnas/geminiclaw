# Roadmap V19 — Controle de Equipamentos Físicos

## Objetivo

Permitir que o assistente controle equipamentos de laboratório por uma interface
MHS-compatível, conforme a spec já existente
[`roadmaps/specs/G7_equipment_control_mhs.md`](specs/G7_equipment_control_mhs.md)
(renumerada de V16.1 para V19.1 pelo ADR 010).

## Dependências

- V18 concluída (ciclo de hipóteses) — decisão do pesquisador: equipamentos entram depois do
  ciclo de hipóteses e antes da federação.

## Tarefas

A decomposição está na spec G7. Antes de implementar, revisar a G7 à luz das decisões
posteriores a ela:

- [ ] **ADR 014:** agentes rodam no host; comandos a equipamentos passam por ferramenta
  tipada, nunca por código gerado executado no host.
- [ ] **ADR 015:** instrumentos entram no grafo como `Abordagem(tipo="instrumento")`; falhas de
  equipamento são causa `infraestrutura` no veredito (§9.3).
- [ ] **ADR 010:** limites de uso e continuidade valem também para experimentos físicos.
- [ ] Converter a G7 para o formato OpenSpec (`openspec/changes/v19-equipment-control/`).

## Validação da Etapa

- [ ] Critérios de validação da própria spec G7.
- [ ] Avaliação do Analista de Segurança (acesso a hardware).
