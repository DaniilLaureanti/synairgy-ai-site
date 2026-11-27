# SynAirgy

This repository contains the SynAirgy marketing site and the separate Lead Engine
application. It is not the SynAirgy Crosspost Engine repository.

**Development starts here:** [AGENTS.md](AGENTS.md) →
[PROJECT_STATUS.md](PROJECT_STATUS.md) → [progress guide](docs/progress/README.md).
Every coding model shares the same rules and saved task state.

```sh
python scripts/progress.py resume
python scripts/progress.py install-hooks
python -m pip install -r lead-engine/requirements-dev.txt
python scripts/progress.py run all
```

- Static site: semantic HTML, CSS and native JS modules; GitHub Pages, no build step.
- Engine: Python 3.12, FastAPI, SQLModel/SQLite, one persistent host.
- [Engine setup and operating boundaries](lead-engine/README.md)
- [Architecture and dependencies](docs/DEVELOPMENT_ARCHITECTURE.md)
- [Architecture decisions](docs/decisions/README.md)
- [Prepared cloud launch](lead-engine/CLOUD_LAUNCH.md) — configuration is not proof
  of a running service. Runtime provider keys and data do not belong in Git.
