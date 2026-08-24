# DSS prototype repository rules

- This repository is the shared PhD decision-support codebase for model Levels 0-3.
- Preserve Level 0 as the deterministic, one-period, exact myopic benchmark.
- Add later levels by extending the shared `dss` protocols; do not copy or mutate Level 0 logic.
- Keep domain/admissibility/valuation logic outside solver construction.
- Keep empirical or confidential data outside the repository. Tests and examples use synthetic data.
- Every model change must add or update mathematical, reduction, and feasibility tests.
- Generated `results/` and `figures/` are reproducible outputs and are not source files.
- Do not import historical `archive/` implementations into active packages.

