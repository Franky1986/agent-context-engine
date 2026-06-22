import type { MonitorLanguage } from '../monitorUi';
import type { FirewallState } from '../../shared/api/types';
import { t } from './index';

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

export function booleanLabel(language: MonitorLanguage, value: unknown) {
  if (value === true) return t(language, 'common.yes');
  if (value === false) return t(language, 'common.no');
  return text(value, t(language, 'common.unknown'));
}

export function firewallScopeLabel(language: MonitorLanguage, value: unknown) {
  const key = text(value, '').toLowerCase();
  const map: Record<string, string> = {
    global: 'firewall.scope.global',
    session: 'firewall.scope.session',
    project: 'firewall.scope.project',
    workdir: 'firewall.scope.workdir',
    agent: 'firewall.scope.agent',
  };
  return map[key] ? t(language, map[key]) : text(value);
}

export function firewallReasonLabel(language: MonitorLanguage, value: unknown) {
  const reason = text(value, '').trim().toLowerCase();
  const map: Record<string, string> = {
    'default enabled': 'firewall.reason.defaultEnabled',
    'enabled from react monitor': 'firewall.reason.enabledFromMonitor',
    'temporarily disabled from react monitor': 'firewall.reason.temporarilyDisabledFromMonitor',
    'permanently disabled from react monitor': 'firewall.reason.permanentlyDisabledFromMonitor',
    'enabled by monitor': 'firewall.reason.enabledByMonitor',
    'disabled by monitor': 'firewall.reason.disabledByMonitor',
    'disable window expired': 'firewall.reason.disableWindowExpired',
  };
  return map[reason] ? t(language, map[reason]) : text(value, t(language, 'common.noneReported'));
}

export function firewallStateLabel(language: MonitorLanguage, state?: FirewallState) {
  if (!state) return t(language, 'firewall.state.loading');
  if (state.enabled) return t(language, 'firewall.state.enabled');
  if (state.disabled_until) return t(language, 'firewall.state.paused');
  return t(language, 'firewall.state.disabled');
}

export function firewallStateHint(language: MonitorLanguage, state?: FirewallState) {
  if (!state) return t(language, 'firewall.stateHint.loading');
  if (state.enabled) return t(language, 'firewall.stateHint.enabled');
  if (state.disabled_until) return t(language, 'firewall.stateHint.paused');
  return t(language, 'firewall.stateHint.disabled');
}

export function firewallDisabledUntilLabel(language: MonitorLanguage, state?: FirewallState) {
  if (!state) return t(language, 'common.loading');
  if (state.enabled) return t(language, 'common.active');
  if (!state.disabled_until) return t(language, 'firewall.disabledUntil.permanent');
  return String(state.disabled_until);
}

export function storageLabel(language: MonitorLanguage, value: unknown) {
  const raw = text(value, '').trim();
  const map: Record<string, string> = {
    'SQLite database files': 'storage.label.sqliteDatabaseFiles',
    'Status and locks': 'storage.label.statusAndLocks',
    Logs: 'storage.label.logs',
    'Hook event logs': 'storage.label.hookEventLogs',
    'Hook queue': 'storage.label.hookQueue',
    'Tool output files': 'storage.label.toolOutputFiles',
    'Session files': 'storage.label.sessionFiles',
    'Dream artifacts': 'storage.label.dreamArtifacts',
    'Memory documents': 'storage.label.memoryDocuments',
    'Graph artifacts': 'storage.label.graphArtifacts',
    'Personal memory': 'storage.label.personalMemory',
    'Personal proposals': 'storage.label.personalProposals',
    'Analysis reports': 'storage.label.analysisReports',
    'Local config': 'storage.label.localConfig',
    Sessions: 'storage.label.sessions',
    Events: 'storage.label.events',
    'Dream runs': 'storage.label.dreamRuns',
    'Memory chunks': 'storage.label.memoryChunks',
    'Retrieval runs': 'storage.label.retrievalRuns',
    'Graph entities': 'storage.label.graphEntities',
    'Graph relations': 'storage.label.graphRelations',
    'Tool output metadata': 'storage.label.toolOutputMetadata',
    'Risk events': 'storage.label.riskEvents',
    'Classifier runs': 'storage.label.classifierRuns',
    'Scheduler runs': 'storage.label.schedulerRuns',
    'Neo4j imports': 'storage.label.neo4jImports',
    Entities: 'storage.entities',
    Relations: 'storage.relations',
    Evidence: 'storage.evidence',
    Größe: 'storage.size',
    Konfiguriert: 'storage.section.configuration',
    URI: 'storage.meta.uri',
    Datenbank: 'storage.meta.database',
    Nutzer: 'storage.meta.user',
  };
  return map[raw] ? t(language, map[raw]) : text(value);
}

export function storageDescription(language: MonitorLanguage, value: unknown) {
  const raw = text(value, '').trim();
  const map: Record<string, string> = {
    'Main SQLite database plus WAL/SHM files.': 'storage.description.sqliteFiles',
    'Runtime status files and lock metadata.': 'storage.description.statusAndLocks',
    'Hook, scheduler, monitor, and runtime logs.': 'storage.description.logs',
    'Legacy raw JSONL hook event logs.': 'storage.description.hookEventLogs',
    'Deferred hook events waiting for processing.': 'storage.description.hookQueue',
    'Legacy raw tool-output files; current builds keep only metadata.': 'storage.description.toolOutputFiles',
    'Per-session summary and handover artifacts.': 'storage.description.sessionFiles',
    'Dream run outputs, graph patches, and extraction artifacts.': 'storage.description.dreamArtifacts',
    'Materialized memory documents indexed for retrieval.': 'storage.description.memoryDocuments',
    'Graph import/export artifacts outside SQLite and Neo4j.': 'storage.description.graphArtifacts',
    'User-curated personal memory markdown files.': 'storage.description.personalMemory',
    'Pending personal-memory proposals.': 'storage.description.personalProposals',
    'Generated session analysis reports.': 'storage.description.analysisReports',
    'Local-only config such as Neo4j env files.': 'storage.description.localConfig',
  };
  return map[raw] ? t(language, map[raw]) : text(value, t(language, 'storage.description.none'));
}
