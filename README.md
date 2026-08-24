# PhD DSS prototype

This repository is the common modelling and experimentation core for the PhD
research programme on **asset-informed fleet-level allocation of retired EV
batteries**. It is organised by increasing problem complexity rather than by
favoured algorithms.

| Level | Problem increment | Canonical model/role |
| --- | --- | --- |
| 0 | one period, heterogeneous assets, admissibility, shared capacity | exact static MILP and myopic benchmark |
| 1 | time, passive carry-over, degradation, repeated arrivals | small exact MDP/DP for mechanism identification |
| 2 | realistic stochastic arrivals, markets, capacities and heterogeneity | core fleet-level MDP/CMDP and scalable policy evaluation |
| 3 | optionally, one limitation revealed by Level 2 | focused risk, information, scalability, or reliability extension if earned |

Level 0 is fully implemented. Later levels must reuse the stable interfaces in
`dss/` and retain Level 0's semantics and verified public benchmark APIs as a
reduction case; ordinary maintenance does not require freezing its source files.

## Level 0 quick start

Python 3.11 is required. This laptop has an isolated 3.11.9 runtime in `.python/`
and a ready project environment in `.venv/`; both are local and ignored by Git.

Run the verified environment directly:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m level0.run_demo
.\.venv\Scripts\python.exe scripts\visualizations\plot_level0_results.py
```

To recreate the virtual environment after installing or restoring Python 3.11:

```powershell
.\.python\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pip install -e . --no-deps
python -m pytest tests -q
python -m level0.run_demo
python scripts\visualizations\plot_level0_results.py
```

The visualization command writes deterministic analysis tables under
`results/level0/` and figures under `figures/level0/`.

## Research boundaries

- The default fleet and all parameter values are synthetic and illustrative.
- Results demonstrate mechanisms and validate the model; they are not OEM
  forecasts or calibrated capacity recommendations.
- Economic value is maximised directly. Avoided emissions are reported separately
  and may be imposed as a constraint to trace an economic-environmental frontier.
- Cohorts are an approximation whose admissibility and value loss must be measured,
  not assumed harmless.

See [docs/development_plan_alignment.md](docs/development_plan_alignment.md) and
[level0/README.md](level0/README.md) for the research and mathematical contracts.
