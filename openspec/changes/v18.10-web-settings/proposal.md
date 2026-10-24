# Proposta: Configurações do Pesquisador pela Web

**ID:** `v18.10-web-settings` · **Versão:** V18.10 · **Capacidade:** `web-interface`
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §6.8 (decisão do pesquisador, 2026-10-24); ADR 011 e ADR 017 (provedores e papéis); AGENTS.md §1.7 (segredos só por variável de ambiente)
**Depende de:** `v18.10-web-skeleton`. Paralela a painel, artefatos e grafo.

## Por quê

O pesquisador ajusta com frequência limites de tempo, tokens e custo, os modelos por papel e as chaves de API dos provedores. Hoje isso exige editar o `.env` à mão. A página de configurações faz isso com segurança, sem expor o que é infraestrutura.

## O que muda

- **Novo:** arquivo de sobreposição do pesquisador, `RESEARCHER_ENV_FILE` (padrão `config/researcher.env`, fora do versionamento, permissão `0600`), carregado por `src/config.py` **depois** do `.env` e só com nomes da lista fechada (design §1); nome fora da lista no arquivo faz a inicialização falhar.
- **Novo:** `src/web/settings.py` e `routes/settings.py`: ler valores efetivos (com a origem: padrão, `.env` ou sobreposição), validar e gravar na sobreposição, remover uma sobreposição (volta ao `.env`).
- **Novo:** página Configurações (grupos Limites, Modelos e Provedores, Chaves de API).
- **Fora do escopo:** banco de dados, Qdrant, `WEB_*`, egresso e localidade, sandbox, gate, credenciais de infraestrutura, variáveis de experimento (`VERDICT_*`, benchmark); edição do `.env` em si.

## Impacto

- **Código:** `src/config.py` (carga da sobreposição com lista fechada e validação por nome); arquivos novos em `src/web/` e `frontend/`.
- **Efeito:** valores novos valem para a **próxima** pesquisa e consulta (cada processo de sessão lê a configuração ao iniciar); a sessão em execução não muda. A página diz isso.
- **Schema:** nenhum.

## Aprovações necessárias

- **Segredos gravados pela web:** chaves de API passam a poder ser gravadas pela página, no arquivo de sobreposição (nunca no banco, nunca de volta ao navegador). Exige aprovação explícita (AGENTS.md §1.7).
- **Lista fechada do design §1:** aprovar os nomes.
- **`.gitignore`:** `config/researcher.env`.
