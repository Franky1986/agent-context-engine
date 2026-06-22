import { apiDelete, apiGet, apiPost } from './client';
import type { MemoryView } from '../../app/monitorUi';
import type {
  CreateFirewallOverrideRequest,
  DreamRunListResponse,
  DreamGraphResponse,
  DreamV2EvaluationResponse,
  DiagnosticsStatus,
  FirewallState,
  FirewallRulesResponse,
  FirewallSuggestionsResponse,
  FirewallOverrideMutationResult,
  GraphEntityListResponse,
  GraphQueryResponse,
  GraphRelationListResponse,
  GraphTableOptions,
  InstallationCheckResponse,
  IntegrationSummary,
  MonitorStatus,
  MonitorStatsResponse,
  Neo4jStorageStatus,
  PersonalFile,
  PersonalFilesResponse,
  RepoIndexFile,
  RevokeFirewallOverrideRequest,
  RiskDetail,
  RiskListResponse,
  SessionDetail,
  SessionListResponse,
  SetFirewallStateRequest,
  StorageStatus,
} from './types';

export function getMonitorStatus() {
  return apiGet<MonitorStatus>('/api/status');
}

export function reconcileRuntime() {
  return apiPost<{ status?: string; result?: Record<string, unknown> }>('/api/runtime/reconcile', {});
}

export function getIntegrations() {
  return apiGet<IntegrationSummary>('/api/integrations');
}

export function getInstallationCheck() {
  return apiGet<InstallationCheckResponse>('/api/installation-check');
}

export function getDiagnostics() {
  return apiGet<DiagnosticsStatus>('/api/diagnostics');
}

export function getFirewallState() {
  return apiGet<FirewallState>('/api/firewall-state');
}

export function setFirewallState(payload: SetFirewallStateRequest) {
  return apiPost<FirewallState>('/api/firewall-state', payload);
}

export type FirewallRulesQueryOptions = {
  status?: string;
  kind?: string;
  limit?: number;
};

export function getFirewallRules(options: FirewallRulesQueryOptions = {}) {
  const params = new URLSearchParams();
  if (options.status) {
    params.set('status', options.status);
  }
  if (options.kind) {
    params.set('kind', options.kind);
  }
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit));
  }
  const suffix = params.size ? `?${params.toString()}` : '';
  return apiGet<FirewallRulesResponse>(`/api/firewall-rules${suffix}`);
}

export function getFirewallSuggestions(limit = 20) {
  return apiGet<FirewallSuggestionsResponse>(`/api/firewall-suggestions?limit=${limit}`);
}

export type SessionQueryOptions = {
  offset?: number;
  q?: string;
  client?: string;
  project?: string;
  workdir?: string;
  kind?: string;
};

export function getSessions(limit = 10, options: SessionQueryOptions = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (options.offset !== undefined) {
    params.set('offset', String(options.offset));
  }
  if (options.q) {
    params.set('q', options.q);
  }
  if (options.client) {
    params.set('client', options.client);
  }
  if (options.project) {
    params.set('project', options.project);
  }
  if (options.workdir) {
    params.set('workdir', options.workdir);
  }
  if (options.kind) {
    params.set('kind', options.kind);
  }
  return apiGet<SessionListResponse>(`/api/sessions?${params.toString()}`);
}

export type SessionDetailSection = 'summary' | 'dreams' | 'messages' | 'events' | 'graph_artifacts' | 'analysis_reports';

export type SessionDetailOptions = {
  eventLimit?: number;
  eventOffset?: number;
  include?: Array<SessionDetailSection | 'base'>;
};

export function getSessionDetail(id: string, options: SessionDetailOptions = {}) {
  const params = new URLSearchParams();
  params.set('id', id);
  if (options.eventLimit !== undefined) {
    params.set('event_limit', String(options.eventLimit));
  }
  if (options.eventOffset !== undefined) {
    params.set('event_offset', String(options.eventOffset));
  }
  if (options.include) {
    params.set('include', options.include.join(','));
  }
  return apiGet<SessionDetail>(`/api/session?${params.toString()}`);
}

export type StatsQueryOptions = {
  range?: string;
  start?: string;
  end?: string;
  client?: string;
  project?: string;
  workdir?: string;
};

