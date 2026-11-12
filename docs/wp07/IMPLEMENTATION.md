# WP07 Rev B: implemented against actual main c91ebe6

This revision completes the software integration missing from Rev A. It is an additive reader development package, not an independently validated full P&ID converter.

## Implemented

* Real main-window tab, reset hook and background-task integration. Defaults OFF each session. The panel supports selected existing proposals, automatic text regions and independent overlapping page tiles. TrOCR requires a selected line. Text can be turned left/right with an inverse coordinate transform.
* Complete CPU adapters for EasyOCR English, TrOCR small printed and the published RF-DETR P&ID checkpoint. Local setup scripts pin public source revisions, inventory every downloaded asset and preserve checkpoint class IDs. No weights are bundled or uploaded with drawings.
* An isolated worker with process termination on cancellation/timeout, bounded crops/output, model reuse inside a batch, and per-crop sealed caching. Repeating a job reuses completed identical crops; interrupted jobs can reuse their completed crop cache on rerun. Cache identity includes source, crop bytes, model artifacts, algorithm and runtime versions. Review decisions are never cached.
* Inference denies Python socket connections, sets Hugging Face offline flags, disables EasyOCR downloads, and uses local processor/checkpoint files. This is an application-level guard, not an OS network sandbox or proof about arbitrary native libraries.
* The current reader's PageFrame renderer is reused, including actual rounded crop boundaries. Tests compare independently located black rectangles over four PDF rotations and asymmetric CropBoxes. The frame is the reader's rotation-aware pdfplumber MediaBox-normalized top-left frame; do not reinterpret it as an unrotated PDF user-space frame.
* Raw scores and unavailable confidence remain distinguishable. Existing OCR is retained and challengers feed WP04 alternatives. The baseline detector threshold is unchanged. RF-DETR boxes are visible for review; a named reviewer can propose a visible symbol class for WP05. Ambiguous associations remain unresolved.
* Separate immutable analyses and append-only, hash-chained review decisions. Printed-text decisions cannot accept plant truth. Reviewable derived results open in the existing WP04–06 tab and sidecar. Project v13 and frozen Worksheet R1 are unchanged.
* JSON, formula-safe CSV, review/audit export, exact fixed-crop comparison tools, dependency records, source/checkpoint hashes and real-model observations.
* A small source archive for external Python workers in frozen installations, PyInstaller data hooks, isolated Windows setup script and an idempotent transactional installer. ML libraries are excluded from the core executable build.

## What was actually demonstrated

See evidence/VALIDATION.json and evidence/real/. All three real pretrained models ran on three selected S418 crop regions. These locations deliberately targeted the known problem readings, so this is a selected-crop diagnostic and is not an automatic page-discovery test. No independent accuracy percentage is claimed.

TrOCR read V-2201 in this crop. Both line labels still contain wrong characters. EasyOCR produced V_2201 and fragmented/misread line labels. RF-DETR produced a Rupture_disk hypothesis in text-only diagnostic regions, which is not evidence of a correct symbol. Treat all outputs as unverified. Raw observations are saved without replacing the supplied S418 baseline.

## Remaining external verification

Windows 11/i5-8265U performance, manual GUI/DPI use, clean-machine installation and a frozen Windows executable build require that environment. The Linux Qt 6.12.0 tests and worker ZIP tests do not certify them. The Windows dependency resolution must be recorded by SetupModels.ps1; its top-level backend versions were actually used here but Windows wheels have not been executed here.

An independently reviewed reference set is still needed for page coverage, text, symbol, association and graph accuracy. PP-OCRv5, standalone CRAFT beyond the EasyOCR path and DINOv2 exemplar matching remain research candidates, not additional implemented adapters. Symbol-port inference, general line/service classification and complete cross-sheet plant conversion are outside this model-integration revision; existing unknown geometry remains unknown.
