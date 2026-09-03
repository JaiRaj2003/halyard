# halyard

## Repository layout

| Path | Purpose |
| --- | --- |
| `data/` | Datasets used by the project. |
| `data/raw/` | Immutable raw data, exactly as obtained from its source. Never edit in place. |
| `analysis/` | Notebooks and scripts that explore, clean, and analyze the data. |
| `docs/` | Documentation: notes, references, and write-ups. |
| `app/` | Application code. |
| `AGENTS.md` | Conventions for AI agents working in this repository. |

## Data audit

Findings: [`docs/DATA_AUDIT.md`](docs/DATA_AUDIT.md) and
[`docs/INITIAL_PROBLEM_RANKING.md`](docs/INITIAL_PROBLEM_RANKING.md).
Method and caveats: [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md),
[`docs/ASSUMPTIONS_AND_LIMITATIONS.md`](docs/ASSUMPTIONS_AND_LIMITATIONS.md),
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

```bash
pip install -r analysis/requirements.txt
python analysis/audit/run_audit.py     # regenerates analysis/output/
python -m pytest analysis/tests -q
```

No application has been built yet; `app/` is empty by design.
