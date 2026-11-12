# Claude: apply and verify this completed WP07 software package

The owner requested that implementation work be completed here. Source, GUI, worker, setup, export, audit, caching, tests and exact integration patches are supplied. Do not recreate the implementation from prose.

1. Inspect the current repository and uncommitted changes. This package was developed against GitHub main **c91ebe6e4e4de49a03155c3335f8ad2f8d4d598c**, not just the older supplied snapshot. Read applicable repository instructions. Do not push.
2. Extract the package outside the source repository, e.g. C:\PIDWork\WP07. From that package root run:

       python tools/install_wp07.py "C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader" --check
       python tools/install_wp07.py "C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader" --apply

   It checks all package hashes and every destination before writing, accepts exact known Rev A adapter upgrades, refuses unknown conflicts, applies two small integration patches and rolls back failures. It never commits or pushes. Rerunning is safe. If current main has changed in a conflicting location, resolve only the reported conflict; do not overwrite entire main-window or build files.
3. In the repository's Python 3.12/Qt environment run:

       python tools/wp07/run_checks.py
       python -m pytest -q tests

   Preserve actual output and classify any existing baseline issues separately. Core and frozen-R1 sources were not changed by this revision. The dedicated checks exercise real Qt main-window integration, cancellation, stale-page rejection, sidecar isolation and rotated/cropped PDFs.
4. Build/rebuild the external worker archive before a frozen build:

       python tools/wp07/build_worker.py

   The installer already ships a tested archive; rebuilding refreshes it after any source edit. PyInstaller spec hooks ship this archive and setup files while excluding the ML runtimes from the executable. Perform the normal Windows build/install checks; no new release is claimed here.
5. Stage CPU model runtimes and public weights outside OneDrive:

       powershell -File tools/wp07/SetupModels.ps1 -Engine all

   This explicitly downloads public model files; it sends no drawings. The script creates a separate model environment, installs pinned CPU versions and writes manifests and the actual Windows dependency list. The source and checkpoint revisions are pinned. Keep weight license/provenance notes with any distribution. A failure must remain visible; do not silently change versions to declare success.
6. Open the Model comparison tab. Choose a manifest and interpreter, enable the session and run selected proposals first. TrOCR needs one selected text line. Compare independent page tiles with EasyOCR and RF-DETR afterwards. Results are proposals and cannot automatically replace baseline readings or engineering records. Review derived readings through WP04–06.
7. Repeat S418 using the same main-analysis switches, then run held-out real drawings. Return baseline vs challenger outputs, timing/memory and coverage separately. No approval reference or accuracy figure should be invented. Manual Windows acceptance and independent engineering validation remain separate.

No new feature design or adapter coding is expected against the tested baseline. The remaining work is installation, actual Windows verification and resolving any genuine differences in a newer repository/environment.
