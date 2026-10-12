"""Cliente de containers simulado para os testes de imagens por plataforma."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import docker


class FakeImages:
    def __init__(self, local: dict[str, str] | None = None, pull_arch: str | None = None,
                 build_arch: str | None = None) -> None:
        self.local = dict(local or {})  # referência -> arquitetura
        self.pull_arch = pull_arch
        self.build_arch = build_arch
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, reference: str):
        if reference not in self.local:
            raise docker.errors.ImageNotFound(reference)
        return SimpleNamespace(id=f"sha256:{reference}", attrs={"Architecture": self.local[reference]})

    def pull(self, reference: str, **kw):
        self.calls.append(("pull", {"reference": reference, **kw}))
        arch = self.pull_arch or kw["platform"].split("/")[1]
        self.local[reference] = arch
        return self.get(reference)

    def build(self, **kw):
        self.calls.append(("build", kw))
        arch = self.build_arch or kw["platform"].split("/")[1]
        self.local[kw["tag"]] = arch
        return self.get(kw["tag"]), iter(())


class FakeClient:
    def __init__(self, arch: str = "aarch64", local: dict[str, str] | None = None, **kw: Any) -> None:
        self.arch = arch
        self.images = FakeImages(local, **kw)

    def info(self) -> dict[str, str]:
        return {"OSType": "linux", "Architecture": self.arch}

    def ping(self) -> bool:
        return True
