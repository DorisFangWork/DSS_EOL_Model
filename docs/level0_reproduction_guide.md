# Level 0 reconstruction record

This implementation was independently reconstructed in August 2026 from the
preserved Level 0 development/reproduction guide and the active PhD research
vault. The original source repository remained on another laptop and was not
available for copying.

The rebuild preserves the scientific contract and intended module boundaries,
but it does not claim source-level identity with the unavailable implementation.
Synthetic generator distributions and illustrative parameter values were newly
specified, so regenerated numerical values are expected to differ from the old
handover record.

## Canonical decisions retained

- deterministic, one-period, asset-level allocation;
- repurpose, recycle, or defer;
- sparse binary asset-pathway variables;
- pathway and shared-resource capacities;
- SOH, safety and chemistry admissibility;
- economic objective with emissions reported separately or constrained;
- MILP solution, LP relaxation and LP shadow prices;
- independent, greedy, SOH-threshold and FIFO comparisons;
- capacity, emissions and cohort-aggregation analyses;
- stable policy/state protocols for Levels 1-3.

## Reproducibility

The default demonstration uses 60 synthetic packs and seed `20260802`. Exact
dependency versions are in `requirements-lock.txt`. Run the complete tests before
regenerating results or figures.

The same positive seed is passed to CBC's `randomSeed` and `randomCbcSeed`
controls. Level 0 is an exact benchmark, so its solver options reject time limits
and nonzero optimality gaps; both PuLP's model status and solution certificate
must report optimality before decisions or LP duals are accepted.

The synthetic static fleet includes varied current `periods_held` values so the
FIFO comparator is genuinely age-ordered. This is an observed one-period asset
attribute, not a transition or carry-over mechanism.

On the rebuilt laptop, Python 3.11.9 is stored in `.python/` and the project
environment in `.venv/`. Both directories are intentionally excluded from Git.
The analysis manifest hashes every asset, pathway, resource, pair coefficient,
deferral cost, emissions floor, and solver option. It also records Python and
package versions, CBC version and location, units, and Git state.
