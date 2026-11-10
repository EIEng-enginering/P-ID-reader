# TR1 offline trainer (separate tool; the app never imports it)

Trains the Faster R-CNN (MobileNetV3-Large FPN) symbol detector on CPU, on Windows, from a folder of tiles. It is the Grok E5 method (seed 20261110)
made restartable and guarded. Nothing here runs unless `PIDLAB_LOCAL_TRAINER_TR1` is on; nothing uploads; nothing changes the app's active detector.

## What you need
* The optional torch component in its own environment (`requirements-tr1-torch.txt`, torch 2.15.0+cpu / torchvision 0.29.2+cpu).
* Tiles: `python prepare_tiles.py <pid2graph_extract_root> <out_dir>` (PID2Graph, CC BY-SA 4.0; see the Grok `tools/pid2graph_fetch`), or your own tiles in the same `TILES_MANIFEST.json` format.
* Optional starting weights: the torchvision COCO checkpoint `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth` (`--init`). `--init none` starts from random weights (used by the tests only).

## Run
```
set PIDLAB_LOCAL_TRAINER_TR1=on
<torch_env>\Scripts\python run_training.py --tiles-dir D:\tiles --out-dir D:\runs\E6 --python <torch_env>\Scripts\python.exe --init D:\models\fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth --max-wall-s 7200
```
Put tiles and runs outside OneDrive (they are large and write often), e.g. `C:\PIDWork\tr1`.

## Guard
* One child process in a Windows **Job Object** with KILL_ON_JOB_CLOSE: a timeout, a cancel (`--cancel-file FILE`, create the file to stop), a limit hit, or the launcher dying ends the whole process tree. The result lists `processes_left_after_kill` (must be empty).
* Limits: `--max-wall-s` (required), `--max-cpu-s`, `--max-rss-mb` (measured over the whole tree, so the Windows venv launcher process does not hide the real interpreter).
* Every state change is appended to `<out-dir>.events.jsonl` (hash chained); `RUN_RESULT.json` is written at the end.

## Resume
A checkpoint (`ckpt_latest.pt`: model, optimiser, scheduler, both random generators, position in the epoch) is written atomically every `--ckpt-every-iters`. After any stop run the same command with `--resume-latest`; it refuses a checkpoint made with different data or settings. On the tested configuration a resumed run ends with weights identical (sha256) to an uninterrupted run.

## Result
`weights_final.pt` + `TRAINING_MANIFEST.json` (data sha256, settings, seed, torch version, weights sha256, peak memory). A finished model is only a candidate. With `PIDLAB_MODEL_REGISTRY_TR1` on and `--register-registry DIR` it is recorded in the model registry (candidate / active / previous, human-approved promotion, rollback). To use it in the app it needs its own model card (classes, threshold chosen on validation data, weights sha256) placed beside the weights in `models/`; a card is never generated automatically.

## Not done
Correction-batch -> tiles conversion (the batches hold reviewed boxes and the document sha256; turning them into tiles needs the original PDFs and is the next work package), validation on the owner's drawings, and any promotion decision.
