import { useEffect, useMemo, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import {
  firewallDisabledUntilLabel,
  firewallReasonLabel,
  firewallScopeLabel,
  firewallStateHint,
  firewallStateLabel,
} from '../../app/i18n/monitorFormatters';
import {
  getFirewallRules,
  getFirewallState,
  getFirewallSuggestions,
  getRisks,
  setFirewallState,
} from '../../shared/api/monitor';
import type {
  FirewallState,
  RiskEventListItem,
  RiskListResponse,
} from '../../shared/api/types';
import './firewall-panel.css';

const FIREWALL_POLL_MS = 5000;

export type FirewallPanelProps = {
  initialData?: FirewallState;
  mode?: 'overview' | 'full' | 'rules';
  language?: MonitorLanguage;
  onStateChange?: (state: FirewallState | undefined) => void;
};

type RecordLike = Record<string, unknown>;

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function asRecord(value: unknown): RecordLike {
  return value && typeof value === 'object' ? (value as RecordLike) : {};
}

function asRecordArray(value: unknown): RecordLike[] {
  return Array.isArray(value) ? value.filter((item): item is RecordLike => Boolean(item) && typeof item === 'object') : [];
}

function parseJsonList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value !== 'string' || !value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map((item) => String(item)).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function riskRows(payload?: RiskListResponse): RiskEventListItem[] {
  return payload?.risks ?? payload?.events ?? [];
}

function isPermanentOverride(override: RecordLike) {
  return override.permanent === true || text(override.expires_at, '') === '9999-12-31T23:59:59+00:00';
}

function overrideFacts(
  language: MonitorLanguage,
  override: RecordLike,
): Array<{ label: string; value: string }> {
  const facts: Array<{ label: string; value: string }> = [];
  const add = (labelKey: string, value: unknown) => {
    const rendered = text(value, '');
    if (rendered) {
      facts.push({ label: t(language, labelKey), value: rendered });
    }
  };
  add('firewall.overrideFact.session', override.session_id);
  add('firewall.overrideFact.runner', override.client_type);
  add('firewall.overrideFact.agentName', override.agent_name);
  add('firewall.overrideFact.thread', override.thread_name);
  add('firewall.overrideFact.project', override.project_id);
  add('firewall.overrideFact.folder', override.workdir);
  add('firewall.overrideFact.source', override.source);
  add('firewall.overrideFact.actor', override.created_by);
  add('firewall.overrideFact.createdAt', override.created_at);
  return facts;
}

export function FirewallPanel({
  initialData,
  mode = 'full',
  language = 'en',
  onStateChange,
}: FirewallPanelProps) {
  const [data, setData] = useState<FirewallState | undefined>(initialData);
  const [riskData, setRiskData] = useState<RiskListResponse | undefined>();
  const [error, setError] = useState('');
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    setData(initialData);
  }, [initialData]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (mode === 'rules') {
        const [state, rulesPayload, suggestionsPayload, risksPayload] = await Promise.all([
          getFirewallState(),
          getFirewallRules({ limit: 200 }),
          getFirewallSuggestions(20),
          getRisks(80),
        ]);
        if (cancelled) return;
        const nextState = {
          ...state,
          rules: rulesPayload.rules ?? state.rules,
          suggestions: suggestionsPayload.suggestions ?? state.suggestions,
        };
        setData(nextState);
        onStateChange?.(nextState);
        setRiskData(risksPayload);
        return;
      }

      const [state, risksPayload] = await Promise.all([getFirewallState(), getRisks(80)]);
      if (cancelled) return;
      setData(state);
      onStateChange?.(state);
      setRiskData(risksPayload);
      setError('');
    };

    load().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });
    const timer = window.setInterval(() => {
      load().catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    }, FIREWALL_POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [mode, onStateChange]);

  const overrides = asRecordArray(data?.overrides);
  const overrideAudit = asRecordArray(data?.override_audit);
  const deterministicRules = asRecordArray(data?.deterministic_rules);
  const fixedRules = asRecordArray(data?.effective_fixed_rules);
  const llmRules = asRecordArray(data?.llm_rules);
  const suggestions = asRecordArray(data?.suggestions);
  const approvals = useMemo(
    () => riskRows(riskData).filter((risk) => text(risk.approval_state, '') !== ''),
    [riskData],
  );
  const requiredApprovals = approvals.filter((risk) => text(risk.approval_state, '') === 'required');

  const showControls = mode !== 'rules';
  const showRules = mode !== 'overview';
  const showApprovals = mode !== 'rules';
  const pendingCount = requiredApprovals.length;
  const activeOverrideCount = overrides.length;
  const totalRuleCount = fixedRules.length + deterministicRules.length + llmRules.length;
  const warningsCount = suggestions.length;
  const enabled = data?.enabled !== false;

  async function activateFirewall() {
    setActionBusy(true);
    try {
      const nextState = await setFirewallState({
        enabled: true,
        actor: 'monitor-ui',
        reason: 'enabled from monitor',
      });
      setData(nextState);
      onStateChange?.(nextState);
      setError('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <section className="firewall-panel" data-firewall-enabled={enabled ? 'true' : 'false'} data-mode={mode}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t(language, 'firewall.heading.control')}</p>
          <h2>{firewallStateLabel(language, data)}</h2>
          <p className="firewall-state-copy">{firewallStateHint(language, data)}</p>
        </div>
        <span>
          {activeOverrideCount} {t(language, 'firewall.kpi.activeOverrides')} · {pendingCount}{' '}
          {t(language, 'firewall.kpi.pendingApprovals')}
        </span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}

      <div className="firewall-kpi-grid">
        <article className="firewall-kpi-card">
          <small>{t(language, 'firewall.kpi.pendingApprovals')}</small>
          <strong>{pendingCount}</strong>
          <span>{t(language, 'firewall.kpi.pendingApprovalsHint')}</span>
        </article>
        <article className="firewall-kpi-card">
          <small>{t(language, 'firewall.kpi.activeOverrides')}</small>
          <strong>{activeOverrideCount}</strong>
          <span>{t(language, 'firewall.kpi.activeOverridesHint')}</span>
        </article>
        <article className="firewall-kpi-card">
          <small>{t(language, 'firewall.kpi.visibleRules')}</small>
          <strong>{totalRuleCount}</strong>
          <span>{t(language, 'firewall.kpi.visibleRulesHint')}</span>
        </article>
        <article className="firewall-kpi-card">
          <small>{t(language, 'firewall.kpi.signals')}</small>
          <strong>{warningsCount}</strong>
          <span>{t(language, 'firewall.kpi.signalsHint')}</span>
        </article>
      </div>

      <div className="firewall-facts">
        <div>
          <dt>{t(language, 'firewall.meta.state')}</dt>
          <dd>{firewallStateLabel(language, data)}</dd>
        </div>
        <div>
          <dt>{t(language, 'firewall.meta.pausedUntil')}</dt>
          <dd>{firewallDisabledUntilLabel(language, data)}</dd>
        </div>
        <div>
          <dt>{t(language, 'firewall.meta.currentReason')}</dt>
          <dd>{firewallReasonLabel(language, data?.reason)}</dd>
        </div>
        <div>
          <dt>{t(language, 'firewall.meta.lastChangedBy')}</dt>
          <dd>{text(data?.updated_by, t(language, 'common.noneReported'))}</dd>
        </div>
      </div>

      {showControls ? (
        <details className="firewall-block" open>
          <summary>{t(language, 'firewall.section.directControls')}</summary>
          {!enabled ? (
            <div className="firewall-actions">
              <button
                type="button"
                data-variant="safe"
                disabled={actionBusy}
                onClick={() => {
                  void activateFirewall();
                }}>
                {actionBusy ? t(language, 'firewall.action.enabling') : t(language, 'firewall.action.enable')}
              </button>
            </div>
          ) : null}
          <p className="firewall-state-copy">{t(language, 'firewall.directControls.copy')}</p>
          <div className="firewall-inline-list">
            <code>firewall disable session</code>
            <code>firewall disable session 30m</code>
            <code>firewall enable session</code>
          </div>
          <div className="firewall-list">
            {overrides.length ? overrides.map((override, index) => {
              const facts = overrideFacts(language, override);
              return (
                <article
                  className="firewall-row firewall-row-override-active"
                  key={`${text(override.override_id)}-${index}`}>
                  <div className="firewall-row-head">
                    <strong>{firewallScopeLabel(language, override.scope_type)}</strong>
                    <small>
                      {isPermanentOverride(override)
                        ? t(language, 'firewall.endsIndefinite')
                        : `${t(language, 'firewall.ends')} ${text(override.expires_at)}`}
                    </small>
                  </div>
                  <span className="firewall-override-summary">{t(language, 'firewall.overrideSummary')}</span>
                  <span>{text(override.reason, t(language, 'firewall.noReason'))}</span>
                  {facts.length ? (
                    <dl className="firewall-row-facts">
                      {facts.map((fact) => (
                        <div key={`${text(override.override_id)}-${fact.label}`}>
                          <dt>{fact.label}</dt>
                          <dd>{fact.value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                  <small>{text(override.override_id)}</small>
                </article>
              );
            }) : <p className="empty-copy">{t(language, 'firewall.noActiveOverrides')}</p>}
          </div>
        </details>
      ) : null}

      {showApprovals ? (
        <details className="firewall-block" open>
          <summary>{t(language, 'firewall.section.needsAttention')}</summary>
          <div className="firewall-subgrid">
            <article className="firewall-card">
              <strong>{t(language, 'firewall.section.openApprovals')}</strong>
              <div className="firewall-list">
                {requiredApprovals.length ? requiredApprovals.slice(0, 12).map((risk) => (
                  <article className="firewall-row" key={text(risk.risk_event_id)}>
                    <div className="firewall-row-head">
                      <strong>{text(risk.tool_name, text(risk.source_kind, t(language, 'firewall.tool')))}</strong>
                      <small>{text(risk.created_at)}</small>
                    </div>
                    <span>{text(risk.reason ?? risk.preview, t(language, 'firewall.noReasonStored'))}</span>
                    <small>{text(risk.approval_state)} · Session {text(risk.session_id)}</small>
                  </article>
                )) : <p className="empty-copy">{t(language, 'firewall.noOpenApprovals')}</p>}
              </div>
            </article>
            <article className="firewall-card">
              <strong>{t(language, 'firewall.section.approvalHistory')}</strong>
              <div className="firewall-list">
                {approvals.length ? approvals.slice(0, 12).map((risk) => (
                  <article className="firewall-row" key={`${text(risk.risk_event_id)}-${text(risk.approval_state)}`}>
                    <div className="firewall-row-head">
                      <strong>{text(risk.approval_state, t(language, 'common.unknown'))}</strong>
                      <small>{text(risk.created_at)}</small>
                    </div>
                    <span>{text(risk.reason ?? risk.preview, t(language, 'firewall.noReasonStored'))}</span>
                    <small>{text(risk.tool_name)} · {text(risk.client_type)} · {text(risk.session_id)}</small>
                  </article>
                )) : <p className="empty-copy">{t(language, 'firewall.noApprovalEvents')}</p>}
              </div>
            </article>
          </div>
        </details>
      ) : null}

      {showRules ? (
        <details className="firewall-block">
          <summary>{t(language, 'firewall.section.rulesAndSignals')}</summary>
          <div className="firewall-subgrid">
            <article className="firewall-card">
              <strong>{t(language, 'firewall.section.fixedRules')}</strong>
              <div className="firewall-list">
                {fixedRules.length ? fixedRules.slice(0, 12).map((rule, index) => (
                  <article className="firewall-row" key={`${text(rule.rule_id)}-${index}`}>
                    <div className="firewall-row-head">
                      <strong>{text(rule.name, text(rule.rule_id))}</strong>
                      <small>{text(rule.rule_effect_label, text(rule.rule_effect))}</small>
                    </div>
                    <span>{text(rule.description, t(language, 'firewall.noDescription'))}</span>
                    <small>{text(rule.origin_label)} · {text(rule.scope_type)} · {text(rule.status)}</small>
                    {parseJsonList(rule.command_patterns_json).length ? (
                      <div className="firewall-inline-list">
                        {parseJsonList(rule.command_patterns_json).slice(0, 3).map((pattern) => <code key={pattern}>{pattern}</code>)}
                      </div>
                    ) : null}
                  </article>
                )) : <p className="empty-copy">{t(language, 'firewall.noFixedRules')}</p>}
              </div>
            </article>
            <article className="firewall-card">
              <strong>{t(language, 'firewall.section.dynamicRules')}</strong>
              <div className="firewall-list">
                {[...deterministicRules, ...llmRules].length ? [...deterministicRules, ...llmRules].slice(0, 16).map((rule, index) => (
                  <article className="firewall-row" key={`${text(rule.rule_id)}-${index}`}>
                    <div className="firewall-row-head">
                      <strong>{text(rule.name, text(rule.rule_id))}</strong>
                      <small>{text(rule.rule_kind)} · {text(rule.status)}</small>
                    </div>
                    <span>{text(rule.description, t(language, 'firewall.noDescription'))}</span>
                    <small>
                      {text(rule.origin_label)} · {t(language, 'firewall.ends')} {text(rule.expires_at, t(language, 'firewall.never'))}
                    </small>
                  </article>
                )) : <p className="empty-copy">{t(language, 'firewall.noDynamicRules')}</p>}
              </div>
            </article>
          </div>
          <article className="firewall-card firewall-card-wide">
            <strong>{t(language, 'firewall.section.signalsAndSuggestions')}</strong>
            <div className="firewall-list">
              {suggestions.length ? suggestions.slice(0, 12).map((item, index) => {
                const payload = asRecord(item);
                const rationale = text(payload.rationale, text(payload.reason, t(language, 'firewall.noRationale')));
                return (
                  <article className="firewall-row" key={`${text(payload.suggestion_id)}-${index}`}>
                    <div className="firewall-row-head">
                      <strong>{text(payload.status, t(language, 'firewall.suggestion'))}</strong>
                      <small>{text(payload.created_at)}</small>
                    </div>
                    <span>{rationale}</span>
                    <small>{text(payload.suggestion_id)}</small>
                  </article>
                );
              }) : <p className="empty-copy">{t(language, 'firewall.noSignals')}</p>}
            </div>
          </article>
        </details>
      ) : null}

      {showControls ? (
        <details className="firewall-block">
          <summary>{t(language, 'firewall.section.overrideHistory')}</summary>
          <div className="firewall-list">
            {overrideAudit.length ? overrideAudit.slice(0, 20).map((entry, index) => (
              <article className="firewall-row" key={`${text(entry.audit_id)}-${index}`}>
                <div className="firewall-row-head">
                  <strong>{text(entry.action, t(language, 'firewall.audit'))}</strong>
                  <small>{text(entry.created_at)}</small>
                </div>
                <span>{text(entry.reason, t(language, 'firewall.noReasonStored'))}</span>
                <small>{text(entry.actor)} · {text(entry.override_id)}</small>
              </article>
            )) : <p className="empty-copy">{t(language, 'firewall.noOverrideHistory')}</p>}
          </div>
        </details>
      ) : null}
    </section>
  );
}
