# Private Streamlit deployment

Prepared 2026-10-22 for personal viewing using synthetic examples and downloads.

Live app: https://dsseolmode-6gvxep8xkwn6u6wosdwgwd.streamlit.app/

The redesigned application provides Dashboard, Decision workspace, Configuration,
Results & comparison, and Model & assumptions pages. See the
[application walkthrough](modular_dss.md#application-walkthrough). Configuration
changes require **Apply configuration**; completed session analyses can be
compared and downloaded together. The redesign passed 88 local regression tests
on 2026-10-22, including scenario persistence, eligibility handoff, stale-evidence
rejection and incompatible-comparison handling. The `dss/` and `level0/` model
implementations are unchanged.

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

## Update the live app from PyCharm

Workflow: **edit locally → test → commit → push → verify online**.
Saving a file or making a local commit does not update the live app. Streamlit
updates it when changes reach the deployed GitHub branch, `streamlit-private`.
Pushing only to `main` or another branch does not update this deployment.

1. **Open the project and check the branch.** In PyCharm, open
   `C:\Research\Codebase\DSS_prototype`. Select `.venv\Scripts\python.exe`
   as the interpreter and confirm the branch selector shows `streamlit-private`.
   For larger experiments, use a separate development branch, then merge the
   tested changes into `streamlit-private` when ready to publish.
2. **Edit and save the intended files.** The shared interface is
   `planner/app.py`; `planner/cloud_app.py` enables its synthetic-only cloud
   mode. Model and capability changes belong in the appropriate `dss/` or
   `level0/` modules. Add or update tests when changing model behaviour.
3. **Test the cloud version locally.** From PyCharm's terminal in the project
   folder, run:

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run planner/cloud_app.py --server.address 127.0.0.1
   ```

   Open the local URL printed in the terminal. Exercise the changed capability,
   run a synthetic example, and download its complete result. Stop the local
   server with `Ctrl+C`, or use another terminal for the next step.
4. **Run the tests before publishing.**

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests -q
   ```

   Resolve failures before pushing. If dependencies changed, install and test
   those versions locally as described below.
5. **Commit and push from PyCharm.** Open the Commit panel, select only the
   intended source, tests, and documentation files, review the diff, and enter
   a descriptive message. Choose **Commit and Push**, or commit first and then
   use **Git → Push**. Confirm the destination is `origin/streamlit-private`
   in `DorisFangWork/DSS_EOL_Model`. Keep secrets, research data, `.idea/`,
   virtual environments, and generated results out of the commit.
6. **Verify the live update.** Wait for Streamlit to finish updating, then open
   the live app linked above. Check the changed behaviour, run the relevant
   synthetic scenario, and save a result download. Ordinary code updates retain
   the existing private sharing settings; keep Sharing set to **Only specific
   people can view this app**, with no additional viewers.

### When dependencies change

Add or change pinned Python packages in `planner/requirements.txt`, the dependency
file used by this deployment. Installing a package only in PyCharm's local
environment does not install it in the cloud. Test the updated requirements
locally before committing and pushing them:

```powershell
.\.venv\Scripts\python.exe -m pip install -r planner/requirements.txt
```

Streamlit automatically rebuilds the environment when dependencies change, which
takes longer than an ordinary source update. Keep dependencies compatible with
the deployed Python 3.11 runtime.

### If the live app does not update or fails

- Confirm the push succeeded and the new commit is visible on GitHub's
  `streamlit-private` branch.
- Open **Manage app** on the live site to inspect build and runtime logs.
- Fix the reported problem locally, test, then commit and push the correction.
- If the build succeeded but the app remains stale, refresh the browser; use
  **Manage app → Reboot app** if needed. Download any results you want to retain
  before a reboot, which resets active sessions.

Streamlit documents automatic source updates and dependency rebuilds in
[Update your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app#update-your-app).

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
