<p align="center">
  <img src="docs/assets/agent-context-engine-logo.png" alt="Agent Context Engine Logo" width="220">
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_de.md">Deutsch</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Node.js" src="https://img.shields.io/badge/Node.js-20%2B-339933?logo=node.js&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-Apache%202.0-D22128">
  <img alt="macOS" src="https://img.shields.io/badge/macOS-active%20runtime%20target-000000?logo=apple&logoColor=white">
</p>

# Agent Context Engine

Lokale, harness-übergreifende Context-Engine für Coding-Agents mit Memory,
Retrieval, Tracing, Summaries, Dreams und Safety Controls.

Agent Context Engine zeichnet Sessions über unterstützte Runner auf, hält
den Laufzeitkontext lokal und inspizierbar und liefert Retrieval, kompakte
Handovers, Monitoring, Graph-Extraktion und firewall-ähnliche Safety-Controls
ohne Cloud-Infrastruktur.

Lizenziert unter der Apache License, Version 2.0. Siehe [LICENSE](LICENSE),
[NOTICE](NOTICE) und [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Aktuelle öffentliche Versionen:

- Backend / Produkt: `0.2.7`
- Monitor: `0.6.5`

Siehe [CHANGELOG.md](CHANGELOG.md) für die öffentliche Änderungshistorie.

## Was Es Macht

- zeichnet Sessions, Prompts, Tools und Runtime-Events über Hooks auf
- speichert lokales Memory für Retrieval über frühere Arbeit
- erzeugt kompakte Handovers und dream-basierte Kontextverdichtung
- bietet einen lokalen Monitor für Sessions, Risiken, Storage, Integrationen und Graph-Status
- erzwingt Safety-Controls für riskante Tool-Calls und Retrieval
- unterstützt Cross-Harness-Workflows für Codex, Claude Code, Cursor, Gemini, Antigravity und OpenCode

## Schnellstart

Aus einem frischen Clone:

```sh
python3 scripts/agent_context_engine.py install
```

Der Installer führt zuerst eine read-only Discovery aus, schlägt Zielpfad,
Memory-Root, Monitor-Port, Wrapper-Namenskonventionen und LaunchAgent-Verhalten
vor und wartet dann auf explizite Bestätigung, bevor Dateien geschrieben
werden.

Danach:

```sh
cd /pfad/zum/agent-context-engine-root
agent-context-engine doctor
agent-context-engine check-installation
agent-context-engine launchagent-status
```

## Dokumentation

- [Überblick](docs/overview.md)
- [System Overview](docs/architecture/SYSTEM_OVERVIEW.md)
- [Activation Model](docs/setup/activation-model.md)
- [Central Installation Mode](docs/setup/central-installation-mode.md)
- [Runner And Harness Guide](docs/setup/RUNNER_HARNESSES.md)
- [Build And Checks](docs/setup/BUILD_AND_CHECKS.md)
- [Monitor Operator Workflows](docs/runbooks/monitor-operator-workflows.md)
- [Project Origin](docs/project-origin.md)

## Für Agents

- [AGENT_BOOTSTRAP.md](AGENT_BOOTSTRAP.md): geführter Installationsvertrag für agentische Setups
- [session-start-hook-entry.md](session-start-hook-entry.md): Retrieval- und Kontext-Workflow zum Session-Start
- [SKILL.md](SKILL.md): paketierte Skill-Anweisungen

## Entwicklung

Zentrale Checks:

```sh
./scripts/check --skip-runtime-db
python3 -m unittest discover -s tests -v
./scripts/audit
```

Dependency-Dateien sind nach Zweck getrennt:

- `backend/requirements-runtime.txt`
- `backend/requirements-build.txt`
- `backend/requirements-audit.txt`

## Projektaktivierung

Für externe Arbeitsverzeichnisse werden die projektspezifischen Aktivierungen
über die öffentlichen Befehle verwaltet:

```sh
agent-context-engine cursor-enable --target /absolute/path/to/project --background-runner claude
agent-context-engine cursor-status --target /absolute/path/to/project
```

`cursor-status --target ...` ist der projektspezifische Detailblick; `doctor`
und `check-installation` zeigen die installweit bekannten Workspace-Roots und
deren Bindings.
