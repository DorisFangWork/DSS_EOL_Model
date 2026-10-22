# Private Streamlit deployment

Prepared 2026-10-22 for personal viewing using synthetic examples and downloads.

Live app: https://dsseolmode-6gvxep8xkwn6u6wosdwgwd.streamlit.app/

## Deployment verification (2026-10-22)

- Deployed from commit `ff2c7b1` on `streamlit-private`, Python 3.11.
- Sharing reads **Only specific people can view this app**, with no invited
  viewers; the private GitHub repository has zero collaborators.
- A signed-out browser was denied access and prompted to sign in. Owner access
  was restored successfully afterward.
- Live 60-pack integrated solve: Optimal; economic value SGD 89,082.37 and
  avoided emissions 159,286.55 kg CO2e; 25 repurposed, 35 recycled, no deferrals.
- Live two-pack integrated solve: Optimal; economic value 17.00.
- Downloaded and inspected `dss_run.json`: 60 battery records, feasible allocation,
  no violations, full scenario and pinned implementation versions. The hosting
  frame prevented automated download capture; capture succeeded from its direct
  app view. A verification copy is in `results/deployment/cloud_60pack_run.json`.
- Local privacy screenshots are in ignored `results/deployment/`.

## Deployment settings

| Setting | Value |
| --- | --- |
| GitHub repository | `DorisFangWork/DSS_EOL_Model` (renamed from `DSS_EOL`) |
| Deployment branch | `streamlit-private` |
| Entrypoint | `planner/cloud_app.py` |
| Python | `3.11` (select in Advanced settings) |
| Dependencies | `planner/requirements.txt` |
| Sharing | **Only specific people can view this app** |
| Viewers | Owner only; do not invite additional viewers |

The cloud entrypoint reuses the modular planner with synthetic-only controls.
It offers the 60-pack fleet and the two-pack capacity example, all four execution
modes, capacity/entry-rule experiments, and downloads of scenario, eligibility
and complete result JSON. Input uploads, manual battery entry, and SQLite history
are disabled for this deployment. Local `planner/app.py` retains those features.

## Account and privacy checks

1. Sign in at https://share.streamlit.io and connect the intended GitHub account.
   Review any terms and repository-access permissions in the browser.
2. Confirm the repository's visibility and its developer access list. Community
   Cloud developers with repository access can also access the private app.
3. Create the app with the settings above. A private repository defaults to a
   private app. If the repository is public, resolve privacy before deployment
   so the app is not temporarily exposed while changing its sharing settings.
4. Verify Sharing reads **Only specific people can view this app**, and that no
   additional viewers or developers have access beyond the intended owner.
5. Run the integrated 60-pack scenario: economic objective SGD 89,082.37, with
   25 repurposed, 35 recycled, and no deferrals. Run the two-pack example: 17.
6. Download a complete result and inspect its scenario and evaluation fields.
7. Test the app URL without an authorised login. It must require authentication
   or deny access, not display the DSS.

A URL is not proof of private access. The sharing settings and signed-out test
are required before describing this deployment as complete.

## Retaining results

Preparation checks on 2026-10-22: 86 local tests passed; pinned Linux/Python 3.11
dependencies resolved successfully. Cloud execution, sharing, signed-out denial,
and a saved result file were subsequently verified as recorded above.

Download results before closing or restarting the session. Cloud local storage
is not a durable results archive. No research data, secrets, local database,
virtual environment, or generated result directory belongs in the deployment.

The optimiser remains the existing PuLP/CBC Model 0. Pinned package resolution
for Linux is a preparation check; an actual cloud solve verifies the deployed
solver runtime. No security settings need to be disabled.

## Official references

- [Deploy an app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Dependency-file precedence](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)
- [Private sharing](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app)
- [Local storage persistence](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data)
