# DSS_EOL — DSS prototype

This repository supports an industry-oriented EV battery disposition DSS intended
for future practical use and commercialisation, alongside a separate PhD research
programme under the service–recovery motivation. Validated research can strengthen
the DSS's modular capabilities.

The DSS has three independently callable, interacting capabilities:

| Capability | Current implementation |
| --- | --- |
| Battery admissibility | Configurable entry rules; eligible, ineligible or undetermined, with reasons |
| Destination determination | Economic or avoided-emissions comparison, explicit ties and advisory preferences |
| Flow allocation | Model 0: exact deterministic one-period allocation under shared constraints |

Integrated execution uses eligibility constraints and jointly selects destinations
and quantities. Destination rankings remain advisory. The previous Level 1–3
development ladder is provisional, not the application's structure.

## Modular planner quick start

Open this folder in PyCharm and select `.venv/Scripts/python.exe` as the project
interpreter. In its terminal, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run planner\app.py --server.address 127.0.0.1
```

Alternatively run `planner/run_planner.ps1`. For a PyCharm run configuration, use
module `streamlit`, parameters `run planner/app.py --server.address 127.0.0.1`,
and this repository as the working directory. The local URL appears in the terminal.
If the UI dependency is missing, install the optional dependency using
`python -m pip install -e ".[planner]"` in the Python 3.11 environment.

Choose the existing synthetic 60-pack scenario or the two-pack capacity example.
The application has Dashboard, Decision workspace, Configuration, Results &
comparison, and Model & assumptions pages. Configuration edits take effect only
after **Apply configuration**. Completed runs retain their snapshots for
baseline-versus-alternative comparisons and downloads within the session.
Use any individual capability or Integrated decision. Scenario JSON supports
complete custom assessments; CSV/manual entry supports battery observations.
Imported packs use synthetic valuation formulas only when explicitly selected.
Saved runs and full scenario snapshots remain in ignored `results/dss/runs.sqlite`.

The existing `demo/app.py` remains the dedicated Level 0 research demonstration.
The new `planner/app.py` is the entry point for the three-capability system.

See [the architecture and API guide](docs/modular_dss.md) for contracts,
execution modes, persistence, and the incremental file mapping.

For personal online viewing, deploy `planner/cloud_app.py` with Python 3.11 and
`planner/requirements.txt`. This entrypoint offers synthetic examples and downloads
and disables data uploads and server-side history. App access must separately be
set to private in Streamlit Community Cloud. See the
[private deployment instructions](docs/streamlit_deployment.md).
See [the application walkthrough](docs/modular_dss.md#application-walkthrough) for
navigation, capability interactions, and a two-pack comparison exercise.

For later changes, follow [Update the live app from PyCharm](docs/streamlit_deployment.md#update-the-live-app-from-pycharm):
edit, test, commit, push to `streamlit-private`, then verify online.

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
