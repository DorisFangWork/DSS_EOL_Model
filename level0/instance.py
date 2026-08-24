"""Level 0 instance records and deterministic synthetic scenario factories."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import numpy as np

from dss.domain import Asset, PairCoefficients, PathwaySpec, ResourceSpec


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "level0" / "default.json"


def _freeze_float_mapping(values: Mapping[str, float], name: str) -> Mapping[str, float]:
    copied: dict[str, float] = {}
    for key, value in values.items():
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError(f"{name}[{key}] must be finite")
        copied[str(key)] = numeric
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class ValuationParams:
    """Illustrative, auditable parameters for the synthetic Level 0 scenario."""

    second_life_price_per_kwh: float = 58.0
    repurpose_fixed_cost: float = 720.0
    repurpose_quality_penalty: float = 1_000.0
    safety_handling_cost: float = 180.0
    repurpose_chemistry_multiplier: Mapping[str, float] = field(
        default_factory=lambda: {"NMC": 1.0, "LFP": 0.95}
    )
    recycling_value_per_kg: Mapping[str, float] = field(
        default_factory=lambda: {"NMC": 3.20, "LFP": 1.75}
    )
    recycling_cost_per_kg: float = 0.65
    deferral_penalty: float = 300.0
    repurpose_co2_kg_per_usable_kwh: Mapping[str, float] = field(
        default_factory=lambda: {"NMC": 92.0, "LFP": 78.0}
    )
    recycling_co2_kg_per_kg: Mapping[str, float] = field(
        default_factory=lambda: {"NMC": 2.40, "LFP": 1.45}
    )

    def __post_init__(self) -> None:
        scalar_names = (
            "second_life_price_per_kwh",
            "repurpose_fixed_cost",
            "repurpose_quality_penalty",
            "safety_handling_cost",
            "recycling_cost_per_kg",
            "deferral_penalty",
        )
        for name in scalar_names:
            value = float(getattr(self, name))
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        for name in (
            "repurpose_chemistry_multiplier",
            "recycling_value_per_kg",
            "repurpose_co2_kg_per_usable_kwh",
            "recycling_co2_kg_per_kg",
        ):
            frozen = _freeze_float_mapping(getattr(self, name), name)
            if any(value < 0 for value in frozen.values()):
                raise ValueError(f"{name} values must be non-negative")
            object.__setattr__(self, name, frozen)


@dataclass(frozen=True, slots=True)
class StaticAllocationInstance:
    """Complete solver-independent definition of a one-period problem."""

    assets: tuple[Asset, ...]
    pathways: tuple[PathwaySpec, ...]
    resources: tuple[ResourceSpec, ...]
    coefficients: Mapping[tuple[str, str], PairCoefficients]
    deferral_costs: Mapping[str, float]
    scenario_label: str = "level0"
    co2_floor_kg: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "pathways", tuple(self.pathways))
        object.__setattr__(self, "resources", tuple(self.resources))
        asset_ids = [asset.asset_id for asset in self.assets]
        pathway_ids = [pathway.pathway_id for pathway in self.pathways]
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset ids must be unique")
        if len(pathway_ids) != len(set(pathway_ids)):
            raise ValueError("pathway ids must be unique")
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("resource ids must be unique")
        if not self.scenario_label.strip():
            raise ValueError("scenario_label must not be empty")
        if any(not pathway.terminal for pathway in self.pathways):
            raise ValueError("all Level 0 pathways must be terminal within the focal system")

        known_resources = set(resource_ids)
        for pathway in self.pathways:
            unknown = set(pathway.resource_use) - known_resources
            if unknown:
                raise ValueError(
                    f"pathway {pathway.pathway_id} references unknown resources: {sorted(unknown)}"
                )

        expected = {(asset_id, pathway_id) for asset_id in asset_ids for pathway_id in pathway_ids}
        provided = set(self.coefficients)
        if expected != provided:
            missing = sorted(expected - provided)
            extra = sorted(provided - expected)
            raise ValueError(f"coefficient table mismatch; missing={missing}, extra={extra}")
        coefficient_copy: dict[tuple[str, str], PairCoefficients] = {}
        for key, coefficient in self.coefficients.items():
            if key != (coefficient.asset_id, coefficient.pathway_id):
                raise ValueError(f"coefficient key {key} does not match its record")
            unknown = set(coefficient.resource_use) - known_resources
            if unknown:
                raise ValueError(f"coefficient {key} references unknown resources: {sorted(unknown)}")
            coefficient_copy[key] = coefficient

        if set(self.deferral_costs) != set(asset_ids):
            raise ValueError("deferral_costs must contain exactly one value per asset")
        deferral_copy: dict[str, float] = {}
        for asset_id, value in self.deferral_costs.items():
            numeric = float(value)
            if not isfinite(numeric) or numeric < 0:
                raise ValueError("deferral costs must be finite and non-negative")
            deferral_copy[asset_id] = numeric

        if self.co2_floor_kg is not None:
            floor = float(self.co2_floor_kg)
            if not isfinite(floor) or floor < 0:
                raise ValueError("co2_floor_kg must be finite and non-negative")
            object.__setattr__(self, "co2_floor_kg", floor)

        object.__setattr__(self, "coefficients", MappingProxyType(coefficient_copy))
        object.__setattr__(self, "deferral_costs", MappingProxyType(deferral_copy))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def asset_by_id(self) -> Mapping[str, Asset]:
        return MappingProxyType({asset.asset_id: asset for asset in self.assets})

    @property
    def pathway_by_id(self) -> Mapping[str, PathwaySpec]:
        return MappingProxyType({pathway.pathway_id: pathway for pathway in self.pathways})

    @property
    def resource_by_id(self) -> Mapping[str, ResourceSpec]:
        return MappingProxyType({resource.resource_id: resource for resource in self.resources})

    def with_co2_floor(self, co2_floor_kg: float | None) -> "StaticAllocationInstance":
        return replace(self, co2_floor_kg=co2_floor_kg)

    def with_capacities(
        self,
        *,
        pathway_capacities: Mapping[str, float | None] | None = None,
        resource_capacities: Mapping[str, float] | None = None,
        scenario_label: str | None = None,
    ) -> "StaticAllocationInstance":
        pathway_capacities = pathway_capacities or {}
        resource_capacities = resource_capacities or {}
        unknown_pathways = set(pathway_capacities) - set(self.pathway_by_id)
        unknown_resources = set(resource_capacities) - set(self.resource_by_id)
        if unknown_pathways or unknown_resources:
            raise KeyError(
                f"unknown capacity keys: pathways={sorted(unknown_pathways)}, "
                f"resources={sorted(unknown_resources)}"
            )
        pathways = tuple(
            replace(p, capacity=pathway_capacities.get(p.pathway_id, p.capacity))
            for p in self.pathways
        )
        resources = tuple(
            replace(r, capacity=resource_capacities.get(r.resource_id, r.capacity))
            for r in self.resources
        )
        return replace(
            self,
            pathways=pathways,
            resources=resources,
            scenario_label=scenario_label or self.scenario_label,
        )


def generate_fleet(
    size: int = 60,
    seed: int = 20260802,
    *,
    soh_mean: float = 0.735,
    soh_sd: float = 0.055,
    max_periods_held: int = 6,
) -> tuple[Asset, ...]:
    """Generate an illustrative fleet using a local deterministic PCG64 stream."""

    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("size must be a positive integer")
    if (
        isinstance(max_periods_held, bool)
        or not isinstance(max_periods_held, int)
        or max_periods_held < 0
    ):
        raise ValueError("max_periods_held must be a non-negative integer")
    rng = np.random.Generator(np.random.PCG64(seed))
    soh = np.clip(rng.normal(soh_mean, soh_sd, size), 0.52, 0.92)
    chemistry = rng.choice(np.array(["NMC", "LFP"]), size=size, p=[0.66, 0.34])
    safety = rng.choice(np.array([0, 1, 2]), size=size, p=[0.72, 0.23, 0.05])
    nameplate = np.clip(rng.normal(70.0, 11.5, size), 42.0, 98.0)
    mass_noise = rng.normal(0.0, 18.0, size)
    mass = np.clip(nameplate * np.where(chemistry == "NMC", 6.8, 7.4) + mass_noise, 280.0, 760.0)
    periods_held = rng.integers(0, max_periods_held + 1, size=size)

    return tuple(
        Asset(
            asset_id=f"BAT-{index + 1:04d}",
            soh=round(float(soh[index]), 6),
            chemistry=str(chemistry[index]),
            safety_class=int(safety[index]),
            nameplate_kwh=round(float(nameplate[index]), 4),
            mass_kg=round(float(mass[index]), 4),
            periods_held=int(periods_held[index]),
        )
        for index in range(size)
    )


def build_instance(
    *,
    assets: Iterable[Asset],
    pathways: Iterable[PathwaySpec],
    resources: Iterable[ResourceSpec],
    valuation: ValuationParams | None = None,
    co2_floor_kg: float | None = None,
    scenario_label: str = "level0",
    metadata: Mapping[str, object] | None = None,
) -> StaticAllocationInstance:
    from .valuation import build_coefficient_table

    asset_tuple = tuple(assets)
    pathway_tuple = tuple(pathways)
    resource_tuple = tuple(resources)
    params = valuation or ValuationParams()
    coefficients = build_coefficient_table(asset_tuple, pathway_tuple, params)
    return StaticAllocationInstance(
        assets=asset_tuple,
        pathways=pathway_tuple,
        resources=resource_tuple,
        coefficients=coefficients,
        deferral_costs={asset.asset_id: params.deferral_penalty for asset in asset_tuple},
        scenario_label=scenario_label,
        co2_floor_kg=co2_floor_kg,
        metadata={"valuation": params, **dict(metadata or {})},
    )


def default_instance(
    *,
    size: int | None = None,
    seed: int | None = None,
    repurpose_capacity: float | None = None,
    test_bay_capacity: float | None = None,
    repurpose_min_soh: float | None = None,
    soh_mean: float | None = None,
    soh_sd: float | None = None,
    max_periods_held: int | None = None,
    co2_floor_kg: float | None = None,
) -> StaticAllocationInstance:
    """Build the canonical demonstration, with explicit overrides for experiments."""

    config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    using_configured_size = size is None
    size = int(config["fleet_size"] if size is None else size)
    seed = int(config["seed"] if seed is None else seed)
    repurpose_capacity = float(
        config["repurpose_capacity"] if repurpose_capacity is None else repurpose_capacity
    )
    test_bay_capacity = float(
        config["test_bay_capacity"] if test_bay_capacity is None else test_bay_capacity
    )
    repurpose_min_soh = float(
        config["repurpose_min_soh"] if repurpose_min_soh is None else repurpose_min_soh
    )
    soh_mean = float(config["soh_mean"] if soh_mean is None else soh_mean)
    soh_sd = float(config["soh_sd"] if soh_sd is None else soh_sd)
    max_periods_held = int(
        config["max_periods_held"] if max_periods_held is None else max_periods_held
    )
    assets = generate_fleet(
        size=size,
        seed=seed,
        soh_mean=soh_mean,
        soh_sd=soh_sd,
        max_periods_held=max_periods_held,
    )
    pathways = (
        PathwaySpec(
            pathway_id="repurpose",
            name="Second-life repurposing",
            capacity=repurpose_capacity,
            min_soh=repurpose_min_soh,
            max_safety_class=1,
            allowed_chemistries=("NMC", "LFP"),
            resource_use={"test_bay": 1.0, "handling": 1.0},
        ),
        PathwaySpec(
            pathway_id="recycle",
            name="Material recycling",
            capacity=None,
            min_soh=None,
            max_safety_class=2,
            allowed_chemistries=("NMC", "LFP"),
            resource_use={"handling": 0.5},
        ),
    )
    resources = (
        ResourceSpec("test_bay", "Diagnostic test-bay capacity", test_bay_capacity, "packs"),
        ResourceSpec("handling", "General handling capacity", float(size), "pack-equivalents"),
    )
    return build_instance(
        assets=assets,
        pathways=pathways,
        resources=resources,
        co2_floor_kg=co2_floor_kg,
        scenario_label=(
            str(config["scenario_label"]) if using_configured_size else f"demo_{size}packs"
        ),
        metadata={
            "seed": seed,
            "data_kind": str(config["data_kind"]),
            "currency": str(config["units"]["currency"]),
            "co2_unit": str(config["units"]["emissions"]),
            "units": dict(config["units"]),
            "interpretation": str(config["interpretation"]),
            "config_path": str(DEFAULT_CONFIG_PATH.relative_to(DEFAULT_CONFIG_PATH.parents[2])),
            "generator": {
                "soh_mean": soh_mean,
                "soh_sd": soh_sd,
                "max_periods_held": max_periods_held,
                "rng": "PCG64",
            },
        },
    )
