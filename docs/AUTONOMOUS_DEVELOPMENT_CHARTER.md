# AUTONOMOUS DEVELOPMENT CHARTER — APPROVED OWNER MANDATE

**Effective:** 7 November 2026. **Applies only to:** Advanced P&ID Reader project and its development artifacts at
`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`,
with Git remote `https://github.com/EIEng-enginering/P-ID-reader.git`.

## 1. The decision

The owner wants **one finished product review**, not 50 more questions, not approval of each feature, not a stop at every work package. All 50 Option A development decisions (Q1–Q50) are binding. Claude is authorised to act as lead software architect/developer/tester, select reasonable implementation details, iterate locally, repair regressions and maintain project releases autonomously within this charter. No additional design-choice approval questions should be generated for in-scope work.

The phrase 'approval for everything' means **all routine development decisions and reversible implementation actions inside this bounded project**, not unlimited permissions to operate on external systems or override security/safety obligations.

## 2. Permitted without further owner design sign-off

1. Inspect source files and existing repository/workspace, create project directories and branches, build source and installer scripts, revise tests and local docs.
2. Choose algorithms, data structures, local models, frameworks and library implementations consistent with Q1–Q50, Python 3.12, approved Qt baseline and R1. Record nontrivial decisions in `docs/adr/` with alternatives, reason and rollback.
3. Implement all work packages WP-000–WP-011, integrate their code, refactor, fix bugs, test, benchmark and rebuild, without an approval checkpoint after each.
4. Generate synthetic drawings and synthetic fixture labels; run permitted test, lint, formatting, static checks and mock integration; capture screenshots when possible.
5. Install/update isolated, compatible development dependencies using existing authorised access and licence terms; pin versions and record download location/hashes. Do not assume network, administrator rights or commercial licensing.
6. Create local Git commits and non-destructive branches; preserve existing history. A push of new feature branches to the **named** remote is within this project's intended delivery if authenticated access and repository policy allow it and no confidential or uncleared data is included. Never overwrite protected branches or merge into main without final owner review.
7. Run background task workers **only within the coding agent's actual session/tool environment** as permitted. Resume from recorded state in subsequent sessions. Do not claim work will continue after the agent session has stopped unless the platform truly supports it.
8. Build candidate Windows packages, source archives, change logs, SBOMs, model cards and installation guides. Label unfinished or unverified components honestly.
9. Run self-review and an additional read-only coding-agent review (if available) against acceptance contracts; fix findings and re-test, without equating AI review with independent engineering validation.
10. Choose safe project defaults for absent minor details, using `UNKNOWN` / `NOT_RUN` rather than inventing engineering facts.

## 3. Forbidden or separately permissioned actions

- Spending new money or entering subscriptions, buying commercial CAD licenses, new cloud compute/API expenditure or acquiring paid models outside already configured, authorised project resources.
- Uploading confidential/client drawings, credentials, secrets, personal data, plant engineering data, license keys or other sensitive material to online AI, external test/telemetry systems, or public repositories.
- Changing, deleting, overwriting, migrating, reconfiguring or deploying the **live Worksheet HAZOP/LOPA application** or a live customer database. Host integration is rehearsed against a disposable COPY with a preserved original R1 contract.
- Modifying original R1 schemas, hashes, identifier rules, audit constraints, worker protocol or backwards compatibility simply to make a test pass; this requires a separately versioned contract change.
- Force pushes, history rewrites, protected-main merges, branch deletion that loses work, repository removal, destructive system commands, unreviewed bulk file removal, bypassing security/permission controls, disabling safety gates or anti-virus.
- Copying/redistributing copyrighted standards, vendor symbols, proprietary models, SDKs or data without applicable licences.
- Calling a P&ID an as-built, independently verified plant design; claiming calculated SIL/PFD/LOPA credit; auto-approving HAZOP, LOPA, QRA or PSS outcomes.
- Claiming independently measured accuracy, third-party review, real-Windows test results, DEXPI conformance or completion where the relevant check remains `NOT_RUN`, `BLOCKED` or `FAIL`.

## 4. Handling unknowns without asking the owner

Apply this deterministic resolution process:

1. If Q1–Q50 or the frozen R1 specify a rule, implement it.
2. If several technical designs satisfy the contract, choose the most maintainable, deterministic, offline-capable, testable, lowest-dependency choice and record the ADR.
3. If a third-party licence/availability prevents one advanced adapter, ship a safe disabled adapter that clearly refuses unsupported input, finish the rest and record the exact blocker.
4. If a real host is unavailable, develop a contract-conforming standalone module and disposable host simulation; mark real host integration `NOT_RUN`, never assume acceptance.
5. If a real Windows environment is unavailable, produce portable build instructions and code; mark actual Windows acceptance `NOT_RUN`, not `PASS`.
6. If no independent engineering reviewers or labelled real-world drawings are available, build synthetic ground truth and developer tests, retain external gate `NOT_RUN`, disclose the limitation at final review.
7. For disputed or ambiguous P&ID interpretations, return competing hypotheses with evidence; do not automatically manufacture connectivity.
8. When a hard access barrier affects only an external action (e.g., remote push), continue local coding and supply the commits/patch ZIP plus one precise final action needed.

Do not stop the entire project for missing drawings, model training data, cloud access, GitHub write access, additional owner approval or commercially unavailable adapters. Deliver the best fully tested subset and an explicit discrepancy to the full specification.

## 5. Developer loop: apply to EVERY work package

`Inspect -> write acceptance tests -> implement small vertical slice -> run tests -> run negative tests -> inspect diff and source licences -> update ADR/traceability -> commit locally -> continue`.

Where possible, independently verify results with a second agent or static checker. Tests must use real code, not fictional output. Never change a golden expected answer just to make production code pass unless the reference is independently demonstrated wrong and the correction is audited. All versions should have recoverable Git history and regression tests.

Record: `WORKLOG.md`, `REQUIREMENTS_TRACEABILITY.csv`, `OPEN_ISSUES.md`, `CHANGELOG.md`, `TEST_RESULTS/` and `docs/adr/` inside the code repository. Store no sensitive drawing text in plain logs.

## 6. Final owner review is the only planned product approval

At the end produce a **single user-facing review package** containing source code, runnable Windows build (if build environment supports it), install instructions, tested features, example synthetic input drawings and outputs, completed/missing work matrix, exact tests and benchmark denominators, licence report, security/rollback instructions, Worksheet adapter on a host COPY, and evidence links for every claim.

Mark four independent release gates distinctly: software functional, extraction accuracy, Worksheet host compatibility, independent engineering/real-Windows acceptance. Human release into production remains an owner decision. Do not claim an external gate was signed by the owner merely because the development charter is approved.

## 7. Tool permission reality

This is a **task authorization**, not a system security bypass. Claude Code permissions are enforced by the platform, not by the prompt. Prefer supported Auto mode or approved exact command patterns, sandboxing and repository-local project settings; do not use `--dangerously-skip-permissions` in a normal Windows environment. Company/managed policies, OS access, network consent, GitHub branch permissions and usage limits still apply. If tools legitimately block an action, record it rather than repeatedly seeking design permission.
