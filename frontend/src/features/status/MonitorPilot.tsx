import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import { getFirewallState, getMonitorStatus } from '../../shared/api/monitor';
import type { FirewallState, MonitorStatus } from '../../shared/api/types';
import type { MonitorLanguage } from '../../app/monitorUi';
import './monitor-pilot.css';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

export type MonitorPilotProps = {
  initialStatus?: MonitorStatus;
  initialFirewall?: FirewallState;
  language?: MonitorLanguage;
};

function valueText(value: unknown, fallback = '-') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

export function MonitorPilot({ initialStatus, initialFirewall, language = 'en' }: MonitorPilotProps) {
  const [state, setState] = useState<LoadState>(initialStatus ? 'ready' : 'idle');
  const [status, setStatus] = useState<MonitorStatus | undefined>(initialStatus);
  const [firewall, setFirewall] = useState<FirewallState | undefined>(initialFirewall ?? initialStatus?.firewall);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (initialStatus || initialFirewall) return;
    let cancelled = false;
    setState('loading');
    Promise.all([getMonitorStatus(), getFirewallState()])
      .then(([statusPayload, firewallPayload]) => {
        if (cancelled) return;
        setStatus(statusPayload);
        setFirewall(firewallPayload);
        setState('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [initialStatus, initialFirewall]);

  const effectiveFirewall = firewall ?? status?.firewall;
  const firewallKnown = Boolean(effectiveFirewall);
  const firewallEnabled = effectiveFirewall?.enabled === true;
  const overrides = effectiveFirewall?.overrides ?? [];

  return (
    <section className="monitor-shell" aria-busy={state === 'loading'}>
      <div className="hero-card">
        <p className="eyebrow">{t(language, 'pilot.runtime')}</p>
        <h1>{valueText(status?.root, 'Agent Context Engine')}</h1>
        <p className="hero-copy">
          {t(language, 'pilot.monitor')} v{valueText(status?.monitor_version)} · {t(language, 'pilot.runner')} {valueText(status?.runner)}
        </p>
      </div>

      {state === 'error' ? <div className="error-card">{t(language, 'pilot.apiError')}: {error}</div> : null}

      <div className="metric-grid">
        <article className="metric-card">
          <span>{t(language, 'app.section.sessions')}</span>
          <strong>{valueText(status?.sessions)}</strong>
        </article>
        <article className="metric-card">
          <span>{t(language, 'sessionDetail.events')}</span>
          <strong>{valueText(status?.events)}</strong>
        </article>
        <article className="metric-card">
          <span>{t(language, 'pilot.pendingDreams')}</span>
          <strong>{valueText(status?.pending_dreams)}</strong>
        </article>
        <article className="metric-card firewall-card" data-enabled={firewallKnown ? String(firewallEnabled) : 'unknown'}>
          <span>{t(language, 'pilot.firewall')}</span>
          <strong>
            {!firewallKnown
              ? t(language, state === 'loading' ? 'common.loading' : 'pilot.firewallUnknown')
              : firewallEnabled
                ? t(language, 'pilot.firewallEnabled')
                : t(language, 'pilot.firewallDisabled')}
          </strong>
        </article>
      </div>

      <section className="panel-card">
        <div>
          <p className="eyebrow">{t(language, 'pilot.scopedOverrides')}</p>
          <h2>
            {overrides.length} {t(language, overrides.length === 1 ? 'pilot.activeOverrideSingular' : 'pilot.activeOverridePlural')}
          </h2>
        </div>
        <div className="override-list">
          {overrides.length ? (
            overrides.slice(0, 5).map((override, index) => (
              <article className="override-row" key={override.override_id ?? index}>
                <strong>{valueText(override.scope_type, 'scope')}</strong>
                <span>{valueText(override.reason, t(language, 'pilot.noReason'))}</span>
                <small>{t(language, 'pilot.expires')} {valueText(override.expires_at)}</small>
              </article>
            ))
          ) : (
            <p className="empty-copy">{t(language, 'pilot.noOverrides')}</p>
          )}
        </div>
      </section>
    </section>
  );
}
