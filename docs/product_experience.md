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

Introduce the tool around an operational question: which destinations are eligible, which options are preferred, and how should a fleet be allocated under shared constraints? Demonstrate a capacity change and inspect its battery-level consequences. The three capabilities interact through shared inputs and evidence; they are not mandatory sequential stages.

An industry pilot should identify a decision owner, validate battery data and destination rules, agree assessment values and operational limits, and compare proposed plans with current practice. Economic savings, environmental benefits and service–recovery coordination gains require validation; synthetic examples are demonstrations of functionality.

The current private cloud preview uses synthetic inputs and session-only history. Download snapshots to retain work. Durable projects, enterprise identity and operational integrations remain deployment requirements, not advertised features. Model 0 and the other existing model implementations are unchanged by this interface redesign.

## Visual direction

The application structure follows Streamlit's management-interface pattern: persistent navigation, a compact header and a task-focused main workspace. The navy-and-white palette and typography borrow the visual language of the Wix Business Consulting Company template (2852). The implementation retains Streamlit, uses original product copy and code-native visual treatment, and does not copy Wix assets or introduce a Wix dependency.
