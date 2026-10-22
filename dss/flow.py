"""Model 0 adapter. Other allocation models can implement the same scenario boundary."""

from dataclasses import replace

from .admissibility import validate_eligibility
from .domain import PairCoefficients
from .planning import BatteryRecord, OptionValue, PlanningScenario


def to_model0(scenario: PlanningScenario, eligibility, unknown_policy="reject"):
    from level0.instance import StaticAllocationInstance

    if unknown_policy not in {"reject", "exclude"}:
        raise ValueError("unknown_policy must be reject or exclude")
    if scenario.periods != 1 or scenario.objective != "economic_value":
        raise ValueError("Model 0 supports one period and the economic_value objective")
    if set(scenario.controllable_actions) != {"route", "defer"}:
        raise ValueError("Model 0 requires exactly the controllable actions route and defer")
    records = validate_eligibility(scenario, eligibility)
    unresolved = [r for r in records if r.status == "undetermined"]
    if unresolved and unknown_policy == "reject":
        raise ValueError("Unresolved eligibility: complete the evidence or explicitly select exclusion")
    assets = tuple(b.to_asset() for b in scenario.batteries)
    if set(scenario.deferral_costs) != {a.asset_id for a in assets}:
        raise ValueError("Model 0 needs one explicit deferral cost per battery")
    values = {(v.asset_id, v.pathway_id): v for v in scenario.values}
    coefficients = {}
    for r in records:
        key = (r.asset_id, r.pathway_id)
        allowed = r.status == "eligible"
        value = values.get(key)
        if allowed and value is None:
            raise ValueError(f"missing assessment values for eligible pair {key}")
        coefficients[key] = PairCoefficients(
            r.asset_id, r.pathway_id, allowed,
            value.economic_value if allowed else 0.0,
            value.avoided_co2_kg if allowed else 0.0,
            pathway_capacity_use=value.pathway_capacity_use if value else 1.0,
            resource_use=value.resource_use if value else {},
        )
    destinations = []
    for destination in scenario.destinations:
        demand = scenario.demand_limits.get(destination.pathway_id)
        if demand is not None:
            if any(v.pathway_capacity_use != 1 for v in scenario.values if v.pathway_id == destination.pathway_id):
                raise ValueError("pack demand limits require unit pathway capacity use")
            capacity = demand if destination.capacity is None else min(demand, destination.capacity)
            destination = replace(destination, capacity=capacity)
        destinations.append(destination)
    return StaticAllocationInstance(
        assets, tuple(destinations), scenario.resources, coefficients, scenario.deferral_costs,
        scenario_label=scenario.scenario_id, co2_floor_kg=scenario.co2_floor_kg,
        metadata={"currency": scenario.currency, "source": scenario.source,
                  "unknown_policy": unknown_policy, "excluded_undetermined_pairs": len(unresolved)},
    )


def allocate(scenario: PlanningScenario, eligibility, unknown_policy="reject"):
    from level0.evaluation import evaluate_action
    from level0.model import solve_milp

    instance = to_model0(scenario, eligibility, unknown_policy)
    result = solve_milp(instance)
    report = evaluate_action(instance, result.action) if result.action is not None else None
    if report is not None and not report.feasible:
        raise RuntimeError("Model 0 allocation failed independent feasibility evaluation")
    return result, report


def scenario_from_model0(instance, *, version=1, source="Supplied Model 0 instance"):
    """Preserve all supplied coefficients; their admissibility is supplied separately."""
    return PlanningScenario(
        instance.scenario_label, version,
        tuple(BatteryRecord(**{name: getattr(a, name) for name in BatteryRecord.__dataclass_fields__})
              for a in instance.assets),
        instance.pathways, source, "Automotive OEM (provisional initial-disposition perspective)",
        resources=instance.resources,
        values=tuple(OptionValue(c.asset_id, c.pathway_id, c.economic_value, c.avoided_co2_kg,
                                 c.pathway_capacity_use, c.resource_use) for c in instance.coefficients.values()),
        deferral_costs=instance.deferral_costs, co2_floor_kg=instance.co2_floor_kg,
        currency=str(instance.metadata.get("currency", "SGD")),
        assumptions=("Pair values and resource consumption are supplied assessments.",
                     "One-period deferral has a current cost and no continuation value."),
    )


def synthetic_scenario():
    """Existing 60-pack scenario with illustrative values for every pair, even if ineligible."""
    from level0.instance import default_instance
    from level0.valuation import economic_value, avoided_co2

    instance = default_instance()
    scenario = scenario_from_model0(instance, source="Synthetic Model 0 generator; seed 20260802")
    params = instance.metadata["valuation"]
    values = tuple(OptionValue(a.asset_id, p.pathway_id,
                              economic_value(a, p, params), avoided_co2(a, p, params),
                              resource_use=p.resource_use)
                   for a in instance.assets for p in instance.pathways)
    return replace(scenario, values=values, assumptions=scenario.assumptions + (
        "Synthetic values in SGD and kg CO2e; illustrative avoided emissions, not calibrated lifecycle benefits.",
        "Assignment does not establish productive service, recovered material, or credited supply.",
    ))


def value_synthetic_batteries(scenario: PlanningScenario, batteries):
    """Explicit opt-in to Model 0 formulas for imported packs; never an empirical calibration."""
    from level0.instance import ValuationParams
    from level0.valuation import economic_value, avoided_co2

    if scenario.currency != "SGD":
        raise ValueError("Illustrative Model 0 formulas use SGD; supply explicit values for another currency")
    params = ValuationParams()
    batteries = tuple(batteries)
    assets = tuple(b.to_asset() for b in batteries)
    values = tuple(OptionValue(a.asset_id, p.pathway_id, economic_value(a, p, params),
                              avoided_co2(a, p, params), resource_use=p.resource_use)
                   for a in assets for p in scenario.destinations)
    return replace(scenario, batteries=batteries, values=values,
                   deferral_costs={a.asset_id: params.deferral_penalty for a in assets},
                   source=scenario.source + "; valuations: illustrative Model 0 default formulas/v1 (SGD, kg CO2e)",
                   assumptions=scenario.assumptions + ("Imported packs use synthetic Model 0 valuation factors, not calibrated assessments.",))
