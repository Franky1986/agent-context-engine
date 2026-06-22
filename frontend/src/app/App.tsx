import { useEffect, useState } from 'react';
import { DiagnosticsPanel } from '../features/diagnostics/DiagnosticsPanel';
import { DreamArtifactsPanel, type DreamArtifactsPanelProps } from '../features/dreams/DreamArtifactsPanel';
import { DreamsPanel } from '../features/dreams/DreamsPanel';
import { FirewallPanel } from '../features/firewall/FirewallPanel';
import { GraphInspectPanel, type GraphInspectTarget } from '../features/graph/GraphInspectPanel';
import { GraphPanel } from '../features/graph/GraphPanel';
import { GraphQueryPanel } from '../features/graph/GraphQueryPanel';
import { IntegrationsPanel } from '../features/integrations/IntegrationsPanel';
import { HowtoPanel } from '../features/howto/HowtoPanel';
import { KnowledgeFocusPanel } from '../features/graph/KnowledgeFocusPanel';
import { OverviewPanel } from '../features/overview/OverviewPanel';
import { PersonalPanel } from '../features/personal/PersonalPanel';
import { SessionDetailPanel } from '../features/sessions/SessionDetailPanel';
import { SessionsPanel } from '../features/sessions/SessionsPanel';
import { StatisticsPanel } from '../features/statistics/StatisticsPanel';
import { StoragePanel } from '../features/storage/StoragePanel';
import { MonitorPilot } from '../features/status/MonitorPilot';
import { t } from './i18n';
import { type MemoryView, type MonitorLanguage, viewLabel } from './monitorUi';
import { getFirewallState, getMonitorStatus } from '../shared/api/monitor';
import type { DreamRun, FirewallState, MonitorStatus } from '../shared/api/types';
import '../shared/styles/global.css';

const sections = ['overview', 'sessions', 'dreams', 'statistics', 'knowledge', 'integrations', 'personal', 'control', 'howto'] as const;

const sectionAliases: Record<string, (typeof sections)[number]> = {
  memory: 'overview',
  api: 'overview',
  retrieval: 'sessions',
  personal: 'personal',
  integrations: 'integrations',
  graph: 'knowledge',
  'graph-tables': 'knowledge',
  inspect: 'knowledge',
  stats: 'statistics',
  firewall: 'control',
  'firewall-rules': 'control',
  reports: 'control',
  help: 'howto',
  guide: 'howto',
  start: 'howto',
  howto: 'howto',
};

function normalizedSection(hash: string): (typeof sections)[number] {
  const value = hash.replace('#', '');
  if (!value) {
    return 'overview';
  }
  if (sections.some((id) => id === value)) {
    return value as (typeof sections)[number];
  }
  return sectionAliases[value] ?? 'sessions';
}

function normalizedLanguage(value: string | null | undefined): MonitorLanguage {
  return value === 'de' ? 'de' : 'en';
}

function normalizedMemoryView(value: string | null | undefined): MemoryView {
  return value === 'deterministic' || value === 'semantic' || value === 'both' ? value : 'both';
}

function parseGraphTarget(url: URL): GraphInspectTarget | undefined {
  const kind = url.searchParams.get('inspect_kind');
  const id = url.searchParams.get('inspect_id');
  if ((kind === 'entity' || kind === 'relation') && id) {
    return {
      kind,
      id,
      label: url.searchParams.get('inspect_label') || undefined,
    };
  }
  return undefined;
}

function parseDreamFocus(url: URL): DreamArtifactsPanelProps['focus'] | undefined {
  const value = url.searchParams.get('dream_focus');
  return value === 'deterministic_entities'
    || value === 'deterministic_relations'
    || value === 'semantic_entities'
    || value === 'semantic_relations'
    ? value
    : undefined;
}

