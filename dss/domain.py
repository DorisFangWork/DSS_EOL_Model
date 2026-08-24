"""Immutable level-neutral records used by all model levels."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Mapping


def _nonempty(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be a non-empty string")
    return cleaned


def _finite_nonnegative(value: float, field_name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return numeric


def _finite_positive(value: float, field_name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return numeric


def _freeze_nonnegative_mapping(
    values: Mapping[str, float], field_name: str
) -> Mapping[str, float]:
    frozen: dict[str, float] = {}
    for key, value in values.items():
        clean_key = _nonempty(str(key), f"{field_name} key")
        frozen[clean_key] = _finite_nonnegative(value, f"{field_name}[{clean_key}]")
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class Asset:
    """One retired battery pack at a decision epoch."""

    asset_id: str
    soh: float
    chemistry: str
    safety_class: int
    nameplate_kwh: float
    mass_kg: float
    periods_held: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _nonempty(self.asset_id, "asset_id"))
        object.__setattr__(self, "chemistry", _nonempty(self.chemistry, "chemistry").upper())
        soh = float(self.soh)
        if not isfinite(soh) or not 0 <= soh <= 1:
            raise ValueError("soh must be a finite fraction from 0 to 1")
        object.__setattr__(self, "soh", soh)
        if (
            isinstance(self.safety_class, bool)
            or not isinstance(self.safety_class, int)
            or self.safety_class < 0
        ):
            raise ValueError("safety_class must be a non-negative integer")
        if (
            isinstance(self.periods_held, bool)
            or not isinstance(self.periods_held, int)
            or self.periods_held < 0
        ):
            raise ValueError("periods_held must be a non-negative integer")
        object.__setattr__(
            self, "nameplate_kwh", _finite_positive(self.nameplate_kwh, "nameplate_kwh")
        )
        object.__setattr__(self, "mass_kg", _finite_positive(self.mass_kg, "mass_kg"))

    @property
    def usable_kwh(self) -> float:
        return self.soh * self.nameplate_kwh


@dataclass(frozen=True, slots=True)
class PathwaySpec:
    """A represented terminal pathway and its simple acceptance rules."""

    pathway_id: str
    name: str
    capacity: float | None = None
    min_soh: float | None = None
    max_safety_class: int | None = None
    allowed_chemistries: tuple[str, ...] | None = None
    resource_use: Mapping[str, float] = field(default_factory=dict)
    terminal: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "pathway_id", _nonempty(self.pathway_id, "pathway_id"))
        object.__setattr__(self, "name", _nonempty(self.name, "pathway name"))
        if self.capacity is not None:
            object.__setattr__(
                self, "capacity", _finite_nonnegative(self.capacity, "pathway capacity")
            )
        if self.min_soh is not None:
            threshold = float(self.min_soh)
            if not isfinite(threshold) or not 0 <= threshold <= 1:
                raise ValueError("min_soh must be a fraction from 0 to 1")
            object.__setattr__(self, "min_soh", threshold)
        if self.max_safety_class is not None and (
            isinstance(self.max_safety_class, bool)
            or not isinstance(self.max_safety_class, int)
            or self.max_safety_class < 0
        ):
            raise ValueError("max_safety_class must be a non-negative integer")
        if self.allowed_chemistries is not None:
            allowed = tuple(sorted({_nonempty(v, "chemistry").upper() for v in self.allowed_chemistries}))
            if not allowed:
                raise ValueError("allowed_chemistries cannot be empty")
            object.__setattr__(self, "allowed_chemistries", allowed)
        object.__setattr__(
            self,
            "resource_use",
            _freeze_nonnegative_mapping(self.resource_use, "resource_use"),
        )


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    resource_id: str
    name: str
    capacity: float
    unit: str = "asset-equivalent"

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _nonempty(self.resource_id, "resource_id"))
        object.__setattr__(self, "name", _nonempty(self.name, "resource name"))
        object.__setattr__(self, "unit", _nonempty(self.unit, "resource unit"))
        object.__setattr__(self, "capacity", _finite_nonnegative(self.capacity, "resource capacity"))


@dataclass(frozen=True, slots=True)
class PairCoefficients:
    """Solver-ready coefficients for one asset-pathway pair."""

    asset_id: str
    pathway_id: str
    admissible: bool
    economic_value: float
    avoided_co2_kg: float
    pathway_capacity_use: float = 1.0
    resource_use: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _nonempty(self.asset_id, "asset_id"))
        object.__setattr__(self, "pathway_id", _nonempty(self.pathway_id, "pathway_id"))
        economic = float(self.economic_value)
        if not isfinite(economic):
            raise ValueError("economic_value must be finite")
        object.__setattr__(self, "economic_value", economic)
        object.__setattr__(
            self, "avoided_co2_kg", _finite_nonnegative(self.avoided_co2_kg, "avoided_co2_kg")
        )
        object.__setattr__(
            self,
            "pathway_capacity_use",
            _finite_nonnegative(self.pathway_capacity_use, "pathway_capacity_use"),
        )
        object.__setattr__(
            self,
            "resource_use",
            _freeze_nonnegative_mapping(self.resource_use, "pair resource_use"),
        )
