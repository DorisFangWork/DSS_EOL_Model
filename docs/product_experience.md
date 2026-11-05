# Industry-facing DSS experience

The product proposition is: turn battery information and operational constraints into traceable disposition plans.

## Navigation

- Dashboard is the default entry page, showing portfolio metrics, decision tools, the active scenario, latest analysis, recent activity and an expandable battery inventory.
- About the DSS contains the product introduction and pilot guidance as secondary information.
- Decision workspace supports independent eligibility assessment, destination comparison, allocation planning and an integrated analysis.
- Configuration applies shared operational inputs; previous results retain their input snapshots.
- Results & comparison explains recommendations and exports complete run and comparison records.
- Model & assumptions explains scope, source-example notes, assessment values and provenance.

Icon-labelled sidebar buttons provide application navigation. The compact workspace header provides a New analysis action. The planning-context panel holds the scenario selector and download. Source-example notes describe the original baseline; the applied configuration and saved snapshots define each actual run.

## Industry positioning

### Central Decision-maker dashboard

Dashboard now provides an overall prototype view through four independently rendered
sections in `planner/dashboard.py`: Disposition planning, Technical assessment,
Management overview, and Review & assurance. All four use the same selected
analysis snapshot, including its original scenario. Before a run, the applied
scenario is shown with explicit empty states; admission-only or infeasible runs
never borrow allocation totals from another run.

Use **Analysis snapshot** to review a run, **Compare against baseline** for an
explicit comparison of evaluated allocations, and the section actions to open the
existing capability workspaces. Historical input/model warnings apply to the
whole view. Inventory and capacity details follow the selected snapshot; editing
configuration still applies to the active scenario in the toolbar. Downloads
preserve the complete selected run.

Central Decision-maker is the integrated prototype perspective. Separate section
renderers provide a boundary for future role views; authentication, role assignment,
permission enforcement and operational approval are not implemented by this view.
Future access controls must cover underlying data and actions as well as visible sections.

Introduce the tool around an operational question: which destinations are eligible, which options are preferred, and how should a fleet be allocated under shared constraints? Demonstrate a capacity change and inspect its battery-level consequences. The three capabilities interact through shared inputs and evidence; they are not mandatory sequential stages.

An industry pilot should identify a decision owner, validate battery data and destination rules, agree assessment values and operational limits, and compare proposed plans with current practice. Economic savings, environmental benefits and service–recovery coordination gains require validation; synthetic examples are demonstrations of functionality.

The current private cloud preview uses synthetic inputs and session-only history. Download snapshots to retain work. Durable projects, enterprise identity and operational integrations remain deployment requirements, not advertised features. Model 0 and the other existing model implementations are unchanged by this interface redesign.

## Visual direction

The application is a planning console with persistent navigation, a compact scenario toolbar and task-focused pages. Main pages use a white background, forest-green headings and actions, Aptos with local-device fallbacks, and consistent outlined cards. The established left menu remains unchanged.

Visual hierarchy distinguishes page titles, decision questions and section titles, key findings, and supporting notes. Metrics use large figures with smaller explicit labels and units; card padding and section spacing follow a shared scale. Context selectors are grouped separately from findings. Amber indicates information requiring attention, rather than a preferred economic or environmental outcome. Capability cards have equal weight and never imply a mandatory sequence.
