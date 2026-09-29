"""Testes de bloqueio de rede interna do WebReaderSkill (Roadmap V16/ADR 014).

Cobre o Requirement "Leitura web sem acesso à rede local" da spec
``agent-runtime`` (openspec/changes/v16-in-process-agents/specs/agent-runtime/spec.md).
"""

import socket
from unittest.mock import patch

import httpx
import pytest

from src.skills.web_reader.skill import (
    WebReaderBlockedError,
    WebReaderSkill,
    guarded_get,
    resolve_and_check_host,
)


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


@pytest.mark.unit
@pytest.mark.asyncio
class TestGuardedGetPinsResolvedIpAgainstRebinding:
    """Prova que ``guarded_get`` fecha a janela de TOCTOU/DNS rebinding do
    finding #2 do review do PR #65: resolver o host e depois deixar o httpx
    resolver de novo por conta própria na conexão real permitia que um DNS
    malicioso respondesse IP público na checagem e IP interno na conexão,
    minutos ou segundos depois. A correção resolve uma única vez e conecta
    diretamente ao IP fixado (``pinned_get``), preservando o ``Host``
    original.
    """

    async def test_connects_to_pinned_ip_and_resolves_only_once(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)
        fake_infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

        with patch("socket.getaddrinfo", return_value=fake_infos) as mock_getaddrinfo:
            async with httpx.AsyncClient(transport=transport) as client:
                response = await guarded_get(client, "http://rebind.example.com/page")

        assert mock_getaddrinfo.call_count == 1
        assert response.status_code == 200
        assert captured[0].url.host == "93.184.216.34"
        assert captured[0].headers["host"] == "rebind.example.com"

    async def test_second_dns_answer_never_reached_because_no_second_resolution(self) -> None:
        """Simula rebinding: se o código re-resolvesse o host na conexão real
        (como o httpx faria sozinho sem pin), a segunda resposta de DNS
        devolveria um IP interno. Como só existe uma resolução, essa segunda
        resposta nunca é consultada e a conexão usa o IP público fixado."""
        call_count = 0

        def fake_getaddrinfo(host, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            # Resposta "rebindada" — só seria alcançada se o código
            # re-resolvesse o host, o que não deve acontecer.
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "93.184.216.34"
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            async with httpx.AsyncClient(transport=transport) as client:
                response = await guarded_get(client, "http://rebind.example.com/page")

        assert response.status_code == 200
        assert call_count == 1

    async def test_redirect_to_internal_host_is_blocked_not_followed(self) -> None:
        """Cenário: um servidor malicioso responde 3xx apontando para um host
        interno para tentar contornar o guard usando o ``follow_redirects``
        do httpx. ``guarded_get`` segue redirecionamentos manualmente e
        reaplica o guard a cada hop — o redirecionamento para host interno
        deve ser bloqueado, não seguido."""

        def fake_getaddrinfo(host, *args, **kwargs):
            if host == "public.example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
            if host == "internal.example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 0))]
            raise AssertionError(f"host inesperado: {host}")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "http://internal.example.com/secret"})

        transport = httpx.MockTransport(handler)

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(WebReaderBlockedError):
                    await guarded_get(client, "http://public.example.com/start")
