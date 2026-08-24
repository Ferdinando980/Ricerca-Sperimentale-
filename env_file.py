"""Small .env reader/writer that preserves comments and ordering. Used by
settings_wizard.py so choosing providers in the app doesn't clobber the comments
in .env.example that explain each variable."""

import re
from pathlib import Path

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _KEY_RE.match(line)
        if match:
            key = match.group(1)
            values[key] = line[len(match.group(0)):]
    return values


def update_env_file(path: Path, updates: dict[str, str], template: Path | None = None) -> None:
    """Update `path` with `updates` (key -> new value), rewriting matching lines
    in place and appending anything not already present. If `path` doesn't exist
    yet and `template` does, start from the template so its comments survive."""
    if not path.exists() and template is not None and template.exists():
        lines = template.read_text(encoding="utf-8").splitlines()
    elif path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    remaining = dict(updates)
    for i, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[i] = f"{key}={remaining.pop(key)}"

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
