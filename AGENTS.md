# AGENTS.md

Guidance for AI agents working in this repository.

## Layout

- `data/raw/` — immutable raw data. Treat as read-only: never edit or overwrite files here. Derived data belongs elsewhere under `data/`.
- `analysis/` — notebooks and scripts for exploration and analysis.
- `docs/` — documentation and write-ups.
- `app/` — application code.

## Conventions

- Keep new files in the directory that matches their purpose; do not add new top-level directories without a reason.
- Do not commit credentials, API keys, or other secrets.
- Do not commit large binary artifacts or generated outputs that can be reproduced from `data/raw/`.
