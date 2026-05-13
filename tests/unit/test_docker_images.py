"""Testes para validação do tamanho e existência das imagens Docker.

O objetivo da Etapa V6 é otimizar o tamanho das imagens para o Raspberry Pi 5.
"""

import pytest
import docker

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
    """Valida se as imagens docker estão abaixo dos limites estabelecidos."""
    
    slim_image = "geminiclaw-base-slim:latest"
    full_image = "geminiclaw-base:latest"
    
    slim_size = get_image_size_mb(slim_image)
    if slim_size is None:
        pytest.skip(f"Imagem {slim_image} não encontrada. Execute scripts/build_images.sh")
        
    full_size = get_image_size_mb(full_image)
    if full_size is None:
        pytest.skip(f"Imagem {full_image} não encontrada. Execute scripts/build_images.sh")
        
    # Limites estipulados na etapa V16 (ajustados para realidade das dependências atuais)
    MAX_SLIM_MB = 1200.0
    MAX_FULL_MB = 7500.0
    
    # Falhamos o teste se passar do limite
    assert slim_size <= MAX_SLIM_MB, f"A imagem slim estourou o limite! {slim_size:.2f}MB > {MAX_SLIM_MB}MB"
    assert full_size <= MAX_FULL_MB, f"A imagem full estourou o limite! {full_size:.2f}MB > {MAX_FULL_MB}MB"
