# Design: Embeddings Locais e Versionados

## Interface

```python
# src/embeddings/base.py
@dataclass(frozen=True)
class EmbeddingInfo:
    model: str        # ex.: "sentence-transformers/all-MiniLM-L6-v2"
    version: str      # versão do artefato do modelo (ex.: revisão/hash do ONNX) ou do fastembed
    dimension: int    # ex.: 384

class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def info(self) -> EmbeddingInfo: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...

def get_embedding_provider() -> EmbeddingProvider   # singleton por processo
def text_hash(text: str) -> str                      # sha256 do texto normalizado (strip, NFC)
def embedding_payload(text: str) -> dict             # {"embedding_model", "embedding_version",
                                                     #  "embedding_dim", "text_hash"}
```

- Métodos síncronos: o cálculo é CPU-bound; chamadores assíncronos usam
  `asyncio.to_thread`.
- `FastEmbedProvider` (`src/embeddings/fastembed_provider.py`) usa
  `fastembed.TextEmbedding(model_name=config.EMBEDDING_MODEL, cache_dir=config.EMBEDDING_CACHE_DIR)`.
  Carregamento preguiçoso no primeiro uso; lotes de `EMBEDDING_BATCH_SIZE` (default 32).
- **Somente backends locais** podem ser registrados. Não existe fábrica de embeddings que
  aceite URL de serviço externo — a garantia do ADR 011 é estrutural, não de configuração.
- O download inicial do modelo (HuggingFace) não envia conteúdo de pesquisa; em produção, o
  modelo é pré-baixado por `scripts/setup_pi.sh` e `EMBEDDING_OFFLINE=true` impede downloads
  em tempo de execução.

## Metadados no Qdrant

Todo `PointStruct.payload` gravado pelos indexadores inclui `embedding_payload(text)`. O texto
de origem permanece recuperável:

- deep search: o payload já guarda o texto do trecho (manter);
- documentos: o texto está em `document_chunks` (PostgreSQL), referenciado pelo `chunk_id` no
  payload (manter).

## Compatibilidade de coleção

Na inicialização (`_ensure_collection`), o indexador compara a dimensão da coleção com
`info.dimension`:

- igual → segue;
- diferente → **não** recria a coleção automaticamente; registra erro claro orientando
  `geminiclaw embeddings reindex --collection <nome>` e desabilita a busca semântica daquela
  coleção até a reindexação (a skill responde com aviso em vez de resultados aleatórios).

`search()` filtra pontos cujo `embedding_model`/`embedding_version` difere do atual e registra
aviso com a contagem de pontos desatualizados.

## Reindexação

`geminiclaw embeddings reindex [--collection NOME] [--yes]`:

1. Lista os pontos desatualizados (modelo/versão diferentes, ou sem metadados).
2. Pede confirmação (a menos que `--yes`).
3. Se a dimensão mudou: recria a coleção; senão, reescreve os pontos.
4. Recupera o texto de origem (payload ou `document_chunks`) e grava vetores novos com
   metadados.
5. Relatório final: pontos atualizados, ignorados (sem texto de origem) e tempo.

## Configuração nova (`src/config.py`)

| Variável | Default |
|---|---|
| `EMBEDDING_MODEL` (já existe) | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_CACHE_DIR` | `~/.cache/<app>/embeddings` (nome do app via config, não literal) |
| `EMBEDDING_BATCH_SIZE` | `32` |
| `EMBEDDING_OFFLINE` | `false` (setup do Pi define `true` após o download) |

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum. |
| Agentes & Prompts | Skills de busca passam a devolver resultados relevantes. |
| Sandboxes & Containers | Nenhum (embeddings rodam no host, ADR 014). |
| Persistência | Vetores regenerados; payload ganha 4 campos. Sem mudança de schema PostgreSQL. |
| Segurança | Garantia estrutural de que nenhum texto sai para provedor externo; modo offline. |
| Testes & Telemetria | Testes com provedor falso determinístico; teste de integração com fastembed marcado para rodar só se o modelo estiver em cache. Tempo de embedding registrado. |

## Riscos

- **Tempo de embedding no Pi 5** em lotes grandes de documentos — mitigação: lotes, execução
  em thread, log de throughput.
- **fastembed indisponível para ARM64 em alguma versão** — verificar wheel ARM64 antes de
  fixar a versão (tarefa 1.1).
