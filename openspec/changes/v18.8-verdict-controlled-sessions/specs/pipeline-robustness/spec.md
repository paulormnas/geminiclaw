# Delta: pipeline-robustness

## ADDED Requirements

### Requirement: Nome de métrica composto em critério quantitativo
O sistema SHALL reconhecer como métrica conhecida o nome citado em um critério quantitativo quando alguma das palavras do nome, separadas por espaço, `_`, `-` ou `.`, é um alias de `_METRIC_ALIASES` (`acuracia_teste_media` vale `accuracy`, `holdout_acuracia` vale `accuracy`). O reconhecimento SHALL só decidir se o critério é quantitativo e de qual métrica; a escolha da chave em `metrics.json` continua nas regras de qualificador e de chave qualificada existentes, e o sistema SHALL NOT avaliar o critério contra uma chave de outro conjunto de avaliação (`cv_accuracy_mean` não vale para "acurácia de teste").

#### Scenario: Chave composta em snake_case
- **GIVEN** o critério "acuracia_teste_media >= 0.93 para confirmar h1" e `metrics.json` com `acuracia_teste_media` = 0,615
- **WHEN** a subtarefa é revisada
- **THEN** o critério é avaliado de forma determinística contra `metrics.json` e reprova com o valor real 0,615

#### Scenario: Critério condicional
- **GIVEN** o critério "se bloqueio_tipos = false: acuracia_teste_media >= 0.93" e `metrics.json` com `acuracia_teste_media` = 0,615
- **WHEN** a subtarefa é revisada
- **THEN** a comparação `acuracia_teste_media >= 0.93` é avaliada e a condição `bloqueio_tipos = false` não é tomada como comparação de métrica

#### Scenario: Reprovação só por limiar vira resultado negativo
- **GIVEN** uma subtarefa de teste com hipótese, o critério do cenário "Chave composta em snake_case" não atendido e os demais critérios aprovados pelo revisor
- **WHEN** a subtarefa é revisada com `NEGATIVE_RESULT_AS_PROGRESS` ligado
- **THEN** o resultado da revisão é `resultado_negativo`, a ingestão grava o experimento como `sucesso` e o `Resultado` entra no veredito como evidência negativa

#### Scenario: Qualificador de outro conjunto
- **GIVEN** o critério "acuracia_teste_media >= 0.93" e `metrics.json` com só `cv_accuracy_mean` = 0,90
- **WHEN** a subtarefa é revisada
- **THEN** o critério não é avaliado contra `cv_accuracy_mean` e o resultado é o de métrica nomeada ausente

#### Scenario: Nome sem alias
- **GIVEN** o critério "contagem_graficos >= 3", sem alias de métrica entre as palavras do nome
- **WHEN** o critério é classificado
- **THEN** o critério não é quantitativo por métrica e segue para o revisor LLM como critério de contagem
