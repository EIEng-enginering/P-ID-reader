# Background training service (symbol detector)

Trains the learned symbol detector (TR1, Faster R-CNN) in the background so you can keep using the Reader (and Claude). Candidate models only: it never changes the active
detector, the project database or any engineering data.

## Use it
**In the Reader:** open the **Training** tab. Check the settings (defaults: continue from the repo's E5 weights, 6 epochs, 2 CPU threads, no daily compute limit (set Compute hours per day to cap it), tiles in
`C:\PIDWork\tr1\tiles`, run folder `%LOCALAPPDATA%\PIDReader\training\tr1`), press **Start training**. Then **Pause / Resume** and **Cancel** as needed; the tab shows state,
progress, loss, speed, estimated time left and the compute used today. It only reads status files (every 3 s, only while the tab is visible), so it never freezes the window.

**From a terminal:** `python -m pid_reader.cli trainer start|status|pause|resume|cancel [--state-dir D] [--tiles-dir D] [--epochs N] [--threads N] [--hours-per-day H] [--lr X]`.

## What it does
* A **detached runner process** supervises the guarded trainer in `tools/tr1_train`. Closing the Reader does **not** stop it. If the computer restarts, press Start again: it resumes from the
  last checkpoint (the trainer restores the optimiser, learning-rate schedule and random state, so a paused or interrupted run finishes with the same weights as an uninterrupted one).
* **Low impact:** runs at BELOW_NORMAL priority on 2 of the 4 cores by default, so your own work keeps the CPU. It waits (state *Waiting*) on battery power, when free memory is under
  2.5 GB, when free disk is under 4 GB, or, only if you set one, when today's compute-hours limit (Perth date) is reached, and continues by itself when that clears.
* **Safe stops:** pause, cancel, a policy wait and the daily limit all stop the trainer at a checkpoint (the guard kills the whole process tree; a Job Object also kills it if the runner dies).
  Losing at most `ckpt_every_iters` (50) iterations. Memory is capped at 4 GiB for the whole tree.
* **Files** (all in the run folder): `config.json`, `service.json` (state), `progress.json`, `budget.json`, `PAUSE`/`CANCEL` control files, `service_events.jsonl` (hash-chained),
  `runner.log`, `run/` (checkpoints, `loss_log.jsonl`, `weights_final.pt`, `TRAINING_MANIFEST.json`).

## The tray icon (no Reader, no terminal needed)
A small separate program puts an icon in the Windows notification area (bottom-right; on Windows 11 drag it out of the "^" overflow onto the taskbar to keep it visible).
It starts by itself whenever a run starts (from the Training tab or the CLI) and stays after the run ends, so you can start the next run. Start it by hand with
`python -m pid_reader.cli trainer tray`.

* **Icon:** grey hollow ring = idle or stopped; green play symbol with a progress ring = training; amber pause symbol = paused or waiting (on battery, low memory or disk, daily hours used);
  blue check = finished; red exclamation = failed or stopped unexpectedly. **Tooltip:** state, epoch, percent, time left.
