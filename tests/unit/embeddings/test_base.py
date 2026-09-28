import pytest

from src.embeddings.base import (
    EmbeddingInfo,
    EmbeddingProvider,
    embedding_payload,
    get_embedding_provider,
    reset_embedding_provider,
    text_hash,
)


class _FakeProvider(EmbeddingProvider):
    """Provedor determinístico (hash → vetor) usado apenas em testes."""

    def __init__(self, dim: int = 4, model: str = "fake-model", version: str = "1"):
        self._info = EmbeddingInfo(model=model, version=version, dimension=dim)

    @property
    def info(self) -> EmbeddingInfo:
        return self._info

    def embed_documents(self, texts):
        return [[float(len(t))] * self._info.dimension for t in texts]

    def embed_query(self, text):
        return [float(len(text))] * self._info.dimension


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_embedding_provider()
    yield
    reset_embedding_provider()


@pytest.mark.unit
def test_text_hash_normalizes_surrounding_whitespace():
    assert text_hash("  hello world  ") == text_hash("hello world")


@pytest.mark.unit
def test_text_hash_normalizes_unicode_nfc_vs_nfd():
    nfc = "café"
    nfd = "café"  # "e" + acento agudo combinante
    assert text_hash(nfc) == text_hash(nfd)


@pytest.mark.unit
def test_text_hash_distinguishes_different_content():
    assert text_hash("a") != text_hash("b")


@pytest.mark.unit
def test_text_hash_is_sha256_hex_digest():
    digest = text_hash("qualquer texto")
    assert len(digest) == 64
    int(digest, 16)  # não lança ValueError se for hexadecimal válido


@pytest.mark.unit
def test_embedding_payload_uses_given_provider():
    provider = _FakeProvider(dim=8, model="fake-model", version="2")
    payload = embedding_payload("algum texto de origem", provider=provider)

    assert payload == {
        "embedding_model": "fake-model",
        "embedding_version": "2",
        "embedding_dim": 8,
        "text_hash": text_hash("algum texto de origem"),
    }


@pytest.mark.unit
def test_get_embedding_provider_returns_process_singleton(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr(
        "src.embeddings.fastembed_provider.FastEmbedProvider", lambda: fake
    )

    first = get_embedding_provider()
    second = get_embedding_provider()

    assert first is fake
    assert first is second


@pytest.mark.unit
def test_reset_embedding_provider_forces_reconstruction(monkeypatch):
    instances = [_FakeProvider(model="one"), _FakeProvider(model="two")]
    monkeypatch.setattr(
        "src.embeddings.fastembed_provider.FastEmbedProvider",
        lambda: instances.pop(0),
    )

    first = get_embedding_provider()
    reset_embedding_provider()
    second = get_embedding_provider()

    assert first.info.model == "one"
    assert second.info.model == "two"
    assert first is not second
