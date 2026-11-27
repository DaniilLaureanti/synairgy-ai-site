#!/usr/bin/env python3
"""Enforce existing SynAirgy module boundaries without importing runtime providers."""
from __future__ import annotations

import ast
from pathlib import Path
import sys

# Dependencies point from composition/application code towards contracts/data/domain.
# This is an intentional boundary policy, not an exhaustive allowlist of import lines.
INTERNAL = {
    "__init__": set(),
    "domain": set(), "ports": set(), "models": set(), "settings": set(),
    "demos": set(), "safe_http": set(), "schedule": set(),
    "store": {"domain", "models"},
    "adapters": {"ports", "domain", "safe_http"},
    "research": {"ports"},
    "workflow": {"demos", "domain", "models", "ports"},
    "outreach": {"domain", "models", "ports"},
    "billing": {"domain", "models", "ports"},
    "portfolio": {"domain", "models", "ports", "research", "settings"},
    "console": {"models"},
    "telegram": {"console", "domain", "models", "portfolio"},
    "api": {"adapters", "billing", "domain", "models", "outreach", "portfolio", "ports", "research", "settings", "store", "workflow", "telegram", "cli"},
    "cli": {"adapters", "demos", "domain", "models", "outreach", "portfolio", "settings", "store", "telegram", "workflow", "api"},
}
LEGACY = {
    "domain": {"catalog"}, "billing": {"catalog"},
    "workflow": {"ai_analyzer", "catalog"}, "adapters": {"scraper", "ai_analyzer"},
    "portfolio": {"google_places"}, "cli": {"google_places"},
}
# Pure domain/contracts/utilities may not acquire provider or framework dependencies.
PURE = {"domain", "ports", "demos", "settings"}
# Provider adapters are allowed in adapters/research/billing/telegram, as documented.
IO_PACKAGES = {"requests", "urllib3", "httpx", "stripe", "openai", "smtplib", "socket", "fastapi", "uvicorn"}


def imports(tree):
    for node in ast.walk(tree):  # includes function-local imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, 0, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module, node.level, node.lineno
            else:
                for alias in node.names:
                    yield alias.name, node.level, node.lineno


def validate(root):
    root = Path(root)
    directory = root / "lead-engine/src/synairgy"
    legacy_names = {p.stem for p in (root / "lead-engine/src").glob("*.py")}
    errors = []
    for path in sorted(directory.rglob("*.py")):
        name = path.stem
        if path.parent != directory or name not in INTERNAL:
            errors.append(f"{path.relative_to(root)}: document and classify new modules in the boundary policy.")
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            errors.append(f"{path.relative_to(root)}: Python syntax error.")
            continue
        for module, level, line in imports(tree):
            parts = module.split(".")
            first = parts[0]
            internal = first if level == 1 else (parts[1] if first == "synairgy" and len(parts) > 1 else None)
            if level > 1 or (first == "synairgy" and len(parts) == 1):
                errors.append(f"{name}:{line}: use an explicit local module import.")
            elif internal and internal not in INTERNAL[name]:
                errors.append(f"{name}:{line}: forbidden dependency on {internal}.")
            elif not internal:
                if first in legacy_names and first not in LEGACY.get(name, set()):
                    errors.append(f"{name}:{line}: unapproved legacy dependency {first}.")
                if name in PURE and first not in sys.stdlib_module_names and first not in LEGACY.get(name, set()):
                    errors.append(f"{name}:{line}: pure module cannot depend on {first}.")
                if name in {"workflow", "outreach", "store", "console", "models"} and first in IO_PACKAGES:
                    errors.append(f"{name}:{line}: provider/transport I/O belongs behind an existing adapter.")
    expected = {
        "CLAUDE.md": "@AGENTS.md\n",
        "GEMINI.md": "@./AGENTS.md\n",
        ".github/copilot-instructions.md": "Read and follow the shared repository instructions in [AGENTS.md](../AGENTS.md).\n",
    }
    for path, content in expected.items():
        if not (root / path).exists() or (root / path).read_text() != content:
            errors.append(f"{path}: keep the thin shared-instructions entrypoint; put rules in AGENTS.md.")
    return errors


def main():
    errors = validate(Path(__file__).resolve().parent.parent)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print("Architecture and shared instruction entrypoints passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
