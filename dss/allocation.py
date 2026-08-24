"""Solver-independent allocation actions and evaluation records."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AllocationAction:
    """One declared action per asset; ``None`` means defer this period."""

    assignments: Mapping[str, str | None]

    def __post_init__(self) -> None:
        normalized: dict[str, str | None] = {}
        for asset_id, pathway_id in self.assignments.items():
            key = str(asset_id).strip()
            if not key:
                raise ValueError("allocation contains an empty asset id")
            if key in normalized:
                raise ValueError(f"duplicate allocation for asset {key}")
            if pathway_id is None:
                normalized[key] = None
            else:
                pathway = str(pathway_id).strip()
                if not pathway:
                    raise ValueError(f"empty pathway id for asset {key}")
                normalized[key] = pathway
        object.__setattr__(self, "assignments", MappingProxyType(normalized))

    @property
    def deferred_asset_ids(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.assignments.items() if v is None))


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Authoritative score and feasibility report recomputed from an action."""

    feasible: bool
    economic_objective: float
    gross_pathway_value: float
    deferral_cost: float
    avoided_co2_kg: float
    pathway_use: Mapping[str, float]
    resource_use: Mapping[str, float]
    violations: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pathway_use", MappingProxyType(dict(self.pathway_use)))
        object.__setattr__(self, "resource_use", MappingProxyType(dict(self.resource_use)))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

