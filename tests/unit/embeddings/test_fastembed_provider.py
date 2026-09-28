import numpy as np
import pytest

from src.embeddings.fastembed_provider import FastEmbedProvider

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class _FakeTextEmbedding:
    """Substituto determinístico de `fastembed.TextEmbedding`.

    Não carrega nenhum modelo ONNX real; gera vetores a partir do
    comprimento do texto para permitir asserções determinísticas. Usado para
    testar `FastEmbedProvider` sem depender do peso/tempo de um modelo real —
    o próprio ponto desta mudança é parar de fingir semântica com vetores
    aleatórios em código de *produção*; aqui, em teste, um duplo é esperado.
    """

    def __init__(self, model_name: str, cache_dir: str, local_files_only: bool = False):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only

    def embed(self, documents, batch_size: int = 256, **kwargs):
        for doc in documents:
            yield np.array([float(len(doc))] * 4)

    def query_embed(self, query, **kwargs):
        yield np.array([float(len(query))] * 4)

    @staticmethod
    def list_supported_models():
        return [{"model": _MODEL_NAME, "dim": 4}]


@pytest.fixture
def fake_fastembed(monkeypatch):
    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", _FakeTextEmbedding)
    return fastembed


@pytest.mark.unit
def test_provider_does_not_load_model_until_first_use(fake_fastembed):
    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")
    assert provider._model is None


@pytest.mark.unit
def test_embed_documents_loads_model_and_returns_vectors_in_order(fake_fastembed):
    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")

    vectors = provider.embed_documents(["hi", "hello!"])

    assert provider._model is not None
    assert vectors == [[2.0, 2.0, 2.0, 2.0], [6.0, 6.0, 6.0, 6.0]]


@pytest.mark.unit
def test_embed_documents_empty_list_does_not_load_model(fake_fastembed):
    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")

    assert provider.embed_documents([]) == []
    assert provider._model is None


@pytest.mark.unit
def test_embed_query_returns_single_vector(fake_fastembed):
    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")

    vector = provider.embed_query("abcd")

    assert vector == [4.0, 4.0, 4.0, 4.0]


@pytest.mark.unit
def test_model_is_loaded_only_once_across_calls(fake_fastembed, monkeypatch):
    load_count = {"n": 0}
    original_init = _FakeTextEmbedding.__init__

    def counting_init(self, *args, **kwargs):
        load_count["n"] += 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(_FakeTextEmbedding, "__init__", counting_init)

    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")
    provider.embed_query("a")
    provider.embed_documents(["b", "c"])
    _ = provider.info

    assert load_count["n"] == 1


@pytest.mark.unit
def test_info_reports_model_dimension_and_version(fake_fastembed):
    provider = FastEmbedProvider(model_name=_MODEL_NAME, cache_dir="/tmp/geminiclaw-test-embeddings")

    info = provider.info

    assert info.model == _MODEL_NAME
    assert info.dimension == 4
    assert info.version  # versão do pacote fastembed instalado, não vazia


@pytest.mark.unit
def test_unknown_model_raises_runtime_error(fake_fastembed):
    provider = FastEmbedProvider(model_name="not-a-real-model", cache_dir="/tmp/geminiclaw-test-embeddings")

    with pytest.raises(RuntimeError, match="não encontrado no catálogo"):
        provider.embed_query("x")


@pytest.mark.unit
def test_offline_flag_is_forwarded_to_text_embedding(fake_fastembed):
    provider = FastEmbedProvider(
        model_name=_MODEL_NAME,
        cache_dir="/tmp/geminiclaw-test-embeddings",
        offline=True,
    )

    provider.embed_query("x")

    assert provider._model.local_files_only is True
