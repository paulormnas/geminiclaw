"""Testes de bloqueio de rede interna do WebReaderSkill (Roadmap V16/ADR 014).

Cobre o Requirement "Leitura web sem acesso à rede local" da spec
``agent-runtime`` (openspec/changes/v16-in-process-agents/specs/agent-runtime/spec.md).
"""

import socket
from unittest.mock import patch

import pytest

from src.skills.web_reader.skill import WebReaderSkill, resolve_and_check_host


@pytest.mark.unit
@pytest.mark.asyncio
class TestResolveAndCheckHost:
    """Testes unitários da função de checagem de host, isolados de httpx."""

    async def test_loopback_ip_literal_is_blocked(self) -> None:
        reason = await resolve_and_check_host("127.0.0.1")
        assert reason is not None
        assert "127.0.0.1" in reason

    async def test_cloud_metadata_ip_is_blocked(self) -> None:
        reason = await resolve_and_check_host("169.254.169.254")
        assert reason is not None

    async def test_private_rfc1918_ip_is_blocked(self) -> None:
        reason = await resolve_and_check_host("192.168.0.10")
        assert reason is not None

    async def test_link_local_ip_is_blocked(self) -> None:
        reason = await resolve_and_check_host("169.254.1.1")
        assert reason is not None

    async def test_domain_resolving_to_private_ip_is_blocked(self) -> None:
        """Cenário: Nome que resolve para IP privado."""
        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.10", 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            reason = await resolve_and_check_host("internal.example.corp")
        assert reason is not None
        assert "192.168.0.10" in reason

    async def test_dns_failure_fails_open(self) -> None:
        """Falha de resolução não é tratada como bloqueio de segurança."""
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("no such host")):
            reason = await resolve_and_check_host("host-inexistente.invalid")
        assert reason is None

    async def test_public_ip_is_not_blocked(self) -> None:
        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        with patch("socket.getaddrinfo", return_value=fake_infos):
            reason = await resolve_and_check_host("dns.google")
        assert reason is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestWebReaderSkillBlocksInternalAddresses:
    """Testes de integração da skill: nenhuma requisição HTTP deve ocorrer para hosts bloqueados."""

    async def test_loopback_url_rejected_without_http_request(self) -> None:
        skill = WebReaderSkill()
        with patch("httpx.AsyncClient") as mock_client_cls:
            result = await skill.run(url="http://127.0.0.1:5432/")

        mock_client_cls.assert_not_called()
        assert result.success is False
        assert "bloqueado" in result.error.lower()

    async def test_cloud_metadata_url_rejected(self) -> None:
        skill = WebReaderSkill()
        with patch("httpx.AsyncClient") as mock_client_cls:
            result = await skill.run(url="http://169.254.169.254/latest/meta-data/")

        mock_client_cls.assert_not_called()
        assert result.success is False

    async def test_private_ip_url_rejected(self) -> None:
        skill = WebReaderSkill()
        with patch("httpx.AsyncClient") as mock_client_cls:
            result = await skill.run(url="http://192.168.1.1/admin")

        mock_client_cls.assert_not_called()
        assert result.success is False
