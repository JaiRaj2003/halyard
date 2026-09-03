"""Loaders and shared paths. Raw files are opened read-only and never rewritten."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_DIR = REPO_ROOT / "analysis" / "output"
DOCS_DIR = REPO_ROOT / "docs"

CONNECTION_FILES = {
    "Marcus Aldridge": "connections_aldridge.csv",
    "Tomás Beckett": "connections_beckett.csv",
    "Elena Duvall": "connections_duvall.csv",
    "Priya Raghunathan": "connections_raghunathan.csv",
    "Owen Trask": "connections_trask.csv",
    "Dana Whitfield": "connections_whitfield.csv",
}


def _read_csv(name: str) -> pd.DataFrame:
    frame = pd.read_csv(RAW_DIR / name, dtype=str, keep_default_na=False, na_values=[""])
    frame["_source_file"] = name
    frame["_source_row"] = range(2, len(frame) + 2)  # 1-based incl. header
    return frame


def load_requests() -> pd.DataFrame:
    return _read_csv("intro_requests.csv")


def load_outcomes() -> pd.DataFrame:
    return _read_csv("intro_outcomes.csv")


def load_crm() -> pd.DataFrame:
    return _read_csv("crm_accounts.csv")


def load_roster() -> pd.DataFrame:
    return _read_csv("connector_roster.csv")


def load_investors() -> pd.DataFrame:
    return _read_csv("investor_network.csv")


def load_connections() -> pd.DataFrame:
    """All six exports concatenated, with the owning connector attached."""
    frames = []
    for owner, filename in CONNECTION_FILES.items():
        frame = _read_csv(filename)
        frame["connector"] = owner
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_slack() -> list[dict]:
    path = RAW_DIR / "slack_threads.jsonl"
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def slack_messages() -> pd.DataFrame:
    records = []
    for thread_index, thread in enumerate(load_slack()):
        for message_index, message in enumerate(thread["messages"]):
            records.append(
                {
                    "request_id": thread["request_id"],
                    "channel": thread["channel"],
                    "thread_index": thread_index,
                    "message_index": message_index,
                    "ts": message["ts"],
                    "user": message["user"],
                    "text": message["text"],
                    "_source_file": "slack_threads.jsonl",
                }
            )
    return pd.DataFrame.from_records(records)


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    return path


def write_json(payload: dict, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    return path


def read_json(name: str) -> dict:
    with (OUT_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def read_output(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / name, dtype=str, keep_default_na=False, na_values=[""])


def fraction(numerator: int, denominator: int) -> dict:
    """Every percentage in this audit ships with its numerator and denominator."""
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "pct": round(100.0 * numerator / denominator, 1) if denominator else None,
    }
