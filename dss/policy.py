"""Stable policy and environment protocols shared by model Levels 0-3."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Mapping, Protocol, TypeVar, runtime_checkable

from .allocation import AllocationAction
from .domain import Asset


@dataclass(frozen=True, slots=True)
class FleetState:
    assets: tuple[Asset, ...]
    period: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))
        if isinstance(self.period, bool) or not isinstance(self.period, int) or self.period < 0:
            raise ValueError("period must be a non-negative integer")
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("FleetState asset ids must be unique")

    def without(self, asset_ids: set[str] | frozenset[str]) -> "FleetState":
        return FleetState(
            assets=tuple(a for a in self.assets if a.asset_id not in asset_ids),
            period=self.period,
        )


@dataclass(frozen=True, slots=True)
class DecisionContext:
    pathway_capacities: Mapping[str, float | None] = field(default_factory=dict)
    resource_capacities: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pathway_capacities", MappingProxyType(dict(self.pathway_capacities))
        )
        object.__setattr__(
            self, "resource_capacities", MappingProxyType(dict(self.resource_capacities))
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    policy_name: str
    action: AllocationAction
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_name.strip():
            raise ValueError("policy_name must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


PolicyStateT = TypeVar("PolicyStateT", contravariant=True)
PolicyContextT = TypeVar("PolicyContextT", contravariant=True)
PolicyDecisionT = TypeVar("PolicyDecisionT", covariant=True)


@runtime_checkable
class Policy(Protocol[PolicyStateT, PolicyContextT, PolicyDecisionT]):
    """Level-neutral policy contract; concrete levels choose their own state types."""

    name: str

    def decide(
        self, state: PolicyStateT, context: PolicyContextT
    ) -> PolicyDecisionT:
        """Return one decision for the observed state and context."""


StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT")


@runtime_checkable
class Environment(Protocol, Generic[StateT, ActionT]):
    """Protocol reserved for Level 1+ dynamic simulation environments."""

    def reset(self, *, seed: int | None = None) -> StateT: ...

    def step(self, action: ActionT) -> tuple[StateT, float, bool, Mapping[str, object]]: ...
