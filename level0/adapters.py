"""Adapters exposing Level 0 decisions through the shared DSS policy protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dss.allocation import AllocationAction
from dss.policy import DecisionContext, FleetState, PolicyDecision

from .instance import StaticAllocationInstance
from .model import SolverOptions, solve_milp


InstanceBuilder = Callable[[FleetState, DecisionContext], StaticAllocationInstance]
ActionBuilder = Callable[[StaticAllocationInstance], AllocationAction]


def fixed_instance_builder(template: StaticAllocationInstance) -> InstanceBuilder:
    """Build a context-adjusted instance for the same static fleet.

    Level 1 should inject its own dynamic-state-to-static-instance builder rather
    than placing transition knowledge inside Level 0.
    """

    def build(state: FleetState, context: DecisionContext) -> StaticAllocationInstance:
        if state.assets != template.assets:
            raise ValueError(
                "fixed_instance_builder requires the complete unchanged template fleet; "
                "inject a Level-specific builder when attributes or membership can change"
            )
        return template.with_capacities(
            pathway_capacities=context.pathway_capacities,
            resource_capacities=context.resource_capacities,
        )

    return build


@dataclass(frozen=True, slots=True)
class MyopicMILPPolicy:
    instance_builder: InstanceBuilder
    solver_options: SolverOptions = SolverOptions()
    name: str = "myopic_milp"

    def decide(self, state: FleetState, context: DecisionContext) -> PolicyDecision:
        instance = self.instance_builder(state, context)
        result = solve_milp(instance, self.solver_options)
        if not result.optimal or result.action is None or result.evaluation is None:
            raise RuntimeError(f"myopic MILP did not solve optimally: {result.status}")
        return PolicyDecision(
            policy_name=self.name,
            action=result.action,
            metadata={
                "economic_objective": result.evaluation.economic_objective,
                "avoided_co2_kg": result.evaluation.avoided_co2_kg,
                "solver_status": result.status,
            },
        )


@dataclass(frozen=True, slots=True)
class FunctionPolicyAdapter:
    name: str
    instance_builder: InstanceBuilder
    action_builder: ActionBuilder

    def decide(self, state: FleetState, context: DecisionContext) -> PolicyDecision:
        instance = self.instance_builder(state, context)
        return PolicyDecision(self.name, self.action_builder(instance))
