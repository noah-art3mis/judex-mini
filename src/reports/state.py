"""Per-class high-water mark for the daily discovery loop.

Tiny JSON file at `data/daily_report/state.json`. Atomic-write contract
so a crashed run can't leave a half-written state that loses the mark.

Shape:

    {
      "max_numero":   {"HC": 271139, "ADI": 7500, ...},
      "last_run_utc": "2026-04-19T06:00:00Z"
    }

Per-class, not global: `numeroProcesso` is a per-class sequential counter
in STF, so one entry per tracked class.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DailyState:
    max_numero: dict[str, int] = field(default_factory=dict)
    last_run_utc: str = ""

    @classmethod
    def load(cls, path: Path) -> "DailyState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            max_numero=dict(data.get("max_numero", {})),
            last_run_utc=str(data.get("last_run_utc", "")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"max_numero": self.max_numero, "last_run_utc": self.last_run_utc},
            indent=2,
            sort_keys=True,
        )
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