export function App() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>();
  const [selectedDreamId, setSelectedDreamId] = useState<string | undefined>();
  const [selectedDream, setSelectedDream] = useState<DreamRun | undefined>();
  const [selectedDreamFocus, setSelectedDreamFocus] = useState<DreamArtifactsPanelProps['focus'] | undefined>();
  const [dreamsSessionFilter, setDreamsSessionFilter] = useState<string | undefined>();
  const [selectedGraphTarget, setSelectedGraphTarget] = useState<GraphInspectTarget | undefined>();
  const [knowledgeFocusQuery, setKnowledgeFocusQuery] = useState<string | undefined>();
  const [sessionsQuery, setSessionsQuery] = useState<string | undefined>();
  const [activeSection, setActiveSection] = useState<(typeof sections)[number]>('overview');
  const [language, setLanguage] = useState<MonitorLanguage>(window.MONITOR_LANGUAGE === 'de' ? 'de' : 'en');
  const [memoryView, setMemoryView] = useState<MemoryView>('both');
  const [firewallState, setFirewallState] = useState<FirewallState | undefined>();
  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus | undefined>();

  function asLabel(value: unknown): string | undefined {
    if (value === null || value === undefined || value === '') return undefined;
    return String(value);
  }

  function text(value: unknown, fallback = '-') {
    return value === null || value === undefined || value === '' ? fallback : String(value);
  }

  useEffect(() => {
    const syncUrlState = () => {
      const url = new URL(window.location.href);
      setActiveSection(normalizedSection(url.hash));
      setLanguage(normalizedLanguage(url.searchParams.get('lang') ?? window.MONITOR_LANGUAGE));
      setMemoryView(normalizedMemoryView(url.searchParams.get('view')));
      setSelectedSessionId(url.searchParams.get('session') || undefined);
      setSelectedDreamId(url.searchParams.get('dream') || undefined);
      setSelectedDreamFocus(parseDreamFocus(url));
      setDreamsSessionFilter(url.searchParams.get('dream_session') || undefined);
      setKnowledgeFocusQuery(url.searchParams.get('knowledge_focus') || undefined);
      setSelectedGraphTarget(parseGraphTarget(url));
      setSelectedDream(undefined);
    };
    syncUrlState();
    window.addEventListener('hashchange', syncUrlState);
    window.addEventListener('popstate', syncUrlState);
    return () => {
      window.removeEventListener('hashchange', syncUrlState);
      window.removeEventListener('popstate', syncUrlState);
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    let cancelled = false;

    const loadFirewallState = async () => {
      try {
        const state = await getFirewallState();
        if (!cancelled) {
          setFirewallState(state);
        }
      } catch {
        if (!cancelled) {
          setFirewallState(undefined);
        }
      }
    };

    void loadFirewallState();
    const timer = window.setInterval(() => {
      void loadFirewallState();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadMonitorStatus = async () => {
      try {
        const status = await getMonitorStatus();
        if (!cancelled) {
          setMonitorStatus(status);
        }
      } catch {
        if (!cancelled) {
          setMonitorStatus(undefined);
        }
      }
    };

    void loadMonitorStatus();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.hash = activeSection === 'overview' ? '' : `#${activeSection}`;
    url.searchParams.set('lang', language);
    url.searchParams.set('view', memoryView);
    if (selectedSessionId) url.searchParams.set('session', selectedSessionId);
    else url.searchParams.delete('session');
    if (selectedDreamId) url.searchParams.set('dream', selectedDreamId);
    else url.searchParams.delete('dream');
    if (selectedDreamFocus) url.searchParams.set('dream_focus', selectedDreamFocus);
    else url.searchParams.delete('dream_focus');
    if (dreamsSessionFilter) url.searchParams.set('dream_session', dreamsSessionFilter);
    else url.searchParams.delete('dream_session');
    if (knowledgeFocusQuery) url.searchParams.set('knowledge_focus', knowledgeFocusQuery);
    else url.searchParams.delete('knowledge_focus');
    if (selectedGraphTarget?.id) {
      url.searchParams.set('inspect_kind', selectedGraphTarget.kind);
      url.searchParams.set('inspect_id', selectedGraphTarget.id);
      if (selectedGraphTarget.label) url.searchParams.set('inspect_label', selectedGraphTarget.label);
      else url.searchParams.delete('inspect_label');
    } else {
      url.searchParams.delete('inspect_kind');
      url.searchParams.delete('inspect_id');
      url.searchParams.delete('inspect_label');
    }
    const next = `${url.pathname}${url.search}${url.hash}`;
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next !== current) {
      window.history.replaceState(null, '', next);
    }
  }, [activeSection, language, memoryView, selectedSessionId, selectedDreamId, selectedDreamFocus, dreamsSessionFilter, knowledgeFocusQuery, selectedGraphTarget]);

  const showSection = (id: (typeof sections)[number]) => {
    if (id === 'overview') {
      setSelectedSessionId(undefined);
      setSelectedDreamId(undefined);
      setSelectedDream(undefined);
      setSelectedDreamFocus(undefined);
      setDreamsSessionFilter(undefined);
      setSelectedGraphTarget(undefined);
      setKnowledgeFocusQuery(undefined);
      const url = new URL(window.location.href);
      url.hash = '';
      url.searchParams.delete('session');
      url.searchParams.delete('dream');
      url.searchParams.delete('dream_session');
      url.searchParams.delete('knowledge_focus');
      url.searchParams.delete('inspect_kind');
      url.searchParams.delete('inspect_id');
      url.searchParams.delete('inspect_label');
    }
    setActiveSection(id);
  };

  const setLanguageAndUrl = (nextLanguage: MonitorLanguage) => {
    setLanguage(nextLanguage);
  };

  const openSession = (sessionId: string, nextSection: (typeof sections)[number] = 'sessions') => {
    setSelectedSessionId(sessionId);
    if (nextSection !== 'dreams') {
      setSelectedDreamFocus(undefined);
    }
    showSection(nextSection);
  };

  const openDream = (
    dream: DreamRun,
    nextSection: (typeof sections)[number] = 'dreams',
    focus?: DreamArtifactsPanelProps['focus'],
  ) => {
    const nextDreamId = dream.dream_run_id ?? dream.run_id ?? undefined;
    setSelectedDream(dream);
    setSelectedDreamId(nextDreamId);
    setSelectedDreamFocus((current) => {
      if (focus !== undefined) return focus;
      return current && current === selectedDreamFocus && nextDreamId === selectedDreamId ? current : undefined;
    });
    if (dream.session_id) {
      setSelectedSessionId(dream.session_id);
    }
    showSection(nextSection);
  };

  const openDreamForSession = (dream: DreamRun) => {
    setDreamsSessionFilter(dream.session_id || undefined);
    openDream(dream, 'dreams');
  };

  const openDreamFocusForSession = (dream: DreamRun, focus: DreamArtifactsPanelProps['focus']) => {
    setDreamsSessionFilter(dream.session_id || undefined);
    openDream(dream, 'dreams', focus);
  };

  const openSessionDreams = () => {
    setDreamsSessionFilter(selectedSessionId);
    setSelectedDream(undefined);
    setSelectedDreamId(undefined);
    setSelectedDreamFocus(undefined);
    showSection('dreams');
  };

  const openSessionKnowledge = () => {
    setSelectedDream(undefined);
    setSelectedDreamId(undefined);
    setSelectedDreamFocus(undefined);
    setSelectedGraphTarget(undefined);
    setKnowledgeFocusQuery(selectedSessionId);
    showSection('knowledge');
  };

  const openGraphInspect = (target: GraphInspectTarget) => {
    setSelectedDreamFocus(undefined);
    setSelectedGraphTarget(target);
    showSection('knowledge');
  };

  const openSessionFromGraph = (sessionId: string) => {
    openSession(sessionId, 'sessions');
  };

  const sectionLabel = (id: (typeof sections)[number]) => {
    return t(language, `app.section.${id}`);
  };

  const controlAlert = firewallState ? firewallState.enabled === false : false;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">{t(language, 'app.header.eyebrow')}</p>
          <h1>{t(language, 'app.header.title')}</h1>
          <p className="app-header-meta">
            {t(language, 'app.header.version')} {text(monitorStatus?.monitor_version)} · {t(language, 'app.header.by')}{' '}
            <a href="https://www.linkedin.com/in/frank-richter-24657078/" target="_blank" rel="noreferrer">
              Frank Richter
            </a>
          </p>
        </div>
        <div className="app-toolbar">
          <div className="app-toolbar-group">
            <span className="app-toolbar-label">{t(language, 'app.toolbar.language')}</span>
            <div className="app-toolbar-switch" role="group" aria-label={t(language, 'app.toolbar.language')}>
              {(['de', 'en'] as const).map((option) => (
                <button
                  key={option}
                  className="app-toolbar-chip"
                  data-active={language === option ? 'true' : 'false'}
                  onClick={() => setLanguageAndUrl(option)}
                  type="button"
                >
                  {option.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div className="app-toolbar-group">
            <span className="app-toolbar-label">{t(language, 'app.toolbar.view')}</span>
            <div className="app-toolbar-switch" role="group" aria-label={t(language, 'app.toolbar.view')}>
              {(['both', 'deterministic', 'semantic'] as const).map((option) => (
                <button
                  key={option}
                  className="app-toolbar-chip"
                  data-active={memoryView === option ? 'true' : 'false'}
                  onClick={() => setMemoryView(option)}
                  type="button"
                >
                  {viewLabel(language, option)}
                </button>
              ))}
            </div>
          </div>
          <nav className="app-nav" aria-label={t(language, 'app.nav.label')}>
            {sections.map((id) => (
              <button
                className="app-nav-tab"
                data-active={activeSection === id ? 'true' : 'false'}
                data-alert={id === 'control' && controlAlert ? 'true' : 'false'}
                key={id}
                onClick={() => {
                  if (id === 'dreams') {
                    setDreamsSessionFilter(undefined);
                    setSelectedDream(undefined);
                    setSelectedDreamId(undefined);
                    setSelectedDreamFocus(undefined);
                  }
                  if (id === 'knowledge') {
                    setSelectedDream(undefined);
                    setSelectedDreamId(undefined);
                    setSelectedDreamFocus(undefined);
                    setSelectedGraphTarget(undefined);
                    setKnowledgeFocusQuery(undefined);
                  }
                  showSection(id);
                }}
                type="button"
              >
                {sectionLabel(id)}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="monitor-workbench">
        {activeSection === 'overview' ? (
          <section className="workbench-section workbench-section-wide" id="overview">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('overview')}</p>
              <h2>{t(language, 'app.heading.overview')}</h2>
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <OverviewPanel
                language={language}
                onOpenSession={(sessionId) => openSession(sessionId, 'sessions')}
                onOpenDream={(dream) => openDream(dream, 'dreams')}
                onOpenControl={() => showSection('control')}
                showHeading={false}
              />
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-overview-preview">
              <MonitorPilot language={language} />
              <FirewallPanel language={language} mode="overview" onStateChange={setFirewallState} />
            </div>
          </section>
        ) : null}

        {activeSection === 'sessions' ? (
          <section className="workbench-section workbench-section-wide" id="sessions">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('sessions')}</p>
              <h2>{t(language, 'app.heading.sessions')}</h2>
            </div>
            <div className="monitor-grid-shell">
              <SessionsPanel
                language={language}
                selectedSessionId={selectedSessionId}
                onSelectSession={(sessionId) => {
                  setSelectedSessionId(sessionId);
                }}
                query={sessionsQuery}
                showHeading={false}
              />
              <SessionDetailPanel
                language={language}
                memoryView={memoryView}
                sessionId={selectedSessionId}
                onOpenDream={openDreamForSession}
                onOpenDreamFocus={openDreamFocusForSession}
                onOpenDreamList={openSessionDreams}
                onOpenSessionKnowledge={openSessionKnowledge}
                onOpenControl={() => showSection('control')}
              />
            </div>
          </section>
        ) : null}

        {activeSection === 'dreams' ? (
          <section className="workbench-section workbench-section-wide" id="dreams">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('dreams')}</p>
              <h2>{t(language, 'app.heading.dreams')}</h2>
            </div>
            <div className="monitor-grid-shell">
              <DreamsPanel
                language={language}
                sessionId={dreamsSessionFilter}
                selectedDreamId={selectedDreamId}
                autoSelectFirst={true}
                onSelectDream={openDream}
                showHeading={false}
              />
              <DreamArtifactsPanel
                language={language}
                memoryView={memoryView}
                selectedDream={selectedDream}
                focus={selectedDreamFocus}
                onOpenSession={(sessionId) => openSession(sessionId, 'sessions')}
                onOpenKnowledge={() => showSection('knowledge')}
                onOpenControl={() => showSection('control')}
              />
            </div>
          </section>
        ) : null}

        {activeSection === 'statistics' ? (
          <section className="workbench-section workbench-section-wide" id="statistics">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('statistics')}</p>
              <h2>{t(language, 'app.heading.statistics')}</h2>
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <StatisticsPanel language={language} showHeading={false} />
            </div>
          </section>
        ) : null}

        {activeSection === 'knowledge' ? (
          <section className="workbench-section workbench-section-wide" id="knowledge">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('knowledge')}</p>
              <h2>{t(language, 'app.heading.knowledge')}</h2>
            </div>
            <div className="monitor-grid-shell">
              <KnowledgeFocusPanel
                language={language}
                memoryView={memoryView}
                focusTarget={selectedGraphTarget}
                focusQuery={knowledgeFocusQuery}
                selectedSessionId={selectedSessionId}
                onFocusQueryChange={setKnowledgeFocusQuery}
                onSelectNode={(node) => openGraphInspect({ kind: 'entity', id: node.id, label: asLabel(node.label) })}
                onSelectEdge={(edge) =>
                  openGraphInspect({ kind: 'relation', id: edge.id, label: asLabel(edge.type ?? edge.source ?? edge.target) })
                }
              />
              <GraphInspectPanel
                language={language}
                memoryView={memoryView}
                target={selectedGraphTarget}
                onOpenSession={openSessionFromGraph}
                onSelectGraphTarget={openGraphInspect}
              />
            </div>
            <div className="monitor-grid-shell">
              <GraphQueryPanel
                language={language}
                memoryView={memoryView}
                onSelectNode={(node) => openGraphInspect({ kind: 'entity', id: node.id, label: asLabel(node.label) })}
                onSelectEdge={(edge) =>
                  openGraphInspect({ kind: 'relation', id: edge.id, label: asLabel(edge.type ?? edge.source ?? edge.target) })
                }
              />
              <GraphPanel
                language={language}
                memoryView={memoryView}
                onSelectEntity={(entity) =>
                  openGraphInspect({ kind: 'entity', id: entity.id, label: entity.name ?? undefined })
                }
                onSelectRelation={(relation) =>
                  openGraphInspect({ kind: 'relation', id: relation.id, label: relation.type ?? undefined })
                }
              />
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <SessionDetailPanel
                language={language}
                memoryView={memoryView}
                sessionId={selectedSessionId}
                onOpenDream={openDreamForSession}
                onOpenDreamFocus={openDreamFocusForSession}
                onOpenDreamList={openSessionDreams}
                onOpenSessionKnowledge={openSessionKnowledge}
                onOpenControl={() => showSection('control')}
              />
            </div>
          </section>
        ) : null}

        {activeSection === 'integrations' ? (
          <section className="workbench-section workbench-section-wide" id="integrations">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('integrations')}</p>
              <h2>{t(language, 'app.heading.integrations')}</h2>
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <IntegrationsPanel language={language} showHeading={false} />
            </div>
          </section>
        ) : null}

        {activeSection === 'personal' ? (
          <section className="workbench-section workbench-section-wide" id="personal">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('personal')}</p>
              <h2>{t(language, 'app.heading.personal')}</h2>
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <PersonalPanel language={language} showHeading={false} />
            </div>
          </section>
        ) : null}

        {activeSection === 'howto' ? (
          <section className="workbench-section workbench-section-wide" id="howto">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('howto')}</p>
              <h2>{t(language, 'app.heading.howto')}</h2>
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <HowtoPanel language={language} onNavigate={(section) => showSection(section)} />
            </div>
          </section>
        ) : null}

        {activeSection === 'control' ? (
          <section className="workbench-section workbench-section-wide" id="control">
            <div className="section-heading">
              <p className="eyebrow">{sectionLabel('control')}</p>
              <h2>{t(language, 'app.heading.control')}</h2>
            </div>
            <div className="monitor-grid-shell">
              <FirewallPanel language={language} mode="full" onStateChange={setFirewallState} />
              <StoragePanel language={language} />
            </div>
            <div className="monitor-grid-shell monitor-grid-shell-single">
              <DiagnosticsPanel language={language} />
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
