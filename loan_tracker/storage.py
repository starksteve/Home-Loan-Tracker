from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_DATA: dict[str, Any] = {
    "loan": {
        "principal": 1125000.0,
        "disbursement_date": "2022-05-31",
        "start_date": "2022-06-01",
        "tenure_years": 15,
        "assumed_annual_rate": 8.5,
    },
    "rate_changes": [],
    "payments": [],
}


def load_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        return DEFAULT_DATA.copy()
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    merged = DEFAULT_DATA.copy()
    merged.update(data)
    return merged


def save_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
