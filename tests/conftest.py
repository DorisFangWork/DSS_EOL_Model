from __future__ import annotations

import pytest

from dss.domain import Asset, PairCoefficients, PathwaySpec, ResourceSpec
from level0.instance import StaticAllocationInstance


def _instance(assets, pathways, coefficients, deferral=2.0, resources=()):
    return StaticAllocationInstance(
        assets=tuple(assets),
        pathways=tuple(pathways),
        resources=tuple(resources),
        coefficients={(c.asset_id, c.pathway_id): c for c in coefficients},
        deferral_costs={a.asset_id: deferral for a in assets},
        scenario_label="analytic_fixture",
        metadata={"data_kind": "analytic_test"},
    )


@pytest.fixture
def scarcity_instance():
    assets = (
        Asset("H", 0.95, "NMC", 0, 60, 400),
        Asset("M", 0.80, "NMC", 0, 60, 400),
        Asset("L", 0.60, "NMC", 0, 60, 400),
    )
    pathways = (
        PathwaySpec("repurpose", "Repurpose", capacity=1, min_soh=0.70),
        PathwaySpec("recycle", "Recycle", capacity=None),
    )
    coefficients = (
        PairCoefficients("H", "repurpose", True, 10, 2),
        PairCoefficients("H", "recycle", True, 9, 5),
        PairCoefficients("M", "repurpose", True, 8, 9),
        PairCoefficients("M", "recycle", True, 0, 1),
        PairCoefficients("L", "repurpose", False, 0, 0),
        PairCoefficients("L", "recycle", True, 4, 3),
    )
    return _instance(assets, pathways, coefficients)


@pytest.fixture
def lp_dual_instance():
    assets = (
        Asset("A", 0.8, "NMC", 0, 50, 300),
        Asset("B", 0.8, "NMC", 0, 50, 300),
    )
    pathways = (PathwaySpec("process", "Process"),)
    resources = (ResourceSpec("machine", "Machine", 3),)
    coefficients = (
        PairCoefficients("A", "process", True, 2, 0, resource_use={"machine": 2}),
        PairCoefficients("B", "process", True, 2, 0, resource_use={"machine": 2}),
    )
    return _instance(assets, pathways, coefficients, deferral=0, resources=resources)


@pytest.fixture
def emissions_instance():
    asset = Asset("A", 0.8, "NMC", 0, 50, 300)
    pathways = (
        PathwaySpec("economic", "Economic"),
        PathwaySpec("green", "Green"),
    )
    coefficients = (
        PairCoefficients("A", "economic", True, 10, 0),
        PairCoefficients("A", "green", True, 8, 10),
    )
    return _instance((asset,), pathways, coefficients, deferral=100)


@pytest.fixture
def cohort_instance():
    assets = tuple(Asset(f"A{i}", 0.8, "NMC", 0, 50, 300) for i in range(3))
    pathways = (
        PathwaySpec("repurpose", "Repurpose", capacity=2),
        PathwaySpec("recycle", "Recycle"),
    )
    coefficients = tuple(
        coefficient
        for asset in assets
        for coefficient in (
            PairCoefficients(asset.asset_id, "repurpose", True, 5, 5),
            PairCoefficients(asset.asset_id, "recycle", True, 1, 1),
        )
    )
    return _instance(assets, pathways, coefficients, deferral=5)