* **Click (or right-click) menu:** Start training… (repeats the last run's settings, or the defaults; asks first), Pause / Resume, Stop training… (asks first; checkpoints are kept),
  Open the Reader, Open run folder, *Start this icon with Windows* (off until you tick it; it adds one file to your Startup folder and unticking removes it), Close this icon.
* A balloon notification appears when a run finishes, fails or stops unexpectedly. Closing the icon never affects a run. Only one icon runs at a time.
* A finished run is kept (`run.completed.N`) and the next Start begins a fresh run.

## Resume after a restart (scheduled task)
`tools/training/Install-ResumeTask.ps1` registers the Windows task **PID Reader Training Resume** (runs as you, no elevation, no window, at logon + 2 minutes).
It runs `python -m pid_reader.cli trainer autoresume`, which restarts the run **only if it was cut off while it was meant to be going** (restart, crash, closing the Claude app, logoff).
It never starts a new run and never overrides you: a paused, stopped, cancelled, failed or finished run is left alone, and a run that is already alive is not touched.
A saved process id from before the restart is recognised as stale (its last heartbeat predates the boot time), so a reused id cannot fool it.
The runner still honours the battery, memory and disk limits (and a daily-hours limit only if you set one). Remove the task with `powershell -File tools/training/Install-ResumeTask.ps1 -Remove`.
A run started from a process that Claude launched ends when the Claude app is closed; start it from the desktop shortcut, the tray icon or this task to keep it independent.

## Cumulative training (each run builds on the last)
**Start from weights = `auto`** (the default in the tab, the CLI and the tray's Start): a new run starts from the newest *usable* finished run, so the work adds up. The first run starts from the
repo's E5 weights. When a run finishes, its weights are copied permanently to `<run folder>/lineage/runNNN_weights.pt` (checksummed) and recorded in `lineage.json` with its parent run, settings
and tile-set checksum; the finished run folder is also kept as `run.completed.N`. Nothing is overwritten or deleted.
* `python -m pid_reader.cli trainer lineage` lists the chain. `... lineage --mark N --status rejected` makes `auto` skip run N (use it when a run scores worse on held-out plans), `--status usable` undoes it.
* A run that was cut off and resumed keeps the weights it began from (its checkpoint continues it); only a *new* run picks up the latest.
* Pick a specific weights file instead of `auto` to branch from an older run or from E5.
* Cautions: gains shrink and a model can overfit if later runs reuse the same data, so score each run on the held-out plans before building on it; a later run on a different dataset should mix in
  the earlier data or it can forget the earlier classes; consider a lower learning rate (`--lr`) for later rounds. The optimiser and learning-rate schedule restart for each new run (they are restored only when resuming the same run).

## Training on all the data (full tile set)
`tools/tr1_train/prepare_tiles_full.py <pid2graph_root> <out_dir>` builds tiles from EVERY usable PID2Graph plan (the older `prepare_tiles.py` only sampled 70 real plans and 3 tiles per synthetic plan).
Train = all 500 real Dataset PID plans except 26 held out + all 250 synthetic plans (about 22,000 tiles, class-balanced so `general` and `arrow` are not drowned out). Held out and never trained on:
PID2Graph OPEN100 (12 authors' test plans) and 26 real plans (index >= 70, every 17th: unseen by E5 and trainer run 1, so comparisons on them are fair; listed under `holdout_plans` in the manifest).
Score a model on them with `tools/data/eval_pid2graph.py ... --holdout-manifest <tiles_dir>/TILES_MANIFEST.json --plans 100` (OPEN100 is the default).
Not usable for the four-class detector: ASU (class-agnostic labels), Digitize-PID (numeric class ids without names, images still archived, licence not stated), Roboflow (not downloaded).
A model whose card pins another checksum (the E5 card does) refuses new weights; score a candidate with its own copied card (CANDIDATE only), never by editing the E5 card.

## Automatic scoring when a run finishes
When a run completes, the runner scores the new weights on the held-out plans (PID2Graph OPEN100, plus the extra held-out real plans in the tiles manifest), scores the parent run (E5 for the first
run) the same way, and stores the comparison in `lineage.json` (`eval`, with the pooled per-class precision/recall/F1, macro F1 and valve+instrumentation F1). Each model is scored once and cached under
`<run folder>/eval/`. The Training tab and `trainer status` show the result (`evaluation`). It runs at low priority and takes about an hour on this laptop; a failure never changes the finished run.
* **Rule:** a run is **rejected** (skipped by `auto`, never deleted) only when it is clearly worse than its parent: macro F1 down by more than 0.01, or valve+instrumentation F1 down by more than 0.03.
  Otherwise it stays usable. Settings in the run config: `auto_evaluate` (default on), `auto_reject` (default on; off = the verdict is recorded but nothing is rejected), `eval_root` (the PID2Graph folder).
* **If the data drive is not connected** the scoring is skipped with a message; connect it and run `python -m pid_reader.cli trainer evaluate [--entry N]`. The logon task also starts a pending scoring
  after a restart (only when the last run finished and nothing else is running).
* The scoring uses the authors' labels on public data: a development measurement, not an accuracy claim about your drawings. Each run gets its own CANDIDATE model card (the E5 card pins E5's checksum).

## Limits
* Source checkout only (it runs `tools/tr1_train` and needs the optional torch environment, `PIDLAB_TR1_PYTHON` or `C:\PIDWork\venv312_torch`).
* One run at a time per run folder. The run folder must not be in OneDrive.
* A finished model is a CANDIDATE. Evaluate it on held-out labelled plans before anyone considers using it; the programme never promotes a model.
* CPU training is slow: use the pace shown in the tab (iterations per minute) to judge how long a run will take.

## Tests
`tests/test_trainer_service.py` (9: detached start, completion, pause/resume without losing iterations, cancel, policy wait, daily budget, low priority, dead runner, validation, double start),
`tests/test_training_tab.py` (5, offscreen Qt), `tests/test_training_tray.py` (11: icons, tooltip, menu, confirmations, start-with-Windows, single instance, archive of finished runs), `tests/test_trainer_service_real.py` (the real guarded trainer with a mid-run pause/resume), and the new `--init-trained` / `--lr` options in
`tests/test_tr1_trainer_tool.py`.
