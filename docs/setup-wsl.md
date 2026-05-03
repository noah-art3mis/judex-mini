# Setup — WSL (Windows Subsystem for Linux)

Host-environment notes for the WSL2-on-Windows reference setup. Most
of these constraints are platform-specific gotchas the rest of the
codebase already accommodates — this doc just collects them.

macOS / native Linux: skim "Cross-platform" at the bottom and skip.

## Install (Windows hosts)

```powershell
# Administrator PowerShell, one-time:
wsl --install
```

Reboot, open the **Ubuntu** app, create user/password. **Run all
project commands inside Ubuntu**, never PowerShell or CMD.

## System deps

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-por poppler-utils
curl -LsSf https://astral.sh/uv/install.sh | sh
# reopen terminal, then:
uv sync --extra analysis
```

The OCR system deps are only needed if you'll use `--provedor
tesseract` locally; cloud providers don't need them.

## The 3.8 GB ceiling — what it forces

WSL2 sees ~50% of host RAM by default. On an 8 GB laptop that's
~3.8 GB, which is what most code-side calibrations target:

- **DuckDB warehouse build** chunks every 5,000 cases
  (`judex/warehouse/builder.py:340-360`); single-pass rebuilds OOM
  past ~80k HC cases.
- **Local Tesseract sweeps** Pool-deadlock under OOM pressure on the
  4 GB box. Use `--provedor tesseract_fly` for any sweep over a
  few hundred PDFs.
- **`extrair-pecas`** must be scoped via `--csv <sweep>/cases.csv`
  to avoid corpus-wide enumeration (peak RSS pushes the ceiling).

To lift the ceiling: edit `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
memory=8GB
```

Then `wsl --shutdown` and reopen Ubuntu.

## Long sweeps + VM suspend

`nohup` survives terminal SIGHUP but **not** WSL VM suspend (Windows
sleep / Ubuntu inactive). Mitigations:

- Keep an Ubuntu window open during sweeps.
- Settings → Power & battery → "Plugged in: Never sleep" while
  sweeping.
- Trust `--retomar` — every sweep writes `sweep.state.json`
  atomically and resumes from the last `ok`.
- For multi-hour sweeps, prefer cloud OCR (`tesseract_fly`) — moves
  the long-running work off the laptop.

## Headless Marimo

WSL2 has no display server. Open localhost from the Windows side:

```bash
uv run marimo edit analysis/<file>.py --no-browser --headless
# Open the printed URL in Edge/Firefox on the Windows side.
```

WSL2 forwards localhost to Windows automatically. The pattern is
already in every analysis script's header comment.

## Filesystem speed

| Path | Speed |
|---|---|
| `/home/<user>/...` (native ext4) | Fast |
| `/mnt/c/...` (Windows mount) | 10-50× slower for small files |

Keep repo + venv + `data/` on the native side. Use `/mnt/c/...`
only for one-shot transfers (e.g.
`judex fazer-backup --saida /mnt/c/Users/<user>/Desktop/`).

## Cross-platform

| WSL | macOS | Linux |
|---|---|---|
| `apt-get install tesseract-ocr tesseract-ocr-por poppler-utils` | `brew install tesseract tesseract-lang poppler` | distro pkg manager |
| `/mnt/c/Users/<user>/Desktop/` | `~/Desktop/` | `~/Desktop/` |
| VM-suspend trap | (n/a) | (n/a; laptops still sleep — same `--retomar` advice) |
