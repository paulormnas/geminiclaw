"""Versão dos modelos por execução do benchmark (v18.6-models-gemini4-gpt6, ADR 019 §6, ADR 020 §7).

O dado vem do ``allocation_profile`` da sessão mestra. ``versao_efetiva`` é o literal ``desconhecida`` quando o
provedor não a informa: nunca se deduz do nome pedido.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.llm import pricing
from src.llm.versions import UNKNOWN_VERSION

NO_DATA = "n/d"


def collect_models(profile: dict | None) -> dict[str, dict]:
    """``{papel: {pedido, familia, versao_efetiva}}`` a partir do ``allocation_profile`` (vazio sem perfil)."""
    papeis = (profile or {}).get("papeis") or {}
    return {
        role: {
            "pedido": entry.get("provedor_modelo"),
            "familia": entry.get("familia_modelo"),
            "versao_efetiva": entry.get("versao_efetiva") or UNKNOWN_VERSION,
        }
        for role, entry in papeis.items()
    }


def collect_prices(models: dict[str, dict]) -> dict[str, dict]:
    """Preços aplicados (US$ por 1M tokens) de cada modelo pedido, com a vigência; modelo sem preço fica ``None``."""
    prices: dict[str, dict | None] = {}
    for info in models.values():
        spec = info.get("pedido")
        if not spec or spec in prices:
            continue
        provider, _, model = spec.partition("/")
        price = pricing.get_price(provider, model)
        if price is None:
            prices[spec] = None
            continue
        prices[spec] = {
            "entrada": price.input,
            "saida": price.output,
            "cache": price.input if price.cached_input is None else price.cached_input,
            "vigencia_ate": price.promo_until.isoformat() if price.promo_until else None,
        }
    return prices


def version_marks(models: dict[str, dict]) -> list[str]:
    """Avisos ``versao_desconhecida:<papel>`` do placar (conferência manual; não são anomalia de parada)."""
    return [f"versao_desconhecida:{role}" for role, info in models.items() if info["versao_efetiva"] == UNKNOWN_VERSION]


def execution_record(profile: dict | None, now: datetime | None = None) -> dict:
    """Campos aditivos do resultado: ``modelos``, ``precos`` e ``data_execucao`` (UTC)."""
    models = collect_models(profile)
    moment = now or datetime.now(timezone.utc)
    return {"modelos": models, "precos": collect_prices(models), "data_execucao": moment.date().isoformat()}


def db_allocation_profile(session_id: str) -> dict | None:
    """``payload["allocation_profile"]`` da sessão mestra, ou ``None`` se indisponível."""
    try:
        from src.session.manager import SessionManager

        payload = getattr(SessionManager().get(session_id), "payload", None)
        profile = payload.get("allocation_profile") if isinstance(payload, dict) else None
        return profile if isinstance(profile, dict) else None
    except Exception:  # noqa: BLE001 — banco indisponível não invalida a medição
        return None


# ---------------------------------------------------------------- relatório


def render_models(results: list[dict]) -> str:
    """Tabela "Modelos e versões" por combinação e repetição (resultado antigo, sem os campos, mostra ``n/d``)."""
    rows = [
        "| Combinação | Rep. | Papel | Modelo pedido | Versão efetiva | Data | Preço (US$/1M: entrada/saída/cache) |\n"
        "|---|---|---|---|---|---|---|"
    ]
    for r in results:
        if r.get("status") == "skipped":
            continue
        models, prices = r.get("modelos"), r.get("precos") or {}
        if not models:
            blank = " | ".join([NO_DATA] * 4)
            rows.append(f"| {r['name']} | {r.get('repeticao', 1)} | - | {blank} |")
            continue
        for role, info in models.items():
            price = prices.get(info.get("pedido"))
            if price:
                until = f", até {price['vigencia_ate']}" if price.get("vigencia_ate") else ""
                cell = f"{price['entrada']}/{price['saida']}/{price['cache']}{until}"
            else:
                cell = NO_DATA
            rows.append(
                f"| {r['name']} | {r.get('repeticao', 1)} | {role} | {info.get('pedido', NO_DATA)} | "
                f"{info.get('versao_efetiva', NO_DATA)} | {r.get('data_execucao', NO_DATA)} | {cell} |"
            )
    return "\n".join(rows)


def version_warnings(results: list[dict]) -> list[str]:
    """Avisos de versão efetiva diferente entre repetições da mesma combinação (por papel)."""
    seen: dict[tuple[str, str], dict[str, int]] = {}
    for r in results:
        for role, info in (r.get("modelos") or {}).items():
            versions = seen.setdefault((r["name"], role), {})
            versions.setdefault(info.get("versao_efetiva", NO_DATA), r.get("repeticao", 1))
    return [
        f"AVISO: a combinação {name} teve versões efetivas diferentes no papel {role}: " + " e ".join(sorted(versions))
        for (name, role), versions in sorted(seen.items())
        if len(versions) > 1
    ]
