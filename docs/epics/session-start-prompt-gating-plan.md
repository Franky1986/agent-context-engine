# Agent-Flow Session-Start Prompt Gating Plan

## Kontext

Seit Einführung der Hook-Startup-Injektion wächst der Startkontext tendenziell.
Der gewünschte Endzustand ist:

- kompakte Start-Nachricht mit klarer, leicht lesbarer Kommando-Referenz,
- kein repetitiver `agent-context-engine`-Präfix auf jeder Zeile,
- konditionale Anzeige von User-Only-Kontrollbefehlen.

## Ziele

1. **Prefix-First**
   - Der CLI-Prefix (`agent-context-engine`, ggf. projektabhängige Wrapper-Variante) wird einmal am Anfang kommuniziert.
   - Danach werden Subcommands ohne Präfix aufgelistet.

2. **Zweistufiger Startflow**
   - Stage 1: kompakter Default-Startkontext.
   - Stage 2: zielgenaue Kontextergänzung nach Intent oder Event-Trigger.

3. **Konditionale User-Only Controls**
   - `approve`-/`firewall`-/`workdir`-Zeilen nur anzeigen, wenn der Kontext sie wirklich verlangt.
   - `hooks-*` als Minimal-Basis beibehalten oder ebenfalls nach Bedarf je nach Risikoprofil.

4. **`session-start-context` bleibt als Fallback/Detailpfad**
   - Vollständige Kommandoliste bleibt abrufbar, aber nicht zwangsläufig im Default-Startblock.

## Soll-Darstellung (kompakte Stage-1-Form)

- `agent-context-engine`
  - `last --limit 10`
  - `use "<session|title|search terms>"`
  - `handover "<session|title|search terms>"`
  - `retrieve "<frage oder suchtext>" --limit 10`
  - `search "<begriff>" --limit 5`
  - `repo-context --list`
  - `personal-context --list`
  - `session-start-context`
  - `hooks-disable [--runner <runner>]`
  - `hooks-enable [--runner <runner>]`
  - `hooks-status`

## Trigger für zusätzliche Kontrollblöcke (Stage 2)

- **Block-Event vorliegt**
  - `approve <risk_event_id> <nonce>`

- **Workdir-Approval nötig**
  - `approve workdir /absolute/project/path`

- **Explain-Anfrage von Risikoklasse**
  - `approve explain <reason>`

- **Taint aktiv**
  - `reset taint`

- **konkrete Firewall-Empfehlung vorliegt**
  - passende `firewall ...` Zeilen

## Umsetzung in Code (Ziel)

1. **Contract-Render schlanker bauen**
   - `backend/src/agent_context_engine/application/agent_flow/contract.py`
   - `render_session_start_hook_entry(...)` reduziert Präfix-Duplikate, hält Basisblock klein.

2. **Startup-Injektion anpassen**
   - `backend/src/agent_context_engine/interfaces/hooks/support/session_context.py`
   - `startup_entry_content()` bleibt für generierte Hook-Datei, aber enthält keine dauerhaften User-Only-Controls.

3. **Trigger-gesteuerte Ergänzungen im Hook-Kontext**
   - `backend/src/agent_context_engine/interfaces/hooks/main.py`
   - Bedarfsabhängige Anzeige der Kontrollblöcke bei blocked tools / active taint / firewall suggestion.

4. **On-Demand-Referenzpfad sichern**
   - `backend/src/agent_context_engine/application/startup_context.py`
   - `session-start-context` bleibt als vollständige Referenzquelle erhalten.

5. **Normative Spezifikation auf gleiche Seite bringen**
   - `backend/src/agent_context_engine/application/agent_flow/agent_flow.spec.md`
   - neue Akzeptanzkriterien: prefix-once + staged injection + conditional controls.

## Risiken / offene Punkte

- Wenn `hooks-*` dauerhaft nicht mehr erscheinen, verliert der Agent einen schnellen Zugriff auf Hook-Management.
  - Empfohlen: dauerhaft nur Basis-Hooks behalten.

- Die Trigger-Heuristik darf kein Kontext-Regression erzeugen.
  - Bei jedem relevanten Event neu evaluieren, ob Kontrollblock angehängt werden muss.

- Prefix-Dynamik bei Runner-Wechsel
  - Der Basis-Prefix muss aus der aktiv aufgelösten CLI-Installation stammen.

## Prüfkriterien

- Default-Sessionstart zeigt keine dauerhaften `User-only controls`.
- Der Prefix wird einmalig angezeigt, Subcommands sind präfixfrei.
- Blockaden, Taint und Firewall-Zustände liefern jeweils die passende Kontrollzeile.
- `session-start-context` liefert bei Nachfrage den vollständigen Kontext.
- Kein Verlust an Hook-/Monitor- und Repo-Kontext-Fähigkeit.

## Review-Hinweis

Bei aktiver Dream-Auswertung sollten die neuen Trigger-Logiken nicht in Konflikt mit Dream-spezifischen Hook-Events geraten.
Der Triggerpfad sollte vor dem Stage-2-Enhancement und nach der Dream-Fehlermeldung geprüft werden.
