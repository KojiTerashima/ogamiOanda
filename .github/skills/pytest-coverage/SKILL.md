---
name: pytest-coverage
description: "Use only for an explicit pytest coverage request or user-supplied coverage target. Measure the requested scope and add tests for observable behavior without inventing a 100 percent goal."
---

# Pytest Coverage

1. Use the requested test, module, package, or percentage target. If no percentage was supplied, report the measured result without inferring one.
2. Check `pytest --help` for `--cov` support before selecting a coverage command.
3. If `--cov` is unavailable, report that `pytest-cov` is missing. Do not install it or edit `pyproject.toml`.
4. Run the narrowest command that measures the requested scope, for example:

   ```bash
   pytest tests/test_target.py --cov=target_module --cov-report=term-missing
   ```

5. Inspect missing lines, then add deterministic tests only where they exercise observable behavior or a relevant risk boundary.
6. Re-run the same scoped command and report the result against the user's target.

Do not broaden the suite or coverage target beyond the explicit request.