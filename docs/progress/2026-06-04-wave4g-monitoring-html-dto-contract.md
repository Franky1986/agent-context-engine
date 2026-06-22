# 2026-06-04 - Agent Context Engine Monitoring UI HTML/DTO Contract (Wave 4g)

## Scope

The monitoring UI in `backend/src/agent_context_engine/interfaces/http/html.py` may only
read server state through documented `/api/*` payloads. This document is the
contract checked by `scripts/check-agent-context-engine`.

## 1) Matched HTML Endpoints

- `/api/status`
- `/api/storage`
- `/api/storage/neo4j`
- `/api/search`
- `/api/retrieve`
- `/api/retrieval-runs`
- `/api/retrieval-run`
- `/api/personal`
- `/api/personal-file`
- `/api/dreams`
- `/api/dream-queue`
- `/api/graph`
- `/api/graph-table-options`
- `/api/graph-types`
- `/api/graph-type`
- `/api/graph-entity`
- `/api/graph-relation`
- `/api/graph-artifact`
- `/api/filter-options`
- `/api/stats`
- `/api/reports`
- `/api/report-file`
- `/api/sessions`
- `/api/session`
- `/api/analyze-session`
- `/api/risk-events`
- `/api/risk-event`
- `/api/risk-review`
- `/api/firewall-state`
- `/api/firewall-suggest`
- `/api/firewall-rule`
- `/api/firewall-rule-version`
- `/api/firewall-override`
- `/api/dream-graph`
- `/api/dream-v2-evaluate`
- `/api/dream-v2-projection-dry-run`
- `/api/dream-v2-fixture-evaluate`
- `/api/dream-v2-apply`
- `/api/dream-v2-review`
- `/api/firewall-rules`
- `/api/firewall-suggestions`

## 2) Field Mapping For UI Use Cases

### `/api/status`
- UI: `monitor_version`, `runner`, `sessions`, `events`
- Producer: `monitor_status`

### `/api/storage`
- UI: `sqlite_version`, `session_count`, `last_write`
- Producer: `monitor_storage_overview`

### `/api/storage/neo4j`
- UI: `available`, `neo4j_running`, `summary`
- Producer: `monitor_storage_neo4j`

### `/api/search`
- UI: `results[]`
- Producer: `monitor_search`

### `/api/retrieve`
- UI: `retrieval_run_id`, `results`
- Producer: `monitor_retrieve`

### `/api/retrieval-runs`
- UI: `runs[]`
- Producer: `monitor_retrieval_runs`

### `/api/retrieval-run`
- UI: `run`, `results`, `access`
- Producer: `monitor_retrieval_run`

### `/api/personal`
- UI: `total`, `files[]`
- Producer: `monitor_personal_files`

### `/api/personal-file`
- UI: `path`, `frontmatter`, `content`
- Producer: `monitor_personal_file`

### `/api/dreams`
- UI: `totals`, `dreams[]`
- Producer: `monitor_dreams`

### `/api/dream-queue`
- UI: `runs[]`, `total`
- Producer: `monitor_dream_queue`

### `/api/graph`
- UI: `nodes`, `links`, `source`
- Producer: `sqlite_graph`, `neo4j_graph`

### `/api/graph-table-options`
- UI: `entity_types`, `relation_types`, `overview`
- Producer: `graph_table_options`

### `/api/graph-types`
- UI: `types`, `total`
- Producer: `graph_type_rows`

### `/api/graph-type`
- UI: `type`, `entities`, `relations`
- Producer: `graph_type_detail`

### `/api/graph-entity`
- UI: `entity`, `relations`, `evidence`
- Producer: `graph_entity_detail`

### `/api/graph-relation`
- UI: `relation`, `endpoint_relations`, `evidence`
- Producer: `graph_relation_detail`

### `/api/graph-artifact`
- UI: `artifact`
- Producer: `monitor_graph_artifact_detail`

### `/api/filter-options`
- UI: `projects`, `workdirs`, `clients`
- Producer: `monitor_filter_options`

### `/api/stats`
- UI: `buckets[]`, `totals`
- Producer: `monitor_stats`

### `/api/reports`
- UI: `reports`, `total`
- Producer: `_list_reports`

### `/api/report-file`
- UI: `filename`, `path`
- Producer: `_get_report_file`

### `/api/sessions`
- UI: `sessions[]`, `total`, `clients`, `projects`, `workdirs`
- Producer: `monitor_sessions`

### `/api/session`
- UI: `session`, `summary`, `dreams`, `graph_artifacts`, `events`
- Producer: `monitor_session_detail`

### `/api/analyze-session`
- UI: `ok`, `filename`, `report_url`
- Producer: `analyze_session`

### `/api/risk-events`
- UI: `total`, `totals`, `events`, `firewall`
- Producer: `monitor_risk_events`

### `/api/risk-event`
- UI: `risk_event`, `evidence`, `overrides`, `classifier`, `graph`, `raw`
- Producer: `monitor_risk_event`

### `/api/risk-review`
- UI: `result`
- Producer: `risk_review_action`

### `/api/firewall-state`
- UI: `enabled`, `overrides`, `rules`, `firewall`
- Producer: `monitor_firewall_state`

### `/api/firewall-suggest`
- UI: `suggested_command`
- Producer: `monitor_firewall_suggest`

### `/api/firewall-rule`
- UI: `rule`
- Producer: `monitor_firewall_rule`

### `/api/firewall-rule-version`
- UI: `rule`, `firewall`
- Producer: `monitor_firewall_rule_version`

### `/api/firewall-override`
- UI: `override`, `firewall`
- Producer: `monitor_create_firewall_override`, `monitor_revoke_firewall_override`

### `/api/dream-graph`
- UI: `graph_artifact`, `nodes`, `links`
- Producer: `monitor_dream_graph`

### `/api/dream-v2-evaluate`
- UI: `result`, `run_id`, `status`
- Producer: `dream_v2_evaluate`

### `/api/dream-v2-projection-dry-run`
- UI: `result`, `status`, `summary`
- Producer: `monitor_dream_v2_projection_dry_run`

### `/api/dream-v2-fixture-evaluate`
- UI: `result`, `status`, `summary`
- Producer: `monitor_dream_v2_fixture_evaluate`

### `/api/dream-v2-apply`
- UI: `result`, `status`, `summary`
- Producer: `monitor_dream_v2_apply`

### `/api/dream-v2-review`
- UI: `ok`, `result`, `status`
- Producer: `monitor_dream_v2_review`

### `/api/firewall-rules`
- UI: `rules`, `total`
- Producer: `monitor_firewall_rules`

### `/api/firewall-suggestions`
- UI: `suggestions`, `policy`
- Producer: `monitor_firewall_suggestions`

## 3) Readiness Check

- [ ] Live runtime rendering validation is still open (`status`, `search`, `retrieve`, `personal`, `retrieval`).
- [x] Server-route and contract sections must stay matched by `monitoring-contract-gate`.
- [x] `analyze-session` must not depend on direct CLI calls in the monitoring path.
