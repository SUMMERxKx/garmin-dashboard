# fixtures

`raw/` — full raw provider responses from `scripts/garmin_probe.py`. **Gitignored**: these
contain real health data and must not go into a repo that ends up public.

`sample/` — hand-anonymized fixtures, committed, used by the parser tests. Copy a file
out of `raw/`, replace the values with plausible fakes, keep the structure exactly.

The structure-only report at `docs/fr165-fields.md` is safe to commit: field names,
types and presence, no values.
