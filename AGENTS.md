# DSS prototype repository rules

- This repository supports two interconnected targets: a modular DSS prototype and focused PhD research, likely within flow allocation.
- Admissibility, destination determination, and flow allocation are interacting capabilities, not a fixed sequence or research progression.
- Preserve Level 0 as the deterministic, one-period, exact myopic benchmark.
- Model 0 belongs to flow allocation; retain the `level0` import paths and verified benchmark semantics during incremental integration.
- Extend shared `dss` contracts for new capabilities. Later research mechanisms remain provisional; do not impose the former Level 1-3 ladder.
- Keep domain/admissibility/valuation logic outside solver construction.
- Keep empirical or confidential data outside the repository. Tests and examples use synthetic data.
- Every model change must add or update mathematical, reduction, and feasibility tests.
- Generated `results/` and `figures/` are reproducible outputs and are not source files.
- Do not import historical `archive/` implementations into active packages.

