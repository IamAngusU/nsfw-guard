# Start here

This path is intentionally short. It keeps the environment inside the repository,
downloads the pinned model, and does not require shell activation.

## 1. Choose a runtime

Use CPU first when portability matters:

```powershell
python scripts\bootstrap.py --runtime cpu
```

Use DirectML for the easiest Windows GPU path:

```powershell
python scripts\bootstrap.py --runtime directml
```

Use CUDA when a compatible NVIDIA stack is already installed:

```powershell
python scripts\bootstrap.py --runtime cuda
```

`cuda-bundled` installs the larger runtime bundle when the host does not already
provide it:

```powershell
python scripts\bootstrap.py --runtime cuda-bundled
```

## 2. Scan a folder

```powershell
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --links
```

Replace `cpu` with `directml` or `cuda` to match the installed runtime. For CUDA, a
conservative arena can be selected when VRAM predictability matters:

```powershell
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cuda --cuda-arena-limit-mib 64 --links
```

The final console summary prints the run ID, counts, throughput, peak RSS, hardware,
and exact evidence paths. Each completed run also contains `metrics.svg`, a light-mode
timeline for throughput, CPU/GPU load, process RSS, and host-total GPU memory.

## 3. Review without touching originals

Open:

```text
C:\Pictures\.nsfw-guard\OPEN-LATEST-RESULTS.url
```

The local page links to `BLOCK`, `REVIEW`, and `ERROR` collections. Each collection
contains `.url` pointers, not copied images. Removing a pointer is safe; changing or
deleting the original remains an explicit user action outside NSFW Guard.

## 4. Pick automation behavior

The default exits nonzero for `ERROR`, after evidence has been written. Other useful
policies are:

```powershell
# Inventory only: always finish successfully
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --fail-on never

# Stop a pipeline when BLOCK exists
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --fail-on block

# Require a clean, fully automatic outcome
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --fail-on review
```

The scan still processes the collection and atomically closes its reports. `--fail-on`
controls the final process status; it is not an instruction to delete or move files.

## 5. Tune only when needed

The default worker planner is recommended. If the machine is shared or memory is
tight, lower its advisory budget:

```powershell
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --memory-budget-mib 512
```

For a controlled throughput experiment:

```powershell
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --workers 1
.venv\Scripts\nsfw-guard.exe folder "C:\Pictures" --provider cpu --workers 4
```

Do not compare cold-cache and warm-cache runs as if they were equivalent. The summary
records starting CPU/GPU load and marks contaminated headline evidence.

Next: [`docs/FOLDER_SCANNING.md`](docs/FOLDER_SCANNING.md) and
[`docs/METRICS.md`](docs/METRICS.md).
