# Configuration (CFG-01)

## Summary
This project now loads runtime settings from YAML.

- Default config file: `./settings.yaml`
- Fallback path: environment variable `OGAMI_OANDA_SETTINGS_PATH`
- Template file: `settings.example.yaml`

`tokens.py` is now a compatibility layer that reads YAML and exposes the same names (`accountIDl`, `access_tokenl`, `line_send`, etc.).

## Setup
1. Copy the template:
   - `cp settings.example.yaml settings.yaml`
2. Fill your own credentials and webhook URLs in `settings.yaml`.
3. Run the app as before.

## Security
- Never commit `settings.yaml`.
- Keep secrets only in local machine or secure secret storage.
- Rotate tokens if leaked.

## Troubleshooting
If startup fails with a configuration error:
- Verify `settings.yaml` exists at project root.
- If using custom path, export `OGAMI_OANDA_SETTINGS_PATH=/path/to/settings.yaml`.
- Check required keys exist in YAML and are strings.
