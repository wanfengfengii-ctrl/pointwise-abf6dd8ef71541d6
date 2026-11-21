from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType


@dataclass(frozen=True)
class Unit:
    symbol: str
    dimension: str


UNIT_CATALOG = MappingProxyType({
    'g/L': Unit('g/L', 'mass concentration'),
    'mg/L': Unit('mg/L', 'mass concentration'),
    'NTU': Unit('NTU', 'turbidity'),
})


def resolve_unit(symbol):
    if type(symbol) is not str or symbol not in UNIT_CATALOG:
        raise ValueError(f'unknown unit {symbol!r}')
    return UNIT_CATALOG[symbol]


def require_same_unit(actual, expected):
    if actual != expected:
        raise ValueError(f'incompatible units {actual!r} and {expected!r}')


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    unit: Unit

    def __post_init__(self):
        if not isinstance(self.value, Fraction) or not isinstance(self.unit, Unit):
            raise ValueError('quantity requires an exact value and a unit')
        require_same_unit(self.unit, resolve_unit(self.unit.symbol))
