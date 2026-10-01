"""Garante que a suíte não alcança as APIs pagas dos provedores LLM."""

import socket

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("host", ["api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com"])
def test_paid_hosts_are_blocked(host):
    with pytest.raises(AssertionError, match="API paga"):
        socket.getaddrinfo(host, 443)


def test_other_hosts_still_resolve_locally():
    assert socket.getaddrinfo("localhost", 80)
