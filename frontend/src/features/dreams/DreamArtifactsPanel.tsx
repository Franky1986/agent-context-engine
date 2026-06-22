import { useEffect, useRef, useState } from 'react';
import { t } from '../../app/i18n';
import type { MemoryView, MonitorLanguage } from '../../app/monitorUi';
import { evaluateDreamV2, getDreamGraph } from '../../shared/api/monitor';
import type { DreamGraphResponse, DreamRun, DreamV2EvaluationItem, DreamV2EvaluationResponse } from '../../shared/api/types';
import { dreamNarrativeSections } from './dreamNarrative';
import './dream-artifacts-panel.css';

export type DreamArtifactsPanelProps = {
  initialEvaluation?: DreamV2EvaluationResponse;
  initialGraph?: DreamGraphResponse;
  selectedDream?: DreamRun;
  focus?: 'deterministic_entities' | 'deterministic_relations' | 'semantic_entities' | 'semantic_relations';
  onOpenSession?: (sessionId: string) => void;
  onOpenKnowledge?: () => void;
  onOpenControl?: () => void;
  language?: MonitorLanguage;
  memoryView?: MemoryView;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function pretty(value: unknown) {
  return JSON.stringify(value ?? null, null, 2);
}

function formatNumber(value: unknown) {
  if (typeof value === 'number') return new Intl.NumberFormat().format(value);
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) {
    return new Intl.NumberFormat().format(Number(value));
  }
  return text(value);
}

