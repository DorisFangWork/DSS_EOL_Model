"""Shared, immutable inputs. Capability services do not own scenario state."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from .domain import Asset, PairCoefficients, PathwaySpec, ResourceSpec


def nonnegative(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


@dataclass(frozen=True)
class BatteryRecord:
    """One identified pack; None means unobserved, never an imputed value."""

    asset_id: str
    soh: float | None = None
    chemistry: str | None = None
    safety_class: int | None = None
    nameplate_kwh: float | None = None
    mass_kg: float | None = None
    periods_held: int = 0

    def __post_init__(self):
        if not isinstance(self.asset_id, str) or not self.asset_id.strip():
            raise ValueError("asset_id must be a non-empty string")
        object.__setattr__(self, "asset_id", self.asset_id.strip())
        if self.chemistry is not None:
            if not isinstance(self.chemistry, str) or not self.chemistry.strip():
                raise ValueError("chemistry must be non-empty or null")
            object.__setattr__(self, "chemistry", self.chemistry.strip().upper())
        for name in ("soh", "nameplate_kwh", "mass_kg"):
            value = getattr(self, name)
            if value is not None:
                value = nonnegative(value, name)
                if (name == "soh" and value > 1) or (name != "soh" and value == 0):
                    raise ValueError(f"invalid {name}")
                object.__setattr__(self, name, value)
        for name in ("safety_class", "periods_held"):
            value = getattr(self, name)
            if value is None and name == "safety_class":
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_asset(self) -> Asset:
        missing = [name for name in ("soh", "chemistry", "safety_class", "nameplate_kwh", "mass_kg")
                   if getattr(self, name) is None]
        if missing:
            raise ValueError(f"Model 0 needs complete pack attributes for {self.asset_id}: {missing}")
        return Asset(**vars(self))


@dataclass(frozen=True)
class OptionValue:
    """Externally supplied pair assessments, separate from admission and rankings."""

    asset_id: str
    pathway_id: str
    economic_value: float
    avoided_co2_kg: float
    pathway_capacity_use: float = 1.0
    resource_use: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        checked = PairCoefficients(**vars(self), admissible=True)
        for name in vars(self):
            object.__setattr__(self, name, getattr(checked, name))


@dataclass(frozen=True)
class PlanningScenario:
    scenario_id: str
    version: int
    batteries: tuple[BatteryRecord, ...]
    destinations: tuple[PathwaySpec, ...]
    source: str
    decision_maker: str
    resources: tuple[ResourceSpec, ...] = ()
    values: tuple[OptionValue, ...] = ()
    deferral_costs: Mapping[str, float] = field(default_factory=dict)
    demand_limits: Mapping[str, float] = field(default_factory=dict)
    co2_floor_kg: float | None = None
    currency: str = "SGD"
    periods: int = 1
    horizon: str = "One initial disposition decision window"
    controllable_actions: tuple[str, ...] = ("route", "defer")
    assumptions: tuple[str, ...] = ()
    objective: str = "economic_value"

    def __post_init__(self):
        for name in ("scenario_id", "source", "decision_maker", "currency", "horizon", "objective"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("version", "periods"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("batteries", "destinations", "resources", "values", "assumptions", "controllable_actions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("assumptions", "controllable_actions"):
            if any(not isinstance(v, str) or not v.strip() for v in getattr(self, name)):
                raise ValueError(f"{name} must contain non-empty strings")
        sets = []
        for name, attr in (("batteries", "asset_id"), ("destinations", "pathway_id"), ("resources", "resource_id")):
            ids = [getattr(item, attr) for item in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate identifiers in {name}")
            sets.append(set(ids))
        assets, pathways, resources = sets
        if not assets or not pathways:
            raise ValueError("a scenario needs batteries and destinations")
        pairs = [(v.asset_id, v.pathway_id) for v in self.values]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate pair valuations")
        if any(a not in assets or p not in pathways for a, p in pairs):
            raise ValueError("valuation references an unknown battery or destination")
        for item in (*self.destinations, *self.values):
            if set(item.resource_use) - resources:
                raise ValueError("resource use references an unknown resource")
        for name, known in (("deferral_costs", assets), ("demand_limits", pathways)):
            values = getattr(self, name)
            if set(values) - known:
                raise ValueError(f"unknown identifiers in {name}")
            object.__setattr__(self, name, MappingProxyType({k: nonnegative(v, name) for k, v in values.items()}))
        if self.co2_floor_kg is not None:
            object.__setattr__(self, "co2_floor_kg", nonnegative(self.co2_floor_kg, "co2_floor_kg"))
