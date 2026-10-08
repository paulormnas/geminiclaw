"""Testes para validação do tamanho da imagem do sandbox de código.

Os agentes rodam como processo local (ADR 014); a única imagem de execução é a do sandbox
(``SANDBOX_IMAGE``, padrão ``code-sandbox:latest``). O limite abaixo é um guarda de tamanho
para o Raspberry Pi 5 (ADR 018: imagem enxuta, abaixo de 1 GB).
"""

import docker
import pytest

from src import config


def get_image_size_mb(image_name: str) -> float | None:
    """Retorna o tamanho da imagem em MB, ou None se não existir."""
    try:
        client = docker.from_env()
        image = client.images.get(image_name)
        return image.attrs["Size"] / (1024 * 1024)
    except docker.errors.ImageNotFound:
        return None
    except Exception as e:
        pytest.skip(f"Erro ao acessar o Docker daemon: {e}")
        return None

@pytest.mark.unit
def test_docker_image_sizes():
    """Valida se a imagem do sandbox está abaixo do limite estabelecido."""

    sandbox_image = config.SANDBOX_IMAGE

    sandbox_size = get_image_size_mb(sandbox_image)
    if sandbox_size is None:
        pytest.skip(f"Imagem {sandbox_image} não encontrada. Execute scripts/build_images.sh")

    # Limite da v16-sandbox-slim-image (design: estimativa abaixo de 1 GB; medir no Pi 5)
    MAX_SANDBOX_MB = 1024.0

    assert sandbox_size <= MAX_SANDBOX_MB, (
        f"A imagem do sandbox estourou o limite! {sandbox_size:.2f}MB > {MAX_SANDBOX_MB}MB (ver ADR 018)"
    )