export function getStats(options: StatsQueryOptions = {}) {
  const params = new URLSearchParams();
  if (options.range) {
    params.set('range', options.range);
  }
  if (options.start) {
    params.set('start', options.start);
  }
  if (options.end) {
    params.set('end', options.end);
  }
  if (options.client) {
    params.set('client', options.client);
  }
  if (options.project) {
    params.set('project', options.project);
  }
  if (options.workdir) {
    params.set('workdir', options.workdir);
  }
  const suffix = params.size ? `?${params.toString()}` : '';
  return apiGet<MonitorStatsResponse>(`/api/stats${suffix}`);
}

export function getPersonalFiles() {
  return apiGet<PersonalFilesResponse>('/api/personal');
}

export function getPersonalFile(path: string) {
  return apiGet<PersonalFile>(`/api/personal-file?path=${encodeURIComponent(path)}`);
}

export function savePersonalFile(path: string, content: string) {
  return apiPost<PersonalFile>('/api/personal-file', { path, content });
}

export function getRepoIndex() {
  return apiGet<RepoIndexFile>('/api/repo-index');
}

export function saveRepoIndex(content: string) {
  return apiPost<RepoIndexFile>('/api/repo-index', { content });
}

export function getRisks(limit = 10) {
  return apiGet<RiskListResponse>(`/api/risks?limit=${limit}`);
}

export function getRiskDetail(id: string) {
  return apiGet<RiskDetail>(`/api/risk?id=${encodeURIComponent(id)}`);
}

export type DreamQueryOptions = {
  status?: string;
  runner?: string;
  sessionId?: string;
};

export function getDreams(limit = 10, options: DreamQueryOptions = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (options.status) {
    params.set('status', options.status);
  }
  if (options.runner) {
    params.set('runner', options.runner);
  }
  if (options.sessionId) {
    params.set('session', options.sessionId);
  }
  return apiGet<DreamRunListResponse>(`/api/dreams?${params.toString()}`);
}

export function evaluateDreamV2(limit = 10) {
  return apiGet<DreamV2EvaluationResponse>(`/api/dream-v2-evaluate?limit=${limit}`);
}

export function getDreamGraph(dreamRunId: string) {
  return apiGet<DreamGraphResponse>(`/api/dream-graph?dream_run_id=${encodeURIComponent(dreamRunId)}`);
}

export function getGraphTableOptions() {
  return apiGet<GraphTableOptions>('/api/graph-table-options');
}

export function getGraphEntities(limit = 10, memoryView: MemoryView = 'both') {
  return apiGet<GraphEntityListResponse>(`/api/graph-entities?limit=${limit}&memory_view=${encodeURIComponent(memoryView)}`);
}

export function getGraphRelations(limit = 10, memoryView: MemoryView = 'both') {
  return apiGet<GraphRelationListResponse>(`/api/graph-relations?limit=${limit}&memory_view=${encodeURIComponent(memoryView)}`);
}

export function getGraphEntityDetail(id: string, memoryView: MemoryView = 'both') {
  return apiGet<Record<string, unknown>>(`/api/graph-entity?id=${encodeURIComponent(id)}&memory_view=${encodeURIComponent(memoryView)}`);
}

export function getGraphRelationDetail(id: string, memoryView: MemoryView = 'both') {
  return apiGet<Record<string, unknown>>(`/api/graph-relation?id=${encodeURIComponent(id)}&memory_view=${encodeURIComponent(memoryView)}`);
}

export function queryGraph(query: string, view = 'search', source: 'sqlite' | 'neo4j' = 'sqlite', limit = 40, memoryView: MemoryView = 'both') {
  const params = new URLSearchParams({
    q: query,
    view,
    source,
    limit: String(limit),
    memory_view: memoryView,
  });
  return apiGet<GraphQueryResponse>(`/api/graph?${params.toString()}`);
}

export function getStorage() {
  return apiGet<StorageStatus>('/api/storage');
}

export function getNeo4jStorage() {
  return apiGet<Neo4jStorageStatus>('/api/storage/neo4j');
}

export function createFirewallOverride(payload: CreateFirewallOverrideRequest) {
  return apiPost<FirewallOverrideMutationResult>('/api/firewall-override', payload);
}

export function revokeFirewallOverride(payload: RevokeFirewallOverrideRequest) {
  return apiDelete<FirewallOverrideMutationResult>('/api/firewall-override', payload);
}
