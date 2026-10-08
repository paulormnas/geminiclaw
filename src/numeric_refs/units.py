"""Lista fechada de unidades reconhecidas e álgebra simples de unidades (design §2.2 e §3)."""

from __future__ import annotations

from fractions import Fraction

# SI e derivadas comuns, mais "%" e "pp" (pontos percentuais). Lista fechada: ampliar exige alterar o design.
KNOWN_UNITS: frozenset[str] = frozenset(
    {
        "%", "pp",
        "m", "mm", "cm", "km", "µm", "um", "nm", "pm",
        "s", "ms", "µs", "ns", "min", "h", "d",
        "kg", "g", "mg", "µg", "t",
        "Hz", "kHz", "MHz", "GHz",
        "V", "mV", "kV", "A", "mA", "W", "mW", "kW", "J", "kJ", "MJ", "Wh", "kWh",
        "K", "°C", "°F", "Pa", "kPa", "MPa", "bar", "N", "kN",
        "mol", "L", "mL", "dB", "rad", "°",
        "B", "KB", "MB", "GB", "TB", "px",
    }
)

DIMENSIONLESS: dict[str, int] = {}


def is_known_unit(token: str) -> bool:
    return token in KNOWN_UNITS


# Uma unidade composta é um mapa {unidade: expoente}; ``None`` = unidade não informada (propaga).
Unit = dict[str, Fraction] | None


def unit_mul(a: Unit, b: Unit) -> Unit:
    if a is None or b is None:
        return None
    out = dict(a)
    for name, exp in b.items():
        out[name] = out.get(name, Fraction(0)) + exp
        if out[name] == 0:
            del out[name]
    return out


def unit_div(a: Unit, b: Unit) -> Unit:
    if a is None or b is None:
        return None
    return unit_mul(a, {name: -exp for name, exp in b.items()})


def unit_pow(a: Unit, exponent: Fraction) -> Unit:
    if a is None:
        return None
    return {name: exp * exponent for name, exp in a.items() if exp * exponent != 0}


def unit_from_text(text: str | None) -> Unit:
    """Unidade simples a partir do texto (``None``/vazio = não informada)."""
    if not text:
        return None
    return {text: Fraction(1)}


def unit_text(unit: Unit) -> str | None:
    """Texto da unidade (``""`` = adimensional; ``None`` = não informada)."""
    if unit is None:
        return None
    if not unit:
        return ""
    numerator = [_fmt(n, e) for n, e in unit.items() if e > 0]
    denominator = [_fmt(n, -e) for n, e in unit.items() if e < 0]
    top = "·".join(numerator) if numerator else "1"
    return top if not denominator else f"{top}/{'·'.join(denominator)}"


def _fmt(name: str, exp: Fraction) -> str:
    return name if exp == 1 else f"{name}^{exp}"


def same_unit(a: Unit, b: Unit) -> bool:
    return a == b
