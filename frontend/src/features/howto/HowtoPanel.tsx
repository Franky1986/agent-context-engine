import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import './howto-panel.css';

type SectionId = 'overview' | 'sessions' | 'dreams' | 'statistics' | 'knowledge' | 'integrations' | 'personal' | 'control' | 'howto';

type HowtoPanelProps = {
  language: MonitorLanguage;
  onNavigate: (section: Exclude<SectionId, 'howto'>) => void;
};

const actionTargets: Array<{ key: string; target: Exclude<SectionId, 'howto'> }> = [
  { key: 'integrations', target: 'integrations' },
  { key: 'control', target: 'control' },
  { key: 'sessions', target: 'sessions' },
  { key: 'knowledge', target: 'knowledge' },
  { key: 'personal', target: 'personal' },
  { key: 'overview', target: 'overview' },
];

export function HowtoPanel({ language, onNavigate }: HowtoPanelProps) {
  return (
    <div className="howto-shell">
      <section className="howto-hero">
        <span className="howto-kicker">{t(language, 'howto.kicker')}</span>
        <div className="howto-title-row">
          <div>
            <h3>{t(language, 'howto.title')}</h3>
            <p>{t(language, 'howto.lead')}</p>
          </div>
          <div className="howto-pills">
            <span className="howto-pill">{t(language, 'howto.pill.local')}</span>
            <span className="howto-pill">{t(language, 'howto.pill.hooks')}</span>
            <span className="howto-pill">{t(language, 'howto.pill.firewall')}</span>
            <span className="howto-pill">{t(language, 'howto.pill.monitor')}</span>
          </div>
        </div>
        <p className="howto-warning">{t(language, 'howto.warning')}</p>
      </section>

      <section className="howto-diagram">
        <h3>{t(language, 'howto.diagram.title')}</h3>
        <p className="howto-diagram-copy">{t(language, 'howto.diagram.copy')}</p>
        <div className="howto-diagram-grid" aria-label={t(language, 'howto.diagram.title')}>
          <div className="howto-diagram-node" data-tone="user">
            <strong>{t(language, 'howto.diagram.user.title')}</strong>
            <span>{t(language, 'howto.diagram.user.copy')}</span>
          </div>
          <div className="howto-diagram-arrow" aria-hidden="true">→</div>
          <div className="howto-diagram-node" data-tone="runner">
            <strong>{t(language, 'howto.diagram.runner.title')}</strong>
            <span>{t(language, 'howto.diagram.runner.copy')}</span>
          </div>
          <div className="howto-diagram-arrow" aria-hidden="true">→</div>
          <div className="howto-diagram-node" data-tone="hook">
            <strong>{t(language, 'howto.diagram.hook.title')}</strong>
            <span>{t(language, 'howto.diagram.hook.copy')}</span>
          </div>
          <div className="howto-diagram-arrow" aria-hidden="true">→</div>
          <div className="howto-diagram-node" data-tone="memory">
            <strong>{t(language, 'howto.diagram.memory.title')}</strong>
            <span>{t(language, 'howto.diagram.memory.copy')}</span>
          </div>
          <div className="howto-diagram-arrow" aria-hidden="true">→</div>
          <div className="howto-diagram-node" data-tone="dream">
            <strong>{t(language, 'howto.diagram.dream.title')}</strong>
            <span>{t(language, 'howto.diagram.dream.copy')}</span>
          </div>
          <div className="howto-diagram-arrow" aria-hidden="true">→</div>
          <div className="howto-diagram-node" data-tone="monitor">
            <strong>{t(language, 'howto.diagram.monitor.title')}</strong>
            <span>{t(language, 'howto.diagram.monitor.copy')}</span>
          </div>
        </div>
      </section>

      <section className="howto-section">
        <h3>{t(language, 'howto.sections.title')}</h3>
        <div className="howto-section-grid">
          <article className="howto-card">
            <h4>{t(language, 'howto.section.hooks.title')}</h4>
            <p>{t(language, 'howto.section.hooks.copy')}</p>
          </article>
          <article className="howto-card">
            <h4>{t(language, 'howto.section.runners.title')}</h4>
            <p>{t(language, 'howto.section.runners.copy')}</p>
          </article>
          <article className="howto-card">
            <h4>{t(language, 'howto.section.firewall.title')}</h4>
            <p>{t(language, 'howto.section.firewall.copy')}</p>
          </article>
          <article className="howto-card">
            <h4>{t(language, 'howto.section.monitor.title')}</h4>
            <p>{t(language, 'howto.section.monitor.copy')}</p>
          </article>
          <article className="howto-card">
            <h4>{t(language, 'howto.section.workflows.title')}</h4>
            <p>{t(language, 'howto.section.workflows.copy')}</p>
          </article>
          <article className="howto-card">
            <h4>{t(language, 'howto.section.troubleshooting.title')}</h4>
            <p>{t(language, 'howto.section.troubleshooting.copy')}</p>
          </article>
        </div>
      </section>

      <section className="howto-actions">
        <h3>{t(language, 'howto.actions.title')}</h3>
        <p className="howto-action-copy">{t(language, 'howto.actions.copy')}</p>
        <div className="howto-action-links">
          {actionTargets.map((item) => (
            <button key={item.key} className="howto-link-button" type="button" onClick={() => onNavigate(item.target)}>
              {t(language, `howto.actions.${item.key}`)}
            </button>
          ))}
        </div>
        <ul className="howto-list">
          <li>{t(language, 'howto.list.sessions')}</li>
          <li>{t(language, 'howto.list.dreams')}</li>
          <li>{t(language, 'howto.list.knowledge')}</li>
          <li>{t(language, 'howto.list.integrations')}</li>
          <li>{t(language, 'howto.list.control')}</li>
        </ul>
        <p className="howto-note">{t(language, 'howto.note')}</p>
      </section>
    </div>
  );
}
