import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getRiskDetail, getRisks } from '../../shared/api/monitor';
import type { RiskDetail } from '../../shared/api/types';
import './risk-detail-panel.css';

const RISK_DETAIL_POLL_MS = 5000;

export type RiskDetailPanelProps = {
  riskId?: string;
  initialData?: RiskDetail;
  language?: MonitorLanguage;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function hasText(value: unknown) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

export function RiskDetailPanel({ riskId, initialData, language = 'en' }: RiskDetailPanelProps) {
  const [data, setData] = useState<RiskDetail | undefined>(initialData);
  const [error, setError] = useState('');

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    const load = async () => {
      const risks = await getRisks(1);
      const first = risks.risks?.[0] ?? risks.events?.[0];
      const id = riskId || first?.risk_event_id || String(first?.id ?? '');
      if (!id) return undefined;
      return getRiskDetail(id);
    };
    load()
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError('');
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    const timer = window.setInterval(() => {
      load()
        .then((payload) => {
          if (!cancelled) {
            setData(payload);
            setError('');
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        });
    }, RISK_DETAIL_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [initialData, riskId]);

  const risk = data?.risk_event;
  const evidence = Array.isArray(data?.evidence) ? data.evidence : [];
  const overrides = Array.isArray(data?.overrides) ? data.overrides : [];
  const classifier = asRecord(data?.classifier);
  const classifierRun = asRecord(classifier?.run);
  const classifierResult = asRecord(classifier?.result);
  const categories = asList(risk?.categories);
  const poisoningFlags = asList(risk?.poisoning_flags);
  const taintContext = asList(risk?.taint_context);

  return (
    <section className="risk-detail-panel">
      <div className="panel-heading">
        <p className="eyebrow">{t(language, 'risk.detail.eyebrow')}</p>
        <h2>{text(risk?.status, t(language, 'risk.detail.latest'))}</h2>
        <span>
          {evidence.length} {t(language, 'risk.detail.evidence')} · {overrides.length} {t(language, 'risk.detail.overrides')}
        </span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}
      <div className="risk-detail-body">
        <div className="risk-detail-headline">
          <strong>{text(risk?.risk_level, t(language, 'risk.status.unknown'))}</strong>
          <span>{text(risk?.decision)} · {text(risk?.source_kind)} · {text(risk?.tool_name)}</span>
        </div>
        <p>{text(risk?.reason ?? risk?.preview, t(language, 'risk.reason.none'))}</p>
        {hasText(risk?.impact) ? <p className="risk-detail-impact">{text(risk?.impact)}</p> : null}
        <small>{text(risk?.created_at)} · {text(risk?.command_ref)}</small>

        <div className="risk-detail-grid">
          <div className="risk-detail-card">
            <span className="risk-detail-label">{t(language, 'risk.detail.categories')}</span>
            <div className="risk-detail-chips">
              {categories.length ? categories.map((item, index) => <code key={`${String(item)}-${index}`}>{String(item)}</code>) : <span>{t(language, 'risk.detail.none')}</span>}
            </div>
          </div>
          <div className="risk-detail-card">
            <span className="risk-detail-label">{t(language, 'risk.detail.flags')}</span>
            <div className="risk-detail-chips">
              {poisoningFlags.length ? poisoningFlags.map((item, index) => <code key={`${String(item)}-${index}`}>{String(item)}</code>) : <span>{t(language, 'risk.detail.none')}</span>}
            </div>
          </div>
        </div>

        {hasText(risk?.approval_line) ? (
          <div className="risk-detail-card risk-detail-card-accent">
            <span className="risk-detail-label">{t(language, 'risk.detail.approval')}</span>
            <pre>{text(risk?.approval_line)}</pre>
          </div>
        ) : null}

        {taintContext.length ? (
          <div className="risk-detail-card">
            <span className="risk-detail-label">{t(language, 'risk.detail.taintSources')}</span>
            <div className="risk-detail-stack">
              {taintContext.map((item, index) => {
                const source = asRecord(item);
                return (
                  <div className="risk-detail-stack-row" key={text(source?.risk_event_id, `taint-${index}`)}>
                    <strong>{text(source?.risk_event_id, 'risk')} · {text(source?.status)} · {text(source?.risk_level)}</strong>
                    <span>{text(source?.reason, t(language, 'risk.reason.none'))}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {classifierRun || classifierResult ? (
          <div className="risk-detail-card">
            <span className="risk-detail-label">{t(language, 'risk.detail.classifier')}</span>
            <div className="risk-detail-stack">
              <div className="risk-detail-stack-row">
                <strong>{text(classifierRun?.runner)} · {text(classifierRun?.status)}</strong>
                <span>{text(classifierRun?.error ?? classifierResult?.reason, t(language, 'risk.reason.none'))}</span>
              </div>
              <div className="risk-detail-inline">
                <span>{text(classifierRun?.model)}</span>
                <span>{text(classifierRun?.duration_ms)} ms</span>
                <span>{text(classifierRun?.total_tokens)} tokens</span>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
