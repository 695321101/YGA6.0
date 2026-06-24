# Third-Party Notices

YGA6.0 core pipeline is original work. The following third-party components are used:

## Python

| Package | License | Used for |
|---------|---------|----------|
| [PyYAML](https://pyyaml.org/) | MIT | Session / PMC YAML read & write |
| [requests](https://requests.readthedocs.io/) | Apache-2.0 | AI HTTP API calls |

Python standard library modules (`pathlib`, `json`, `dataclasses`, etc.) are used throughout.

## Node.js (optional — `terminal/` module)

| Package | License | Used for |
|---------|---------|----------|
| [node-pty](https://github.com/microsoft/node-pty) | MIT | Local PTY terminal sessions |

## Runtime (not bundled in this repository)

- **AI API**: You provide your own OpenAI-compatible endpoint and API key via local `config/ai_config.json` (copy from `config/ai_config.example.json`; not included in this repo).
- **Python 3.10+** is required to run the pipeline.

## Future components (roadmap, not in this release)

- **YGA Studio Browser**: planned desktop browser for visual editing and AI-assisted UI iteration.
- Web UI shell: see `docs/showcase/index.html` for a concept preview.
