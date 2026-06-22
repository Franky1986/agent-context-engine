import { useEffect, useMemo, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getStats, type StatsQueryOptions } from '../../shared/api/monitor';
import type { MonitorStatsBucket, MonitorStatsGroup, MonitorStatsResponse } from '../../shared/api/types';
import { LoadingCard } from '../../shared/components/PanelLoading';
import './statistics-panel.css';

const STATS_POLL_MS = 15000;
const GROUP_LIMIT = 8;
const TIME_CHART_HEIGHT = 360;
const TIME_CHART_WIDTH = 1040;

type RangeName = 'today' | '2d' | '7d' | '30d' | 'custom';

type FiltersState = {
  range: RangeName;
  start: string;
  end: string;
  client: string;
  project: string;
  workdir: string;
};

export type StatisticsPanelProps = {
  language?: MonitorLanguage;
  showHeading?: boolean;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function number(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) return Number(value);
  return 0;
}

function localeFor(language: MonitorLanguage) {
  return language === 'de' ? 'de-DE' : 'en-US';
}

function formatNumber(value: unknown, language: MonitorLanguage) {
  return new Intl.NumberFormat(localeFor(language)).format(number(value));
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function toDateTimeLocalInput(value: string) {
  if (!value) return '';
  const normalized = value.endsWith('Z') ? value : `${value}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  const hours = `${date.getHours()}`.padStart(2, '0');
  const minutes = `${date.getMinutes()}`.padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function toApiDateTime(value: string) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
}

function compactPath(value: string, limit = 48) {
  return value.length > limit ? `...${value.slice(-(limit - 3))}` : value;
}

function buildQuery(filters: FiltersState): StatsQueryOptions {
  return {
    range: filters.range,
    start: filters.range === 'custom' ? toApiDateTime(filters.start) || undefined : undefined,
    end: filters.range === 'custom' ? toApiDateTime(filters.end) || undefined : undefined,
    client: filters.client || undefined,
    project: filters.project || undefined,
    workdir: filters.workdir || undefined,
  };
}

function kpiRows(language: MonitorLanguage, data?: MonitorStatsResponse) {
  const totals = data?.totals ?? {};
  const sessionTotal = number(totals.session_total_tokens);
  const dreamTotal = number(totals.dream_total_tokens);
  const combined = sessionTotal + dreamTotal;
  const dreamShare = combined > 0 ? dreamTotal / combined : 0;
  return [
    { label: t(language, 'statistics.kpi.sessionTokens'), value: formatNumber(sessionTotal, language), tone: 'session' },
    { label: t(language, 'statistics.kpi.dreamTokens'), value: formatNumber(dreamTotal, language), tone: 'dream' },
    { label: t(language, 'statistics.kpi.totalTokens'), value: formatNumber(combined, language), tone: 'total' },
    { label: t(language, 'statistics.kpi.sessions'), value: formatNumber(totals.session_count, language), tone: 'neutral' },
    { label: t(language, 'statistics.kpi.dreams'), value: formatNumber(totals.dream_count, language), tone: 'neutral' },
    { label: t(language, 'statistics.kpi.dreamShare'), value: formatPercent(dreamShare), tone: 'mix' },
  ];
}

function TimeSeriesChart({
  buckets,
  language,
}: {
  buckets: MonitorStatsBucket[];
  language: MonitorLanguage;
}) {
  const rows = buckets.filter((bucket) => number(bucket.session_total_tokens) > 0 || number(bucket.dream_total_tokens) > 0);
  if (!rows.length) {
    return <p className="statistics-empty">{t(language, 'statistics.emptyRange')}</p>;
  }
  const maxValue = Math.max(
    1,
    ...rows.map((bucket) => Math.max(number(bucket.session_total_tokens), number(bucket.dream_total_tokens))),
  );
  const chartHeight = TIME_CHART_HEIGHT;
  const chartWidth = TIME_CHART_WIDTH;
  const marginTop = 24;
  const marginBottom = 118;
  const marginLeft = 88;
  const marginRight = 16;
  const plotHeight = chartHeight - marginTop - marginBottom;
  const plotWidth = chartWidth - marginLeft - marginRight;
  const band = plotWidth / rows.length;
  const sessionBarWidth = Math.max(6, band * 0.46);
  const dreamBarWidth = Math.max(4, band * 0.2);
  const ticks = 4;
  const labelStep = Math.max(1, Math.ceil(rows.length / 8));
  const yFor = (value: number) => marginTop + plotHeight - (value / maxValue) * plotHeight;

  return (
    <div className="statistics-time-chart-shell">
      <svg className="statistics-time-chart" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={t(language, 'statistics.timeChart')}>
        <g className="statistics-grid">
          {Array.from({ length: ticks + 1 }).map((_, index) => {
            const value = (maxValue / ticks) * index;
            const y = yFor(value);
            return (
              <g key={index}>
                <line x1={marginLeft} x2={chartWidth - marginRight} y1={y} y2={y} />
                <text x={marginLeft - 12} y={y + 4} textAnchor="end">
                  {formatNumber(Math.round(value), language)}
                </text>
              </g>
            );
          })}
        </g>
        <g className="statistics-bars">
          {rows.map((bucket, index) => {
            const sessionTotal = number(bucket.session_total_tokens);
            const dreamTotal = number(bucket.dream_total_tokens);
            const x = marginLeft + index * band;
            const label = text(bucket.hour).slice(5, 16).replace('T', ' ');
            const showLabel = index % labelStep === 0 || index === rows.length - 1;
            return (
              <g key={text(bucket.hour, String(index))}>
                <rect
                  className="statistics-bar-session"
                  x={x + band * 0.08}
                  y={yFor(sessionTotal)}
                  width={sessionBarWidth}
                  height={Math.max(0, marginTop + plotHeight - yFor(sessionTotal))}
                  rx={4}
                />
                <rect
                  className="statistics-bar-dream"
                  x={x + band * 0.62}
                  y={yFor(dreamTotal)}
                  width={dreamBarWidth}
                  height={Math.max(0, marginTop + plotHeight - yFor(dreamTotal))}
                  rx={4}
                />
                {showLabel ? (
                  <text
                    className="statistics-axis-label"
                    x={x + band * 0.5}
                    y={chartHeight - 62}
                    textAnchor="end"
                    transform={`rotate(-90 ${x + band * 0.5} ${chartHeight - 62})`}
                  >
                    {label}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="statistics-legend">
        <span><i className="statistics-legend-swatch statistics-legend-session" /> {t(language, 'statistics.legend.session')}</span>
        <span><i className="statistics-legend-swatch statistics-legend-dream" /> {t(language, 'statistics.legend.dream')}</span>
      </div>
    </div>
  );
}

function BreakdownCard({
  title,
  subtitle,
  rows,
  language,
  pathLike = false,
}: {
  title: string;
  subtitle: string;
  rows: MonitorStatsGroup[];
  language: MonitorLanguage;
  pathLike?: boolean;
}) {
  const items = rows.slice(0, GROUP_LIMIT);
  const maxCombined = Math.max(1, ...items.map((item) => number(item.total_tokens)));
  return (
    <article className="statistics-breakdown-card">
      <div className="statistics-breakdown-head">
        <div>
          <p className="eyebrow">{subtitle}</p>
          <h3>{title}</h3>
        </div>
      </div>
      {items.length ? (
        <div className="statistics-breakdown-list">
          {items.map((item) => {
            const sessionTotal = number(item.session_total_tokens);
            const dreamTotal = number(item.dream_total_tokens);
            const combined = Math.max(1, number(item.total_tokens));
            const label = pathLike ? compactPath(text(item.label)) : text(item.label);
            return (
              <div className="statistics-breakdown-row" key={text(item.group_key)}>
                <div className="statistics-breakdown-meta">
                  <strong title={text(item.label)}>{label}</strong>
                  <small>
                    {t(language, 'statistics.row.session')}: {formatNumber(sessionTotal, language)}
                    {' · '}
                    {t(language, 'statistics.row.dream')}: {formatNumber(dreamTotal, language)}
                    {' · '}
                    {t(language, 'statistics.row.share')}: {formatPercent(number(item.total_share))}
                  </small>
                </div>
                <div className="statistics-breakdown-bars" aria-hidden="true">
                  <div className="statistics-breakdown-track">
                    <div className="statistics-breakdown-fill statistics-breakdown-fill-session" style={{ width: `${(sessionTotal / maxCombined) * 100}%` }} />
                  </div>
                  <div className="statistics-breakdown-track">
                    <div className="statistics-breakdown-fill statistics-breakdown-fill-dream" style={{ width: `${(dreamTotal / maxCombined) * 100}%` }} />
                  </div>
                </div>
                <div className="statistics-breakdown-totals">
                  <strong>{formatNumber(item.total_tokens, language)}</strong>
                  <small>
                    {formatNumber(item.session_count, language)} {t(language, 'statistics.row.sessions')}
                    {' · '}
                    {formatNumber(item.dream_count, language)} {t(language, 'statistics.row.dreams')}
                  </small>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="statistics-empty">{t(language, 'statistics.emptyBreakdown')}</p>
      )}
    </article>
  );
}

export function StatisticsPanel({
  language = 'en',
  showHeading = true,
}: StatisticsPanelProps) {
  const [filters, setFilters] = useState<FiltersState>({
    range: '2d',
    start: '',
    end: '',
    client: '',
    project: '',
    workdir: '',
  });
  const [data, setData] = useState<MonitorStatsResponse | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | undefined>();

  useEffect(() => {
    let cancelled = false;
    const load = (background = false) => {
      if (!background) {
        setLoading(true);
      }
      getStats(buildQuery(filters))
        .then((payload) => {
          if (cancelled) return;
          setData(payload);
          setError('');
          setLoading(false);
          setUpdatedAt(new Date());
          if (payload.range?.name === 'custom') {
            setFilters((current) => ({
              ...current,
              start: current.start || toDateTimeLocalInput(text(payload.range?.start, '')),
              end: current.end || toDateTimeLocalInput(text(payload.range?.end, '')),
            }));
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : String(err));
            setLoading(false);
          }
        });
    };

    load(false);
    const timer = window.setInterval(() => load(true), STATS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [filters]);

  const statsKpis = useMemo(() => kpiRows(language, data), [language, data]);
  const buckets = useMemo(() => (Array.isArray(data?.buckets) ? data.buckets : []), [data]);
  const byProject = useMemo(() => (Array.isArray(data?.by_project) ? data.by_project : []), [data]);
  const byClient = useMemo(() => (Array.isArray(data?.by_client) ? data.by_client : []), [data]);
  const byWorkdir = useMemo(() => (Array.isArray(data?.by_workdir) ? data.by_workdir : []), [data]);
  const byDreamRunner = useMemo(() => (Array.isArray(data?.by_dream_runner) ? data.by_dream_runner : []), [data]);
  const byDreamModel = useMemo(() => (Array.isArray(data?.by_dream_model) ? data.by_dream_model : []), [data]);

  return (
    <section className="statistics-panel" aria-busy={loading}>
      {showHeading ? (
        <div className="panel-heading statistics-heading">
          <div>
            <p className="eyebrow">{t(language, 'app.section.statistics')}</p>
            <h2>{t(language, 'statistics.title')}</h2>
          </div>
          <small>{t(language, 'statistics.updated')} {updatedAt ? updatedAt.toLocaleTimeString() : '-'}</small>
        </div>
      ) : null}

      <div className="statistics-filters">
        <label>
          <span>{t(language, 'statistics.filters.range')}</span>
          <select value={filters.range} onChange={(event) => setFilters((current) => ({ ...current, range: event.target.value as RangeName }))}>
            <option value="today">{t(language, 'statistics.range.today')}</option>
            <option value="2d">{t(language, 'statistics.range.2d')}</option>
            <option value="7d">{t(language, 'statistics.range.7d')}</option>
            <option value="30d">{t(language, 'statistics.range.30d')}</option>
            <option value="custom">{t(language, 'statistics.range.custom')}</option>
          </select>
        </label>
        <label>
          <span>{t(language, 'statistics.filters.start')}</span>
          <input
            disabled={filters.range !== 'custom'}
            type="datetime-local"
            value={filters.start}
            onChange={(event) => setFilters((current) => ({ ...current, start: event.target.value }))}
          />
        </label>
        <label>
          <span>{t(language, 'statistics.filters.end')}</span>
          <input
            disabled={filters.range !== 'custom'}
            type="datetime-local"
            value={filters.end}
            onChange={(event) => setFilters((current) => ({ ...current, end: event.target.value }))}
          />
        </label>
        <label>
          <span>{t(language, 'statistics.filters.client')}</span>
          <select value={filters.client} onChange={(event) => setFilters((current) => ({ ...current, client: event.target.value }))}>
            <option value="">{t(language, 'statistics.filters.allClients')}</option>
            {(data?.clients ?? []).map((client) => <option key={client} value={client}>{client}</option>)}
          </select>
        </label>
        <label>
          <span>{t(language, 'statistics.filters.project')}</span>
          <select value={filters.project} onChange={(event) => setFilters((current) => ({ ...current, project: event.target.value }))}>
            <option value="">{t(language, 'statistics.filters.allProjects')}</option>
            {(data?.projects ?? []).map((project) => <option key={project} value={project}>{project}</option>)}
          </select>
        </label>
        <label>
          <span>{t(language, 'statistics.filters.workdir')}</span>
          <select value={filters.workdir} onChange={(event) => setFilters((current) => ({ ...current, workdir: event.target.value }))}>
            <option value="">{t(language, 'statistics.filters.allWorkdirs')}</option>
            {(data?.workdirs ?? []).map((workdir) => <option key={workdir} value={workdir}>{compactPath(workdir, 56)}</option>)}
          </select>
        </label>
      </div>

      {error ? <p className="panel-error">{error}</p> : null}

      {loading && !data ? (
        <div className="statistics-loading-grid">
          <LoadingCard className="statistics-loading-card" />
          <LoadingCard className="statistics-loading-card" />
          <LoadingCard className="statistics-loading-card" />
        </div>
      ) : (
        <>
          <div className="statistics-kpi-grid">
            {statsKpis.map((kpi) => (
              <article className="statistics-kpi-card" data-tone={kpi.tone} key={kpi.label}>
                <p className="eyebrow">{kpi.label}</p>
                <strong>{kpi.value}</strong>
              </article>
            ))}
          </div>

          <article className="statistics-chart-card">
            <div className="statistics-breakdown-head">
              <div>
                <p className="eyebrow">{t(language, 'statistics.timeSeries.eyebrow')}</p>
                <h3>{t(language, 'statistics.timeSeries.title')}</h3>
              </div>
              <small>{t(language, 'statistics.updated')} {updatedAt ? updatedAt.toLocaleTimeString() : '-'}</small>
            </div>
            <TimeSeriesChart buckets={buckets} language={language} />
          </article>

          <div className="statistics-breakdown-grid">
            <BreakdownCard language={language} rows={byProject} subtitle={t(language, 'statistics.groupedUsage')} title={t(language, 'statistics.breakdown.project')} />
            <BreakdownCard language={language} rows={byClient} subtitle={t(language, 'statistics.groupedUsage')} title={t(language, 'statistics.breakdown.client')} />
            <BreakdownCard language={language} rows={byDreamRunner} subtitle={t(language, 'statistics.dreamOnly')} title={t(language, 'statistics.breakdown.runner')} />
            <BreakdownCard language={language} rows={byDreamModel} subtitle={t(language, 'statistics.dreamOnly')} title={t(language, 'statistics.breakdown.model')} />
            <BreakdownCard language={language} pathLike rows={byWorkdir} subtitle={t(language, 'statistics.groupedUsage')} title={t(language, 'statistics.breakdown.workdir')} />
          </div>
        </>
      )}
    </section>
  );
}