function list(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function records(value: unknown): Record<string, unknown>[] {
  return list(value).map(record).filter((item) => Object.keys(item).length > 0);
}

function parseJson(value: unknown): unknown {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}

function filePath(file: Record<string, unknown>) {
  return text(file.path ?? file.artifact_path ?? file.name, '');
}

function fileContent(file: Record<string, unknown>) {
  return file.content ?? file.text ?? file.payload;
}

function pathIncludes(file: Record<string, unknown>, needle: string) {
  return filePath(file).includes(needle);
}

function findFile(files: Record<string, unknown>[], needle: string) {
  return files.find((file) => pathIncludes(file, needle));
}

function jsonFile(files: Record<string, unknown>[], needle: string): Record<string, unknown> {
  return record(parseJson(fileContent(findFile(files, needle) ?? {})));
}

function stagePrefix(stage: Record<string, unknown>) {
  const path = text(stage.prompt_path ?? stage.raw_output_path ?? stage.parsed_output_path ?? stage.artifact_path, '');
  const match = path.match(/\/(\d{2}-[^/]+)\//);
  return match?.[1] ?? text(stage.stage_name, '');
}

function confidence(value: unknown) {
  if (typeof value === 'number') return `${Math.round(value * 100)}%`;
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) return `${Math.round(Number(value) * 100)}%`;
  return text(value);
}

function compactJson(value: unknown) {
  const payload = pretty(value);
  return payload.length > 1200 ? `${payload.slice(0, 1200)}\n...` : payload;
}

function compactText(value: unknown, limit = 220, fallback = '-') {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

function formatDurationMs(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '-';
  const totalSeconds = Math.round(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

function decisionCounts(decisions: Record<string, unknown>[]) {
  const counts = new Map<string, number>();
  decisions.forEach((decision) => {
    const action = text(decision.decision, text(decision.action, 'unknown'));
    counts.set(action, (counts.get(action) ?? 0) + 1);
  });
  return Array.from(counts.entries());
}

function mutationBadge(item: Record<string, unknown>) {
  const mutations = records(item.mutations);
  const first = record(mutations[0]);
  if (text(first.mutation_kind, '') !== '') return text(first.mutation_kind);
  if (item.was_updated) return 'updated';
  return 'created';
}

function mutationCounts(items: Record<string, unknown>[]) {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const kind = mutationBadge(item);
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  });
  return counts;
}

type QuickPeekEntry = {
  label: string;
  meta?: string;
};

function entityDisplayName(item: Record<string, unknown>): QuickPeekEntry {
  const label = text(item.name ?? item.proposed_name ?? item.entity_key ?? item.key ?? item.proposal_id, 'unknown');
  const type = text(item.entity_type ?? item.type, '');
  const key = text(item.entity_key ?? item.key, '');
  const metaParts = [type, key && key !== label ? key : ''].filter(Boolean);
  return {
    label,
    meta: metaParts.join(' · '),
  };
}

function relationDisplayName(item: Record<string, unknown>, language: MonitorLanguage): QuickPeekEntry {
  const type = text(item.relation_type ?? item.type ?? item.proposed_type, t(language, 'graph.relationFallback'));
  const source = text(item.source_entity_key ?? record(item.from).key ?? item.source_ref, '');
  const target = text(item.target_entity_key ?? record(item.to).key ?? item.target_ref, '');
  if (source || target) {
    return {
      label: `${type}: ${source || '?'} -> ${target || '?'}`,
    };
  }
  return { label: type };
}

function handoverUsage(stages: Record<string, unknown>[]) {
  const promptFile = stages
    .flatMap((stage) => records(stage.files))
    .find((file) => text(file.kind, '') === 'prompt' || /prompt\.md$/.test(filePath(file)));
  const prompt = text(fileContent(promptFile ?? {}), '');
  if (!prompt) return 'unknown';
  if (/Current Session Handover/i.test(prompt) && !/_No current handover available\._/i.test(prompt)) {
    return 'yes';
  }
  if (/_No current handover available\._/i.test(prompt)) {
    return 'no';
  }
  return 'unknown';
}

function dreamOutcomeSummary(
  selectedDream: DreamRun | undefined,
  decisions: Record<string, unknown>[],
  language: MonitorLanguage,
) {
  const item = record(selectedDream);
  const summary = item.episode_short
    ?? item.episode_title
    ?? item.error_message
    ?? item.error
    ?? item.intent
    ?? item.pipeline_status
    ?? item.status;
  const decisionSummary = decisionCounts(decisions)
    .slice(0, 3)
    .map(([action, count]) => `${action} ${count}`)
    .join(' · ');
  if (decisionSummary) {
    return compactText(`${summary} · ${decisionSummary}`, 240, t(language, 'dreamArtifacts.summaryFallback'));
  }
  return compactText(summary, 240, t(language, 'dreamArtifacts.summaryFallback'));
}

function QuickPeekList({
  title,
  items,
  formatter,
  language,
}: {
  title: string;
  items: Record<string, unknown>[];
  formatter: (item: Record<string, unknown>) => QuickPeekEntry;
  language: MonitorLanguage;
}) {
  const entries = items
    .map(formatter)
    .filter((item) => item && item.label && item.label !== '-');
  return (
    <details className="dream-quickpeek">
      <summary>{title} ({entries.length})</summary>
      {entries.length ? (
        <ul className="dream-quickpeek-list">
          {entries.slice(0, 10).map((entry, index) => (
            <li key={`${entry.label}-${entry.meta ?? ''}-${index}`}>
              <span className="dream-quickpeek-label">{entry.label}</span>
              {entry.meta ? <small className="dream-quickpeek-meta">{entry.meta}</small> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="dream-quickpeek-empty">{t(language, 'dreamArtifacts.quickPeek.empty')}</p>
      )}
      {entries.length > 10 ? (
        <small className="dream-quickpeek-more">
          {t(language, 'dreamArtifacts.quickPeek.more', { count: entries.length - 10 })}
        </small>
      ) : null}
    </details>
  );
}

function ProposalCard({
  item,
  candidates,
  kind,
  language,
}: {
  item: Record<string, unknown>;
  candidates?: Record<string, unknown>[];
  kind: string;
  language: MonitorLanguage;
}) {
  const evidence = records(item.evidence);
  return (
    <article className="dream-semantic-card">
      <div className="semantic-card-title">
        <span>{kind}</span>
        <strong>{text(item.name ?? item.proposal_id ?? item.type)}</strong>
      </div>
      <div className="dream-chip-row">
        <span>{text(item.type)}</span>
        <span>{confidence(item.confidence)}</span>
        {item.review_required ? <span>{t(language, 'dreamArtifacts.review')}</span> : null}
      </div>
      <p>{text(item.summary ?? item.review_reason, t(language, 'dreamArtifacts.proposal.noSummary'))}</p>
      {text(item.source_ref, '') || text(item.target_ref, '') ? (
        <p className="semantic-link">{text(item.source_ref)} {'->'} {text(item.target_ref)}</p>
      ) : null}
      {evidence.length ? (
        <details>
          <summary>{t(language, 'dreamArtifacts.proposal.evidence')} ({evidence.length})</summary>
          <ul className="dream-evidence-list">
            {evidence.map((entry, index) => (
              <li key={index}>
                <span>#{text(entry.event_seq, '?')}</span>
                <q>{text(entry.quote ?? entry.summary)}</q>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {candidates?.length ? (
        <details open>
          <summary>{t(language, 'dreamArtifacts.proposal.matches')} ({candidates.length})</summary>
          <div className="candidate-list">
            {candidates.map((candidate, index) => (
              <div className="candidate-row" key={`${text(candidate.entity_key)}-${index}`}>
                <strong>{text(candidate.name ?? candidate.entity_key)}</strong>
                <span>{text(candidate.entity_type)} · {confidence(candidate.confidence)}</span>
                <small>{text(candidate.summary)}</small>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </article>
  );
}

export function DreamArtifactsPanel({
  initialEvaluation,
  initialGraph,
  selectedDream,
  focus,
  onOpenSession,
  onOpenKnowledge,
  onOpenControl,
  language = 'en',
  memoryView = 'both',
}: DreamArtifactsPanelProps) {
  const [evaluation, setEvaluation] = useState<DreamV2EvaluationResponse | undefined>(initialEvaluation);
  const [graph, setGraph] = useState<DreamGraphResponse | undefined>(initialGraph);
  const [error, setError] = useState('');
  const deterministicSectionRef = useRef<HTMLDetailsElement | null>(null);
  const semanticSectionRef = useRef<HTMLDetailsElement | null>(null);

  const selectedDreamId = selectedDream?.dream_run_id;

  useEffect(() => {
    if (initialEvaluation) {
      setEvaluation(initialEvaluation);
      return;
    }
    let cancelled = false;
    evaluateDreamV2(25)
      .then((payload) => {
        if (cancelled) return;
        setEvaluation(payload);
        setError('');
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [initialEvaluation]);

  useEffect(() => {
    if (initialGraph && !selectedDreamId) {
      setGraph(initialGraph);
      return;
    }
    if (!selectedDreamId) {
      setGraph(undefined);
      return;
    }
    let cancelled = false;
    getDreamGraph(selectedDreamId)
      .then((payload) => {
        if (cancelled) return;
        setGraph(payload);
        setError('');
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [initialGraph, selectedDreamId]);

  const runs: DreamV2EvaluationItem[] = evaluation?.runs ?? evaluation?.items ?? [];
  const selectedEvaluation = runs.find((run) => run.dream_run_id === selectedDreamId);
  const entities = graph?.entities ?? [];
  const relations = graph?.relations ?? [];
  const auditFiles = list(record(selectedDream).audit_files);
  const downstreamFiles = list(record(selectedDream).downstream_files);
  const outputPaths = list(record(selectedDream).output_memory_paths ?? record(selectedDream).output_memory_paths_json);
  const artifactFiles = list(record(selectedDream).v2_artifacts);
  const allFiles = [...auditFiles, ...downstreamFiles, ...artifactFiles].map(record);
  const stages = records(record(selectedDream).v2_stages).sort((left, right) => {
    return Number(left.stage_order ?? 0) - Number(right.stage_order ?? 0);
  });
  const proposalPayload = jsonFile(allFiles, 'semantic-proposals.json');
  const candidatePayload = jsonFile(allFiles, 'candidates.json');
  const decisionPayload = jsonFile(allFiles, 'decisions.json');
  const finalPatch = jsonFile(allFiles, 'final-semantic-patch.json');
  const sqliteWrites = jsonFile(allFiles, 'sqlite-writes.json');
  const neo4jSync = jsonFile(allFiles, 'neo4j-sync.json');
  const entityProposals = records(proposalPayload.entities);
  const relationProposals = records(proposalPayload.relations);
  const schemaProposals = records(proposalPayload.schema_proposals);
  const candidateMap = record(candidatePayload.candidates);
  const decisions = records(decisionPayload.decisions ?? record(selectedDream).v2_reconciliation_decisions);
  const persistedEntities = records(finalPatch.entities ?? record(selectedDream).v2_semantic_entities);
  const persistedRelations = records(finalPatch.relations ?? record(selectedDream).v2_semantic_relations);
  const deterministicEntities = records(record(selectedDream).v2_deterministic_entities);
  const deterministicRelations = records(record(selectedDream).v2_deterministic_relations);
  const reviewItems = records(record(selectedDream).v2_review_items);
  const entityMutationCounts = mutationCounts(persistedEntities);
  const relationMutationCounts = mutationCounts(persistedRelations);
  const durationMs = selectedDream ? Number(selectedDream.duration_ms ?? 0) : 0;
  const durationSeconds = formatDurationMs(durationMs);
  const llmStages = stages.filter((stage) => text(stage.category, '') === 'llm_call');
  const llmStageDurationMs = llmStages.reduce((sum, stage) => sum + Number(stage.duration_ms ?? 0), 0);
  const llmStageTokens = llmStages.reduce((sum, stage) => sum + Number(stage.total_tokens ?? 0), 0);
  const handoverUsed = handoverUsage(stages);
  const outcomeSummary = dreamOutcomeSummary(selectedDream, decisions, language);
  const narrative = dreamNarrativeSections(record(selectedDream));
  const decisionSummary = decisionCounts(decisions);
  const createdEntities = entityMutationCounts.get('created') ?? 0;
  const updatedEntities = entityMutationCounts.get('updated') ?? 0;
  const createdRelations = relationMutationCounts.get('created') ?? 0;
  const updatedRelations = relationMutationCounts.get('updated') ?? 0;
  const showDeterministic = memoryView !== 'semantic';
  const showSemantic = memoryView !== 'deterministic';
  const deterministicSectionOpen = focus === 'deterministic_entities' || focus === 'deterministic_relations';
  const semanticSectionOpen = focus === 'semantic_entities' || focus === 'semantic_relations';

  useEffect(() => {
    const target = deterministicSectionOpen ? deterministicSectionRef.current : semanticSectionOpen ? semanticSectionRef.current : null;
    if (!target) return;
    window.requestAnimationFrame(() => {
      target.scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
  }, [deterministicSectionOpen, semanticSectionOpen, selectedDreamId]);

  return (
    <section className="dream-artifacts-panel">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'dreamArtifacts.heading')}</p>
        <h2>{text(selectedDreamId, t(language, 'dreamArtifacts.selectRun'))}</h2>
        <span>{allFiles.length} files · {entities.length} entities · {relations.length} relations</span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}

      {selectedDream ? (
        <>
          <div className="dream-top-kpis">
            <article className="dream-top-kpi">
              <small>{t(language, 'dreamArtifacts.wallTime')}</small>
              <strong>{durationSeconds}</strong>
            </article>
            <article className="dream-top-kpi">
              <small>{t(language, 'dreamArtifacts.llmCalls')}</small>
              <strong>{formatNumber(llmStages.length)}</strong>
            </article>
            <article className="dream-top-kpi">
              <small>{t(language, 'dreamArtifacts.llmCumulative')}</small>
              <strong>{formatDurationMs(llmStageDurationMs)}</strong>
            </article>
            <article className="dream-top-kpi">
              <small>{t(language, 'dreamArtifacts.llmTokens')}</small>
              <strong>{formatNumber(llmStageTokens)}</strong>
            </article>
          </div>

          <div className="dream-summary-grid">
            <article className="dream-summary-card dream-summary-card-accent">
              <p className="eyebrow">{t(language, 'dreamArtifacts.summary')}</p>
              <h3>{text(selectedDream.status)} / {text(selectedDream.pipeline_status)}</h3>
              <p className="dream-summary-copy">{outcomeSummary}</p>
              <div className="dream-chip-row">
                <span>{text(selectedDream.runner)} {text(selectedDream.runner_model, '')}</span>
                <span>{text(selectedDream.session_id)}</span>
                <span>{t(language, 'dreamArtifacts.handover')} {handoverUsed}</span>
                <span>{t(language, 'dreamArtifacts.wallTime')} {durationSeconds}</span>
                <span>{t(language, 'dreamArtifacts.llmCalls')} {llmStages.length}</span>
                <span>{t(language, 'dreamArtifacts.llmCumulative')} {formatDurationMs(llmStageDurationMs)}</span>
              </div>
            </article>

            {showSemantic ? (
              <article className="dream-summary-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.semanticImpact')}</p>
                <h3>{persistedEntities.length} entities · {persistedRelations.length} relations</h3>
                <p className="dream-summary-copy">
                  {t(language, 'dreamArtifacts.newEntities')} {createdEntities}, {t(language, 'dreamArtifacts.updatedEntities')} {updatedEntities}, {t(language, 'dreamArtifacts.newRelations')} {createdRelations}, {t(language, 'dreamArtifacts.updatedRelations')} {updatedRelations}.
                </p>
                <div className="dream-chip-row">
                  <span>{reviewItems.length} {t(language, 'dreamArtifacts.reviewItems')}</span>
                  <span>{decisions.length} {t(language, 'dreamArtifacts.decisions')}</span>
                </div>
                <div className="dream-quickpeek-grid">
                  <QuickPeekList
                    formatter={entityDisplayName}
                    items={persistedEntities}
                    language={language}
                    title={t(language, 'dreamArtifacts.inspectEntities')}
                  />
                  <QuickPeekList
                    formatter={(item) => relationDisplayName(item, language)}
                    items={persistedRelations}
                    language={language}
                    title={t(language, 'dreamArtifacts.inspectRelations')}
                  />
                </div>
              </article>
            ) : null}

            {showDeterministic ? (
              <article className="dream-summary-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.deterministic')}</p>
                <h3>{deterministicEntities.length} entities · {deterministicRelations.length} relations</h3>
                <p className="dream-summary-copy">
                  {t(language, 'dreamArtifacts.deterministicCopy')}
                </p>
                <div className="dream-chip-row">
                  <span>{formatNumber(selectedDream.input_event_count)} {t(language, 'sessionDetail.events')}</span>
                  <span>{formatNumber(selectedDream.total_tokens)} tokens</span>
                  <span>{durationSeconds}</span>
                </div>
                <div className="dream-quickpeek-grid">
                  <QuickPeekList
                    formatter={entityDisplayName}
                    items={deterministicEntities}
                    language={language}
                    title={t(language, 'dreamArtifacts.inspectEntities')}
                  />
                  <QuickPeekList
                    formatter={(item) => relationDisplayName(item, language)}
                    items={deterministicRelations}
                    language={language}
                    title={t(language, 'dreamArtifacts.inspectRelations')}
                  />
                </div>
              </article>
            ) : null}
          </div>

          <details className="dream-inspect-block" open>
            <summary>{t(language, 'dreamArtifacts.narrative')}</summary>
            <div className="dream-summary-grid">
              <article className="dream-summary-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.compact')}</p>
                <p className="dream-summary-copy">{text(narrative.compact, t(language, 'dreamArtifacts.noNarrative'))}</p>
              </article>
              <article className="dream-summary-card">
                <p className="eyebrow">{t(language, 'dreamArtifacts.summary')}</p>
                <p className="dream-summary-copy">{text(narrative.summary, t(language, 'dreamArtifacts.noNarrative'))}</p>
              </article>
            </div>
            <details className="dream-inspect-nested">
              <summary>{t(language, 'dreamArtifacts.fullDream')}</summary>
              <pre className="dream-code">{text(narrative.full, t(language, 'dreamArtifacts.noNarrative'))}</pre>
            </details>
          </details>

          <div className="dream-cta-row">
            <button
              className="dream-cta-button"
            disabled={!selectedDream.session_id || !onOpenSession}
            onClick={() => selectedDream.session_id && onOpenSession?.(selectedDream.session_id)}
            type="button"
          >
            {t(language, 'dreamArtifacts.openSession')}
          </button>
            <button
              className="dream-cta-button"
            disabled={!onOpenKnowledge}
            onClick={() => onOpenKnowledge?.()}
            type="button"
          >
            {t(language, 'dreamArtifacts.openKnowledge')}
          </button>
            <button
              className="dream-cta-button"
            disabled={!onOpenControl}
            onClick={() => onOpenControl?.()}
            type="button"
          >
            {t(language, 'dreamArtifacts.openControl')}
          </button>
          </div>

          <div className="dream-outcome-grid">
            {showDeterministic ? (
              <>
                <button className="dream-outcome-card" disabled type="button">
                  <small>{t(language, 'dreamArtifacts.deterministic')}</small>
                  <strong>{deterministicEntities.length}</strong>
                  <span>{t(language, 'common.entities')}</span>
                </button>
                <button className="dream-outcome-card" disabled type="button">
                  <small>{t(language, 'dreamArtifacts.deterministic')}</small>
                  <strong>{deterministicRelations.length}</strong>
                  <span>{t(language, 'common.relations')}</span>
                </button>
              </>
            ) : null}
            {showSemantic ? (
              <>
                <button className="dream-outcome-card" disabled type="button">
                  <small>{t(language, 'dreamArtifacts.semantic')}</small>
                  <strong>{persistedEntities.length}</strong>
                  <span>{t(language, 'common.entities')}</span>
                </button>
                <button className="dream-outcome-card" disabled type="button">
                  <small>{t(language, 'dreamArtifacts.semantic')}</small>
                  <strong>{persistedRelations.length}</strong>
                  <span>{t(language, 'common.relations')}</span>
                </button>
              </>
            ) : null}
          </div>

          <div className="dream-inspect-grid">
            <span><strong>{t(language, 'common.status')}</strong>{text(selectedDream.status)} / {text(selectedDream.pipeline_status)}</span>
            <span><strong>{t(language, 'common.runner')}</strong>{text(selectedDream.runner)} {text(selectedDream.runner_model, '')}</span>
            <span><strong>{t(language, 'common.session')}</strong>{text(selectedDream.session_id)}</span>
            <span><strong>{t(language, 'common.project')}</strong>{text(selectedDream.project_id)}</span>
            <span><strong>{t(language, 'common.events')}</strong>{text(selectedDream.input_event_seq_from)}-{text(selectedDream.input_event_seq_to)} ({text(selectedDream.input_event_count)})</span>
            <span><strong>{t(language, 'common.tokens')}</strong>{text(selectedDream.total_tokens)}</span>
            <span><strong>{t(language, 'dreamArtifacts.wallTime')}</strong>{durationSeconds}</span>
            <span><strong>{t(language, 'dreamArtifacts.llmCumulative')}</strong>{formatDurationMs(llmStageDurationMs)} · {formatNumber(llmStageTokens)} tokens</span>
            <span><strong>{t(language, 'common.started')}</strong>{text(selectedDream.started_at_local ?? selectedDream.started_at)}</span>
            <span><strong>{t(language, 'common.finished')}</strong>{text(selectedDream.finished_at_local ?? selectedDream.finished_at)}</span>
          </div>

          {decisionSummary.length ? (
            <div className="dream-chip-row dream-chip-row-summary">
              {decisionSummary.map(([action, count]) => (
                <span key={action}>{action} {count}</span>
              ))}
            </div>
          ) : null}

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.stageTimeline')}</summary>
            {stages.length ? (
              <div className="dream-stage-list">
                {stages.map((stage, index) => {
                  const prefix = stagePrefix(stage);
                  const stageFiles = allFiles.filter((file) => pathIncludes(file, `/${prefix}/`)
                    || [stage.prompt_path, stage.raw_output_path, stage.parsed_output_path, stage.artifact_path].some((path) => path && filePath(file) === text(path, '')));
                  const promptFile = stageFiles.find((file) => /prompt\.md$/.test(filePath(file)) || text(file.llm_role) === 'prompt');
                  const rawFile = stageFiles.find((file) => /raw-output\./.test(filePath(file)) || text(file.llm_role) === 'raw_output');
                  const parsedFile = stageFiles.find((file) => /semantic-proposals\.json$|decisions\.json$|final-semantic-patch\.json$|dream\.md$/.test(filePath(file)));
                  return (
                    <article className="dream-stage-card" key={`${text(stage.stage_name)}-${index}`}>
                      <div className="dream-stage-head">
                        <span>{text(stage.stage_order, String(index + 1))}</span>
                        <div>
                          <strong>{text(stage.label ?? stage.stage_name)}</strong>
                          <small>{text(stage.category)} · {text(stage.badge)} · {text(stage.status)}</small>
                        </div>
                      </div>
                      <div className="dream-chip-row">
                        <span>{text(stage.runner)}</span>
                        <span>{text(stage.model)}</span>
                        <span>{formatNumber(stage.total_tokens)} tokens</span>
                        <span>{formatNumber(stage.duration_ms)} ms</span>
                      </div>
                      {Object.keys(record(stage.validation)).length ? (
                        <details>
                          <summary>{t(language, 'dreamArtifacts.validation')}</summary>
                          <pre className="dream-pre compact">{compactJson(stage.validation)}</pre>
                        </details>
                      ) : null}
                      <div className="stage-artifact-grid">
                        {promptFile ? (
                          <details>
                            <summary>{t(language, 'dreamArtifacts.prompt')}</summary>
                            <small>{filePath(promptFile)}</small>
                            <pre className="dream-pre compact">{text(fileContent(promptFile), t(language, 'dreamArtifacts.noPrompt'))}</pre>
                          </details>
                        ) : null}
                        {rawFile ? (
                          <details>
                            <summary>{t(language, 'dreamArtifacts.modelOutput')}</summary>
                            <small>{filePath(rawFile)}</small>
                            <pre className="dream-pre compact">{text(fileContent(rawFile), t(language, 'dreamArtifacts.noModelOutput'))}</pre>
                          </details>
                        ) : null}
                        {parsedFile && parsedFile !== rawFile ? (
                          <details>
                            <summary>{t(language, 'dreamArtifacts.parsedArtifact')}</summary>
                            <small>{filePath(parsedFile)}</small>
                            <pre className="dream-pre compact">{text(fileContent(parsedFile), t(language, 'dreamArtifacts.noArtifact'))}</pre>
                          </details>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="empty-copy">{t(language, 'dreamArtifacts.noStages')}</p>
            )}
            {selectedEvaluation ? (
              <details>
                <summary>{t(language, 'dreamArtifacts.evaluationRow')}</summary>
                <pre className="dream-pre">{pretty(selectedEvaluation)}</pre>
              </details>
            ) : null}
          </details>

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.semanticProposals')}</summary>
            <div className="dream-artifact-grid">
              <article className="dream-artifact-summary">
                <strong>{entityProposals.length}</strong>
                <span>{t(language, 'dreamArtifacts.proposedEntities')}</span>
              </article>
              <article className="dream-artifact-summary">
                <strong>{relationProposals.length}</strong>
                <span>{t(language, 'dreamArtifacts.proposedRelations')}</span>
              </article>
            </div>
            <div className="dream-semantic-grid">
              {entityProposals.map((item) => (
                <ProposalCard
                  candidates={records(candidateMap[text(item.proposal_id, '')])}
                  item={item}
                  key={text(item.proposal_id)}
                  kind="Entity proposal"
                  language={language}
                />
              ))}
              {relationProposals.map((item) => (
                <ProposalCard
                  candidates={records(candidateMap[text(item.proposal_id, '')])}
                  item={item}
                  key={text(item.proposal_id)}
                  kind="Relation proposal"
                  language={language}
                />
              ))}
              {schemaProposals.map((item, index) => (
                <ProposalCard item={item} key={`${text(item.proposal_id)}-${index}`} kind="Schema proposal" language={language} />
              ))}
            </div>
            {!entityProposals.length && !relationProposals.length && !schemaProposals.length ? (
              <p className="empty-copy">{t(language, 'dreamArtifacts.noSemanticProposal')}</p>
            ) : null}
          </details>

          {showSemantic ? (
            <details className="dream-inspect-block">
              <summary>{t(language, 'dreamArtifacts.reconciliation')}</summary>
            {decisions.length ? (
              <div className="dream-decision-list">
                {decisions.map((decision, index) => (
                  <article className="dream-decision-card" key={`${text(decision.decision_id)}-${index}`}>
                    <div className="semantic-card-title">
                      <span>{text(decision.action)}</span>
                      <strong>{text(decision.human_summary ?? decision.decision_id)}</strong>
                    </div>
                    <div className="dream-chip-row">
                      <span>{text(decision.proposal_id)}</span>
                      <span>{confidence(decision.confidence)}</span>
                      {decision.review_required ? <span>{t(language, 'dreamArtifacts.review')}</span> : null}
                    </div>
                    <p>{text(decision.reason, t(language, 'dreamArtifacts.noReasonRecorded'))}</p>
                    <div className="decision-targets">
                      <span><strong>{t(language, 'dreamArtifacts.target')}</strong>{text(decision.target_key, t(language, 'dreamArtifacts.new'))}</span>
                      <span><strong>{t(language, 'dreamArtifacts.candidates')}</strong>{list(decision.candidate_keys).map((key) => text(key)).join(', ') || '-'}</span>
                    </div>
                    {Object.keys(record(decision.write_patch)).length ? (
                      <details>
                        <summary>{t(language, 'dreamArtifacts.writePatch')}</summary>
                        <pre className="dream-pre compact">{compactJson(decision.write_patch)}</pre>
                      </details>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <p className="empty-copy">{t(language, 'dreamArtifacts.noReconciliation')}</p>
            )}
            </details>
          ) : null}

          {showDeterministic ? (
            <details className="dream-inspect-block" open={deterministicSectionOpen} ref={deterministicSectionRef}>
              <summary>{t(language, 'dreamArtifacts.deterministicBaseline')}</summary>
              <div className="dream-artifact-grid">
                <article className="dream-artifact-summary">
                  <strong>{deterministicEntities.length}</strong>
                  <span>{t(language, 'dreamArtifacts.deterministicEntities')}</span>
                </article>
                <article className="dream-artifact-summary">
                  <strong>{deterministicRelations.length}</strong>
                  <span>{t(language, 'dreamArtifacts.deterministicRelations')}</span>
                </article>
              </div>
              <div className="dream-semantic-grid">
                {deterministicEntities.map((item, index) => (
                  <article className="dream-semantic-card" key={`${text(item.key)}-${index}`}>
                    <div className="semantic-card-title">
                      <span>{text(item.type)}</span>
                      <strong>{text(item.name ?? item.key)}</strong>
                    </div>
                    <div className="dream-chip-row">
                      <span>{text(item.key)}</span>
                      <span>{text(item.memory_kind)}</span>
                    </div>
                    <p>{text(record(item.properties).summary ?? item.summary, t(language, 'dreamArtifacts.noSummaryRecorded'))}</p>
                  </article>
                ))}
                {deterministicRelations.map((item, index) => (
                  <article className="dream-semantic-card" key={`${text(item.type)}-${index}`}>
                    <div className="semantic-card-title">
                      <span>{text(item.type)}</span>
                      <strong>{text(record(item.from).key)} {'->'} {text(record(item.to).key)}</strong>
                    </div>
                    <div className="dream-chip-row">
                      <span>{text(item.memory_kind)}</span>
                    </div>
                    <p>{text(record(item.properties).summary ?? record(item.properties).semantic_type, t(language, 'dreamArtifacts.noSummaryRecorded'))}</p>
                  </article>
                ))}
              </div>
              {!deterministicEntities.length && !deterministicRelations.length ? (
                <p className="empty-copy">{t(language, 'dreamArtifacts.noDeterministicItems')}</p>
              ) : null}
            </details>
          ) : null}

          {showSemantic ? (
            <details className="dream-inspect-block" open={semanticSectionOpen} ref={semanticSectionRef}>
              <summary>{t(language, 'dreamArtifacts.persistence')}</summary>
            <div className="dream-artifact-grid">
              <article className="dream-artifact-summary">
                <strong>{persistedEntities.length}</strong>
                <span>{t(language, 'dreamArtifacts.persistedEntities')}</span>
              </article>
              <article className="dream-artifact-summary">
                <strong>{persistedRelations.length}</strong>
                <span>{t(language, 'dreamArtifacts.persistedRelations')}</span>
              </article>
            </div>
            <div className="dream-semantic-grid">
              {persistedEntities.map((item, index) => (
                <article className="dream-semantic-card" key={`${text(item.key)}-${index}`}>
                  <div className="semantic-card-title">
                    <span>{text(item.type)}</span>
                    <strong>{text(item.name ?? item.key)}</strong>
                  </div>
                  <div className="dream-chip-row">
                    <span>{text(item.key)}</span>
                    <span>{confidence(item.confidence)}</span>
                    <span>{text(item.memory_kind)}</span>
                  </div>
                  <p>{text(record(item.properties).summary)}</p>
                </article>
              ))}
              {persistedRelations.map((item, index) => (
                <article className="dream-semantic-card" key={`${text(item.type)}-${index}`}>
                  <div className="semantic-card-title">
                    <span>{text(item.type)}</span>
                    <strong>{text(record(item.from).key)} {'->'} {text(record(item.to).key)}</strong>
                  </div>
                  <div className="dream-chip-row">
                    <span>{confidence(item.confidence)}</span>
                    <span>{text(item.memory_kind)}</span>
                  </div>
                  <p>{text(record(item.properties).summary ?? record(item.properties).semantic_type)}</p>
                </article>
              ))}
            </div>
            <div className="dream-sync-grid">
              <details>
                <summary>{t(language, 'dreamArtifacts.sqliteWrites')}</summary>
                <pre className="dream-pre compact">{pretty(sqliteWrites)}</pre>
              </details>
              <details>
                <summary>{t(language, 'dreamArtifacts.neo4jSync')}</summary>
                <pre className="dream-pre compact">{pretty(neo4jSync)}</pre>
              </details>
              <details>
                <summary>{t(language, 'dreamArtifacts.finalGraphPatch')}</summary>
                <pre className="dream-pre compact">{pretty(finalPatch)}</pre>
              </details>
            </div>
            </details>
          ) : null}

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.outputPaths')}</summary>
            {outputPaths.length ? (
              <ul className="dream-path-list">{outputPaths.map((path, index) => <li key={index}>{text(path)}</li>)}</ul>
            ) : (
              <p className="empty-copy">{t(language, 'dreamArtifacts.noOutputPaths')}</p>
            )}
          </details>

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.auditAndStageFiles')}</summary>
            <div className="dream-file-list">
              {allFiles.length ? allFiles.map((file, index) => {
                const item = record(file);
                return (
                  <details className="dream-file" key={`${text(item.path)}-${index}`}>
                    <summary>
                      <strong>{text(item.title ?? item.kind ?? item.path)}</strong>
                      <span>{text(item.path)}</span>
                    </summary>
                    <div className="dream-file-meta">
                      <span>{text(item.kind)}</span>
                      <span>{text(item.llm_role)}</span>
                      <span>{text(record(item.metadata).char_count)} chars</span>
                    </div>
                    <pre className="dream-pre">{text(item.content, t(language, 'dreamArtifacts.noContent'))}</pre>
                  </details>
                );
              }) : <p className="empty-copy">{t(language, 'dreamArtifacts.noFiles')}</p>}
            </div>
          </details>

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.semanticGraph')}</summary>
            <div className="dream-artifact-grid">
              <article className="dream-artifact-summary">
                <strong>{entities.length}</strong>
                <span>{t(language, 'dreamArtifacts.semanticEntities')}</span>
              </article>
              <article className="dream-artifact-summary">
                <strong>{relations.length}</strong>
                <span>{t(language, 'dreamArtifacts.semanticRelations')}</span>
              </article>
            </div>
            <pre className="dream-pre small">{pretty(graph)}</pre>
          </details>

          <details className="dream-inspect-block">
            <summary>{t(language, 'dreamArtifacts.rawPayload')}</summary>
            <pre className="dream-pre">{pretty(selectedDream)}</pre>
          </details>
        </>
      ) : (
        <p className="empty-copy">{t(language, 'dreamArtifacts.empty')}</p>
      )}
    </section>
  );
}
