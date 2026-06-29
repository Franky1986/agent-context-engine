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

2. **Kondensierter Basiskontext**
   - Der Standard-Sessionstart bleibt kompakt.
   - Kontextergänzung erfolgt nur bei konkretem Trigger/Bedarf im laufenden Dialog.

3. **Konditionale User-Only Controls**
  - `approve`-/`firewall`-/`workdir`-Kontrollzeilen nur anzeigen, wenn der Kontext sie wirklich verlangt.
  - `hooks-*` bleiben nicht im Basiskontext enthalten; sie sind weiterhin über `session-start-context` oder explizit zugänglich.

4. **`session-start-context` bleibt als Fallback/Detailpfad**
   - Vollständige Kommandoliste bleibt abrufbar, aber nicht im Default-Startblock.

## Soll-Darstellung (kompakter Basiskontext)

- `agent-context-engine`
  - `last --limit 10`
  - `use "<session|title|search terms>"`
  - `handover "<session|title|search terms>"`
  - `retrieve "<frage oder suchtext>" --limit 10`
  - `search "<begriff>" --limit 5`

Load extra context when needed:

- `session-start-context`
- `personal-context --list`
- `personal-context <identifier>`
- `repo-context --list`
- `repo-context <identifier>`
- `retrieval-runs --limit 10`
- `retrieval-run <retrieval_run_id>`

## Session-Start-Ausgabekomposition

Aktuelle Reihenfolge in `memory_hooks_status_context` + `startup_entry_content`:

1. Runtime-Status / Kontroll-Hinweise (`firewall`, `dream`, `pending`, `taint`, optional Cursor-Auth).
2. Kompakter Quickstart.
3. Optionale Dream-/Cursor/Firewall/taint/pendingspezifische Nachreichung.
4. Monitor-Kommandoline.

## Trigger für zusätzliche Kontrollblöcke

- **Pending-Approvals vorhanden**
  - `Pending blocked approvals: n...`

- **Taint aktiv**
  - `You are in taint-aware mode after recent high-risk context.`
  - `reset taint`

- **Globale Firewall deaktiviert**
  - `firewall enable session`

- **Relevante Dream-Failures vorhanden**
  - `Agent Context Engine dream processing needs attention...`

- **Cursor-Auth-Hinweis relevant**
  - Cursor-spezifische Auth-Notiz bei ersten relevanten Schritten.

- **Block-/Workdir-/Explain-Kontexte**
  - bleiben im passenden User-Prompt-/Tool-Kontext aktiv; werden nicht im Basiskontext dauerhaft angezeigt.

## Umsetzung in Code (Ist-Stand)

1. **Contract-Render schlanker**
   - `backend/src/agent_context_engine/application/agent_flow/contract.py`
   - `render_session_start_hook_entry(...)` reduziert Präfix-Duplikate, hält Basisblock klein.

2. **Startup-Injektion angepasst**
   - `backend/src/agent_context_engine/interfaces/hooks/support/session_context.py`
   - `startup_entry_content()` enthält keine dauerhaften User-Only-Controls mehr.

3. **Trigger-gesteuerte Ergänzungen im Hook-Kontext**
   - `backend/src/agent_context_engine/interfaces/hooks/main.py`
   - Bedarfsabhängige Anzeigen für Pending-Approvals, taint-aware Hinweis, Firewall-Enable-Hinweis.

4. **On-Demand-Referenzpfad gesichert**
   - `backend/src/agent_context_engine/application/startup_context.py`
   - `session-start-context` bleibt als vollständiger Detailpfad.

5. **Normative Spezifikation**
   - `backend/src/agent_context_engine/application/agent_flow/agent_flow.spec.md`
  - Akzeptanzkriterien: prefix-once + konditionaler Zusatzkontext + conditional controls.

## Risiken / offene Punkte

- Wenn `hooks-*` dauerhaft nicht mehr erscheinen, geht schneller Zugriff auf Hook-Management verloren.
  - Empfehlung: `session-start-context` als dokumentierten Detailpfad für diese Befehle nutzen.

- Die Trigger-Heuristik darf kein Kontext-Regression erzeugen.
  - Bei jedem relevanten Event neu evaluieren, ob der Kontrollblock angehängt werden muss.

- Prefix-Dynamik bei Runner-Wechsel
  - Basis-Prefix muss aus der aktiv aufgelösten CLI-Installation stammen.

## Prüfkriterien

- Default-Sessionstart zeigt keine dauerhaften `User-only controls`.
- Der Prefix wird einmalig angezeigt, Subcommands sind präfixfrei.
- Kompaktmodus bleibt kurz; Zusatzblöcke erscheinen nur konditional.
- `session-start-context` liefert bei Nachfrage den vollständigen Kontext.
- Kein Verlust an Hook-/Monitor- und Repo-/Personal-Kontext-Fähigkeit.
- Pending/Taint/Firewall/Dream-Hinweise erscheinen bei aktueller Relevanz.

## Review-Hinweis

Bei aktiver Dream-Auswertung sollen Trigger-Logiken nicht mit Dream-Hook-Events kollidieren.
Der Triggerpfad sollte vor Zusatz-Erweiterungen und nach der Dream-Fehlermeldung geprüft werden.

## Umsetzungsstand (2026-06-29)

- ✅ Prefix-once Command-Signature im Session-Start-Entry umgesetzt.
- ✅ Session-Start-Injection auf kompakten Basis-Block reduziert.
- ✅ Kontextsensitive Nachreichung aktiv:
  - Pending-Approvals (`Pending blocked approvals` + Hidden-Details-Hinweis)
  - Taint-Hinweis (`reset taint`)
  - Firewall-Enable-Hinweis bei deaktiviertem Modus
  - Dream-Fehlerwarnung
- ✅ `hooks-disable`, `hooks-enable`, `hooks-status` als auf Nachfrage verfügbare Zusatzbefehle aufgenommen.
- ✅ `session-start-context` bleibt als vollständiger Detailpfad mit Prefix.
- ✅ Basiskontext und kontextsensitive Ergänzungen gegen Fixtures und bestehende End-to-End-Tests verifiziert.
