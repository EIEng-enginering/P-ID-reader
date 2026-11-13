# Background training service (symbol detector)

Trains the learned symbol detector (TR1, Faster R-CNN) in the background so you can keep using the Reader (and Claude). Candidate models only: it never changes the active
detector, the project database or any engineering data.

## Use it
**In the Reader:** open the **Training** tab. Check the settings (defaults: continue from the repo's E5 weights, 6 epochs, 2 CPU threads, 2 compute hours per day, tiles in
`C:\PIDWork\tr1\tiles`, run folder `%LOCALAPPDATA%\PIDReader\training\tr1`), press **Start training**. Then **Pause / Resume** and **Cancel** as needed; the tab shows state,
progress, loss, speed, estimated time left and the compute used today. It only reads status files (every 3 s, only while the tab is visible), so it never freezes the window.

**From a terminal:** `python -m pid_reader.cli trainer start|status|pause|resume|cancel [--state-dir D] [--tiles-dir D] [--epochs N] [--threads N] [--hours-per-day H] [--lr X]`.

## What it does
* A **detached runner process** supervises the guarded trainer in `tools/tr1_train`. Closing the Reader does **not** stop it. If the computer restarts, press Start again: it resumes from the
  last checkpoint (the trainer restores the optimiser, learning-rate schedule and random state, so a paused or interrupted run finishes with the same weights as an uninterrupted one).
* **Low impact:** runs at BELOW_NORMAL priority on 2 of the 4 cores by default, so your own work keeps the CPU. It waits (state *Waiting*) on battery power, when free memory is under
  2.5 GB, when free disk is under 4 GB, or when today's compute-hours limit (Perth date) is reached, and continues by itself when that clears.
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
The runner still honours the battery, memory, disk and daily-hours limits. Remove the task with `powershell -File tools	raining\Install-ResumeTask.ps1 -Remove`.
A run started from a process that Claude launched ends when the Claude app is closed; start it from the desktop shortcut, the tray icon or this task to keep it independent.

## Limits
* Source checkout only (it runs `tools/tr1_train` and needs the optional torch environment, `PIDLAB_TR1_PYTHON` or `C:\PIDWork\venv312_torch`).
* One run at a time per run folder. The run folder must not be in OneDrive.
* A finished model is a CANDIDATE. Evaluate it on held-out labelled plans before anyone considers using it; the programme never promotes a model.
* CPU training is slow: use the pace shown in the tab (iterations per minute) to judge how long a run will take.

## Tests
`tests/test_trainer_service.py` (9: detached start, completion, pause/resume without losing iterations, cancel, policy wait, daily budget, low priority, dead runner, validation, double start),
`tests/test_training_tab.py` (5, offscreen Qt), `tests/test_training_tray.py` (11: icons, tooltip, menu, confirmations, start-with-Windows, single instance, archive of finished runs), `tests/test_trainer_service_real.py` (the real guarded trainer with a mid-run pause/resume), and the new `--init-trained` / `--lr` options in
`tests/test_tr1_trainer_tool.py`.
