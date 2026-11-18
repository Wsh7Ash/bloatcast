# Contributing

## Setup

```shell
pip install -e ".[dev]"
```

## Running tests

```shell
PYTHONPATH=src python -m pytest tests/ -v
```

## Changing the severity model

Severities are fixed on purpose so two reports from different people mean the same thing. If a threshold genuinely needs changing:

1. change the constant in `src/bloatcast/analyze.py` (`CRITICAL_DEAD_RATIO`, `WARN_DEAD_RATIO`, `INFO_DEAD_RATIO`);
2. update the table in `README.md`, `docs/ARCHITECTURE.md` and the output of `bloatcast rules`;
3. update the boundary tests in `tests/test_analyze.py` — every threshold needs a test exactly on the boundary;
4. re-run the example and update `results/` and `RESULTS.md` with the observed output.

## Adding input fields

- Add the field to `TableStats` and validate it in `model._table`; never trust a JSON value's type.
- Unknown keys inside a table object are ignored for forward compatibility; unknown keys in `settings` are rejected so a typo cannot silently disable a setting.
- Add a positive test, a rejected-type test and an "optional field absent" test.

## Recommendation changes

- One suggestion per table, maximum.
- State the resulting trigger in the note; a suggestion without its effect is not reviewable.
- Never emit a change that is not stricter than the current effective trigger.

## Style

- Standard library only; no runtime dependency will be accepted without a strong reason.
- No `print` outside `cli.py`/`render.py`.
- Keep the tool read-only: it must never execute SQL or connect to a database.
