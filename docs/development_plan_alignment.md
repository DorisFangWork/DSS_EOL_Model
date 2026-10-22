# Development-plan alignment

## Two interconnected targets

The SLR informs both the DSS prototype and the PhD research. The prototype spans
battery admissibility, destination determination, and flow allocation. The PhD
topic is likely to focus on a specific allocation problem; its mechanism and
research question remain open. Service–recovery supplies the overarching
motivation for both targets.

The capabilities can operate separately or together. They are overlapping
decision responsibilities, not a fixed sequence or a hierarchy of research levels.
An allocation model can jointly determine destinations and quantities.

## Implemented foundation

- Shared planning contracts hold pack observations, destinations, resource and
  compatible-demand limits, pair assessments, assumptions and provenance.
- Admission evaluates configurable SOH, safety-class and chemistry requirements.
  Missing relevant observations remain explicitly undetermined.
- Destination comparison reports economic or avoided-emissions preferences.
  Mandatory admission requirements cannot be compensated by favourable scores.
- Model 0 supplies exact one-period allocation and independent outcome evaluation.
- The planner supports four execution modes, scenario editing, saved snapshots,
  and descriptive comparisons after changed information or assumptions.

See [modular_dss.md](modular_dss.md) for software contracts and acceptance examples.

## Level 0 contract

Model 0 belongs to flow allocation. Its existing `level0` import paths,
deterministic mathematics, solver certificates, and research outputs are preserved.
`dss.flow` adapts shared scenarios to its established instance contract.
Illustrative valuation formulas remain in `level0.valuation`; shared services
accept explicit pair assessments.

It represents heterogeneous packs, pathway eligibility, economic and emissions
coefficients, destination and shared-resource capacity, an optional emissions
floor, and current-period deferral costs. It allocates initial disposition within
one decision window. Its `terminal` flag denotes leaving that model boundary.

Arrivals, degradation, continued service, diagnostic actions, qualification
fallback, material yields, crediting requirements, and optimal reassessment timing
require additional models and data.

Its research outputs are a verified exact benchmark, feasible allocation matrix,
capacity opportunity-cost evidence, baseline comparisons, an emissions frontier,
and measured cohort-aggregation error.

## Future investigations and extensions

Time, information acquisition, preparation, uncertainty and reassessment remain
candidate mechanisms. The former fixed Level 1–3 progression is superseded as a
development commitment. Each selected mechanism needs its own research question,
comparison basis, and validation plan.

New allocation models should reuse shared contracts and retain a Model 0 reduction
test where that mathematical relationship is valid. The existing `Policy` and
`Environment` protocols remain available for future dynamic investigations;
their presence does not commit the programme to an MDP.

Circularity assessment and upstream data integrations can supply documented
assessments through the scenario boundary. Current values are SGD and avoided
kg CO2e. A future indicator requires a unit, system boundary, source, and declared
decision role before it affects ranking or allocation.
