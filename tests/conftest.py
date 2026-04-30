import os
import pytest

# Define variáveis de ambiente necessárias para a importação do src.config nos testes unitários
os.environ["GENAI_API_KEY"] = "dummy_key_for_testing"
os.environ["DEFAULT_MODEL"] = "gemini-3-flash-preview"
os.environ["AGENT_TIMEOUT_SECONDS"] = "120"
# DATABASE_URL: valor fictício para testes unitários (sem banco real)
# Testes de integração sobrescrevem com uma URL real
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost:5432/test_geminiclaw"
)
os.environ["SEARCH_CACHE_TTL_SECONDS"] = "3600"

# Sinaliza para pular testes de integração que consomem cota de API durante a suíte completa
os.environ["CI_SKIP_INTEGRATION"] = "1"

@pytest.fixture(scope="session", autouse=True)
def global_container_cleanup_check():
    """Garante que não sobrou nenhum container do projeto após rodar os testes."""
    yield
    try:
        import docker
        client = docker.from_env()
        # all=True checks stopped containers as well
        containers = client.containers.list(filters={"label": "project=geminiclaw"}, all=True)
        if containers:
            container_ids = [c.short_id for c in containers]
            for c in containers:
                try:
                    c.remove(force=True)
                except Exception:
                    pass
            pytest.fail(f"Vazamento de containers detectado apos os testes: {container_ids}")
    except Exception as e:
        print(f"Aviso na verificacao de containers: {e}")
