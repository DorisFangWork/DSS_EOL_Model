# Development-plan alignment

## Purpose

This repository is the shared technical foundation for model Levels 0-3. Its
architecture protects the thesis logic:

```text
static fleet allocation
    -> carry-over and degradation
    -> value of dynamic policy
    -> uncertainty and realistic shared constraints
    -> one focused methodological extension
```

Each level adds an identifiable mechanism and must reduce to the previous level
when that mechanism is disabled.

## Stable cross-level contracts

`dss.policy` defines four concepts that later levels reuse:

1. `FleetState`: the currently held assets and decision period.
2. `DecisionContext`: observed capacities and scenario metadata.
3. `PolicyDecision`: one action per asset plus declared policy metrics.
4. `Policy` and `Environment` protocols: interchangeable policies and dynamic
   simulation environments.

Level 0 supplies `MyopicMILPPolicy`, which solves the one-period allocation
problem for the current state. At Level 1 it can be called every period without
modification. Exact DP then becomes another policy behind the same interface.
Levels 2-3 may add rolling-horizon, ADP, decomposition, RMAB-inspired, or RL
policies only after computational diagnosis.

## Level 0 contract

Level 0 is deterministic, static and asset-level. It includes heterogeneous
assets, pathway admissibility, economic and environmental coefficients, pathway
and shared-resource capacity, terminal allocation, and a one-period deferral
penalty. It excludes arrivals, state transitions, continuation value, stochastic
processes, risk measures, inspection, partial observability and learning.

Its research outputs are a verified exact benchmark, feasible allocation matrix,
capacity opportunity-cost evidence, baseline comparisons, an emissions frontier,
and measured cohort-aggregation error.

## Rules for future levels

- Level 1 adds time only and proves at least one transparent dynamic-versus-myopic
  difference using an exact small state space.
- Level 2 adds realistic uncertainty and scale while retaining exact Level 1
  instances as ground truth.
- Level 3 is optional. If Levels 0-2 reveal a material unresolved limitation, it
  selects one extension; it is not an accumulation of fashionable methods.
- Every later model includes a reduction test to the preceding level.
