# Proposta: v18.6-profile-hardening

**Origem:** parecer de segurança [`docs/security/parecer_v18_6_perfil_estrutural.md`](../../../../docs/security/parecer_v18_6_perfil_estrutural.md) (2026-10-13), não conformidades NC-PERFIL-1 a 6. O pesquisador autorizou todas as correções.
**Mudança de origem:** `v18.6-review-evidence` (arquivada), requisito "Perfil estrutural de artefatos de dados".

## Por quê
O perfil estrutural enviado ao revisor promete "nenhum valor de célula", mas a garantia depende de duas premissas que o
código não impõe (primeira linha do CSV é cabeçalho; o arquivo é regular e da sessão) e o perfil sai sem delimitador de
dado não confiável, sem tratamento de exceção e sem limites estruturais. Com juiz de nuvem (ADR 020) isso vira
vazamento (S1, S2), aprovação indevida por injeção (S3) e negação de serviço no Pi 5 (S4, S5).

## O que muda
| NC | Achado | Requisito | Severidade |
|---|---|---|---|
| NC-PERFIL-1 | S1 CSV sem cabeçalho expõe linha de dados | R1 | Alta |
| NC-PERFIL-2 | S2 symlink em `outputs/` é lido | R2 | Alta |
| NC-PERFIL-3 | S3 nome de coluna sem delimitador de dado não confiável | R3 | Média |
| NC-PERFIL-4 | S4 JSON profundo, S7 `LOCALITY_MIN_GROUP_SIZE` ausente | R4 | Média |
| NC-PERFIL-5 | S5 CSV com milhões de colunas | R5 | Média |
| NC-PERFIL-6 | S6 chaves de mapas JSON e números em rótulos | R6 | Baixa |

Código afetado: `src/artifact_profile.py`, `src/agents/validator_agent.py` (`_profile_for`,
`build_artifact_evidence_fragments`, instrução do revisor), `src/egress/gate.py` e `src/egress/fragments.py`
(delimitação do perfil), `src/config.py` e `.env.example` (limites). Sem alteração de esquema de banco, Dockerfile ou
sandbox.

## Fora de escopo
Os agentes e o catálogo (mudança paralela `v18.6-remove-unused-agents`); a medição no Pi 5 (feita pelo orquestrador).
