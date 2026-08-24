# Level 0 — static fleet-allocation foundation

## Research question

When is within-period fleet coordination necessary, rather than a collection of
independent battery-level pathway choices?

## Mathematical model

For battery assets `i`, admissible pathways `p`, and shared resources `r`:

```text
x[i,p] = 1 if asset i is assigned to pathway p; 0 otherwise
d[i]   = 1 if asset i is deferred in this decision period; 0 otherwise
```

The economic objective is:

```text
max sum(value[i,p] * x[i,p]) - sum(deferral_cost[i] * d[i])
```

subject to:

```text
sum(x[i,p] over admissible p) + d[i] = 1                 for every asset i
sum(pathway_use[i,p] * x[i,p]) <= pathway_capacity[p]    for bounded p
sum(resource_use[i,p,r] * x[i,p]) <= resource_capacity[r]
sum(avoided_co2[i,p] * x[i,p]) >= optional_CO2_floor
```

Only admissible asset-pathway variables are constructed. Deferral always remains
available, ensuring a feasible one-period action even when all terminal capacity
is zero.

## Module boundaries

- `instance.py`: validated static instances and deterministic synthetic fleet.
- `valuation.py`: pure admissibility, economic value and emissions coefficients.
- `evaluation.py`: authoritative solver-independent feasibility and scoring.
- `model.py`: isolated PuLP/CBC MILP, LP relaxation and emissions endpoint.
- `policies.py`: diagnostic independent choice and feasible operating rules.
- `adapters.py`: Level 0 behind the shared DSS policy interface.
- `cohorts.py`: aggregation sufficiency, integer cohort solve and lifted loss.
- `analysis.py`: tidy evidence tables and reproducibility manifest.
- `verify.py`: mathematical, reduction and call-order checks.

## Interpretation discipline

- `independent_best` ignores coupling capacities and is usually infeasible. It is a
  diagnostic ceiling, not an implementable baseline.
- The MILP must dominate every **feasible** heuristic.
- LP relaxation is an upper bound and the only source used for shadow prices.
- Exact status requires both the PuLP model status and solution certificate;
  time-limited or positive-gap solves are not accepted by the Level 0 API.
- A zero dual does not prove geometric slack. Use, slack and dual are all reported.
- LP marginal values apply to fractional marginal capacity; they are not
  automatically the value of one indivisible additional pack.
- The emissions floor traces a trade-off without inventing a money/CO2 weight.
- Cohort objective values are lifted back to asset decisions and independently
  reevaluated before loss is reported.

Level 0 contains no arrivals, transition, degradation, continuation value, MDP,
RL, inspection, partial observability or risk measure. Those mechanisms belong to
later evidence gates.
