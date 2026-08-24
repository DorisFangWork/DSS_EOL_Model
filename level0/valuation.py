"""Pure admissibility, economic-value, and avoided-emissions calculations."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from dss.domain import Asset, PairCoefficients, PathwaySpec

from .instance import ValuationParams


@dataclass(frozen=True, slots=True)
class AdmissibilityResult:
    allowed: bool
    reasons: tuple[str, ...]


def assess_admissibility(asset: Asset, pathway: PathwaySpec) -> AdmissibilityResult:
    reasons: list[str] = []
    if pathway.min_soh is not None and asset.soh < pathway.min_soh:
        reasons.append(f"SOH {asset.soh:.3f} is below {pathway.min_soh:.3f}")
    if pathway.max_safety_class is not None and asset.safety_class > pathway.max_safety_class:
        reasons.append(
            f"safety class {asset.safety_class} exceeds {pathway.max_safety_class}"
        )
    if (
        pathway.allowed_chemistries is not None
        and asset.chemistry not in pathway.allowed_chemistries
    ):
        reasons.append(f"chemistry {asset.chemistry} is not accepted")
    return AdmissibilityResult(allowed=not reasons, reasons=tuple(reasons))


def is_admissible(asset: Asset, pathway: PathwaySpec) -> bool:
    return assess_admissibility(asset, pathway).allowed


def economic_value(asset: Asset, pathway: PathwaySpec, params: ValuationParams) -> float:
    if pathway.pathway_id == "repurpose":
        try:
            multiplier = params.repurpose_chemistry_multiplier[asset.chemistry]
        except KeyError as error:
            raise KeyError(
                f"missing repurpose economic parameter for chemistry {asset.chemistry}"
            ) from error
        revenue = asset.usable_kwh * params.second_life_price_per_kwh * multiplier
        quality_cost = (1.0 - asset.soh) * params.repurpose_quality_penalty
        safety_cost = asset.safety_class * params.safety_handling_cost
        return revenue - params.repurpose_fixed_cost - quality_cost - safety_cost
    if pathway.pathway_id == "recycle":
        try:
            material_value = params.recycling_value_per_kg[asset.chemistry]
        except KeyError as error:
            raise KeyError(
                f"missing recycling economic parameter for chemistry {asset.chemistry}"
            ) from error
        margin_per_kg = material_value - params.recycling_cost_per_kg
        safety_cost = asset.safety_class * params.safety_handling_cost
        return asset.mass_kg * margin_per_kg - safety_cost
    raise KeyError(
        f"no default valuation formula for pathway {pathway.pathway_id}; "
        "supply a custom coefficient table"
    )


def avoided_co2(asset: Asset, pathway: PathwaySpec, params: ValuationParams) -> float:
    if pathway.pathway_id == "repurpose":
        try:
            factor = params.repurpose_co2_kg_per_usable_kwh[asset.chemistry]
        except KeyError as error:
            raise KeyError(
                f"missing repurpose emissions parameter for chemistry {asset.chemistry}"
            ) from error
        return asset.usable_kwh * factor
    if pathway.pathway_id == "recycle":
        try:
            factor = params.recycling_co2_kg_per_kg[asset.chemistry]
        except KeyError as error:
            raise KeyError(
                f"missing recycling emissions parameter for chemistry {asset.chemistry}"
            ) from error
        return asset.mass_kg * factor
    raise KeyError(
        f"no default emissions formula for pathway {pathway.pathway_id}; "
        "supply a custom coefficient table"
    )


def build_pair_coefficients(
    asset: Asset, pathway: PathwaySpec, params: ValuationParams
) -> PairCoefficients:
    admissibility = assess_admissibility(asset, pathway)
    return PairCoefficients(
        asset_id=asset.asset_id,
        pathway_id=pathway.pathway_id,
        admissible=admissibility.allowed,
        economic_value=economic_value(asset, pathway, params) if admissibility.allowed else 0.0,
        avoided_co2_kg=avoided_co2(asset, pathway, params) if admissibility.allowed else 0.0,
        pathway_capacity_use=1.0,
        resource_use=pathway.resource_use,
    )


def build_coefficient_table(
    assets: Iterable[Asset],
    pathways: Iterable[PathwaySpec],
    params: ValuationParams,
) -> Mapping[tuple[str, str], PairCoefficients]:
    table: dict[tuple[str, str], PairCoefficients] = {}
    for asset in assets:
        for pathway in pathways:
            coefficient = build_pair_coefficients(asset, pathway, params)
            table[(asset.asset_id, pathway.pathway_id)] = coefficient
    return MappingProxyType(table)
