import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { booleanLabel, storageDescription, storageLabel } from '../../app/i18n/monitorFormatters';
import { getNeo4jStorage, getStorage } from '../../shared/api/monitor';
import type { Neo4jStorageStatus, StorageStatus } from '../../shared/api/types';
import { LoadingBlock, LoadingCard, LoadingLine } from '../../shared/components/PanelLoading';
import './storage-panel.css';

export type StoragePanelProps = {
  initialData?: StorageStatus;
  showNeo4j?: boolean;
  language?: MonitorLanguage;
};

type RecordLike = Record<string, unknown>;

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function formatBytes(value: unknown) {
  const bytes = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(bytes)) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function asRecord(value: unknown): RecordLike {
  return value && typeof value === 'object' ? (value as RecordLike) : {};
}

function asRecordArray(value: unknown): RecordLike[] {
  return Array.isArray(value) ? value.filter((item): item is RecordLike => Boolean(item) && typeof item === 'object') : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function formatMtime(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return new Date(value * 1000).toLocaleString();
  }
  return text(value, '-');
}

export function StoragePanel({ initialData, showNeo4j = true, language = 'en' }: StoragePanelProps) {
  const [data, setData] = useState<StorageStatus | undefined>(initialData);
  const [neo4j, setNeo4j] = useState<Neo4jStorageStatus | undefined>();
  const [error, setError] = useState('');
  const [neo4jError, setNeo4jError] = useState('');
  const [loading, setLoading] = useState(!initialData);
  const [neo4jLoading, setNeo4jLoading] = useState(showNeo4j);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    setLoading(true);
    getStorage()
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initialData]);

  useEffect(() => {
    if (!showNeo4j) return;
    let cancelled = false;
    setNeo4jLoading(true);
    getNeo4jStorage()
      .then((payload) => {
        if (!cancelled) {
          setNeo4j(payload);
          setNeo4jLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setNeo4jError(err instanceof Error ? err.message : String(err));
          setNeo4jLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [showNeo4j]);

  const total = asRecord(data?.total);
  const categories = asRecordArray(data?.categories);
  const sqlite = asRecord(data?.sqlite);
  const sqliteFiles = asRecordArray(sqlite.files);
  const sqliteRows = asRecordArray(sqlite.row_counts);
  const warnings = asRecordArray(data?.warnings);
  const cleanupCommands = asStringArray(data?.cleanup_commands);
  const instanceMetadata = asRecord(data?.instance_metadata);
  const neo4jConfig = asRecord(neo4j?.config);
  const neo4jCounts = asRecord(neo4j?.counts);
  const neo4jSize = asRecord(neo4j?.size);
  const databaseFootprint = formatBytes(sqlite.total_size_bytes ?? data?.size_bytes ?? data?.bytes);

  if (loading && !data && !error) {
    return (
      <section className="storage-panel" aria-busy="true">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t(language, 'storage.heading.control')}</p>
            <h2>{t(language, 'common.loading')}...</h2>
          </div>
          <span>{t(language, 'common.loading')}...</span>
        </div>
        <div className="storage-kpi-grid">
          {Array.from({ length: 4 }).map((_, index) => (
            <article className="storage-kpi-card storage-kpi-card-loading" key={index}>
              <LoadingBlock lines={['short', 'metric', 'default']} />
            </article>
          ))}
        </div>
        <div className="panel-loading-grid storage-loading-grid">
          <LoadingCard />
          <LoadingCard />
          <LoadingCard />
        </div>
      </section>
    );
  }

  return (
    <section aria-busy={loading || neo4jLoading} className="storage-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t(language, 'storage.heading.control')}</p>
          <h2>{t(language, 'storage.heading.title')}</h2>
        </div>
        <span>
          {formatBytes(total.size_bytes ?? data?.size_bytes ?? data?.bytes)}
          {neo4jLoading ? ` · ${t(language, 'common.loading')}...` : ''}
        </span>
      </div>
      {error ? <p className="panel-error">{error}</p> : null}

      <div className="storage-kpi-grid">
        <article className="storage-kpi-card">
          <small>{t(language, 'storage.kpi.warnings')}</small>
          <strong>{warnings.length}</strong>
          <span>{t(language, 'storage.kpi.warningsHint')}</span>
        </article>
        <article className="storage-kpi-card">
          <small>{t(language, 'storage.kpi.storageAreas')}</small>
          <strong>{categories.length}</strong>
          <span>{t(language, 'storage.kpi.storageAreasHint')}</span>
        </article>
        <article className="storage-kpi-card">
          <small>{t(language, 'storage.kpi.databases')}</small>
          <strong>{sqliteFiles.length}</strong>
          <span>{t(language, 'storage.kpi.databasesHint')}</span>
        </article>
        <article className="storage-kpi-card">
          <small>{t(language, 'storage.kpi.sqliteSize')}</small>
          <strong>{databaseFootprint}</strong>
          <span>{t(language, 'storage.kpi.sqliteSizeHint')}</span>
        </article>
      </div>

      <div className="storage-facts">
        <div>
          <dt>{t(language, 'storage.meta.projectRoot')}</dt>
          <dd>{text(data?.install_root ?? data?.root)}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.memoryDir')}</dt>
          <dd>{text(data?.memory_root ?? data?.memory_dir)}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.filesFolders')}</dt>
          <dd>{text(total.file_count, '0')} / {text(total.dir_count, '0')}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.kpi.sqliteSize')}</dt>
          <dd>{databaseFootprint}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.schemaVersion')}</dt>
          <dd>{text(data?.storage_schema_version, '-')}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.storageProfile')}</dt>
          <dd>{text(data?.storage_profile_path, '-')}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.userConfig')}</dt>
          <dd>{text(data?.user_config_path, '-')}</dd>
        </div>
        <div>
          <dt>{t(language, 'storage.meta.instanceMetadata')}</dt>
          <dd>{text(data?.instance_metadata_path, '-')}</dd>
        </div>
      </div>

      <details className="storage-block" open>
        <summary>{t(language, 'storage.section.installation')}</summary>
        <div className="storage-facts">
          <div>
            <dt>{t(language, 'storage.meta.productVersion')}</dt>
            <dd>{text(instanceMetadata.product_version, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.monitorVersion')}</dt>
            <dd>{text(instanceMetadata.monitor_version, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.instanceId')}</dt>
            <dd>{text(instanceMetadata.instance_id, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.userRoot')}</dt>
            <dd>{text(data?.user_state_root, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.checkoutBranch')}</dt>
            <dd>{text(instanceMetadata.checkout_branch, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.checkoutCommit')}</dt>
            <dd>{text(instanceMetadata.checkout_commit, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.wrapperSuffix')}</dt>
            <dd>{text(instanceMetadata.wrapper_suffix, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.installedAt')}</dt>
            <dd>{text(instanceMetadata.installed_at, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.updatedAt')}</dt>
            <dd>{text(instanceMetadata.last_updated_at, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.lastDoctor')}</dt>
            <dd>{text(instanceMetadata.last_successful_doctor_at, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.lastCheck')}</dt>
            <dd>{text(instanceMetadata.last_successful_check_at, '-')}</dd>
          </div>
          <div>
            <dt>{t(language, 'storage.meta.gitRemote')}</dt>
            <dd>{text(instanceMetadata.checkout_remote, '-')}</dd>
          </div>
        </div>
      </details>

      {warnings.length ? (
        <details className="storage-block" open>
          <summary>{t(language, 'storage.section.signals')}</summary>
          <div className="storage-list">
            {warnings.map((warning, index) => (
              <article className="storage-row" data-level={text(warning.level, 'info')} key={`${text(warning.message)}-${index}`}>
                <strong>{text(warning.level, 'info')}</strong>
                <span>{text(warning.message, t(language, 'storage.noWarningText'))}</span>
              </article>
            ))}
          </div>
        </details>
      ) : null}

      <details className="storage-block" open>
        <summary>{t(language, 'storage.section.databases')}</summary>
        <div className="storage-subgrid">
          <article className="storage-card">
            <strong>{t(language, 'storage.section.files')}</strong>
            <div className="storage-list">
              {sqliteFiles.length ? sqliteFiles.map((file, index) => (
                <article className="storage-row" key={`${text(file.path)}-${index}`}>
                  <span>{text(file.name, text(file.path))}</span>
                  <small>{formatBytes(file.size_bytes)} · {booleanLabel(language, file.exists)}</small>
                </article>
              )) : <p className="empty-copy">{t(language, 'storage.noSqliteFiles')}</p>}
            </div>
          </article>
          <article className="storage-card">
            <strong>{t(language, 'storage.section.tableCounts')}</strong>
            <div className="storage-list">
              {sqliteRows.length ? sqliteRows.map((row, index) => (
                <article className="storage-row" key={`${text(row.table)}-${index}`}>
                  <span>{storageLabel(language, row.label ?? row.table)}</span>
                  <small>{text(row.rows, '0')} {t(language, 'storage.rows')}</small>
                </article>
              )) : <p className="empty-copy">{t(language, 'storage.noTableCounts')}</p>}
            </div>
          </article>
        </div>
      </details>

      <details className="storage-block" open>
        <summary>{t(language, 'storage.section.importantPaths')}</summary>
        <div className="storage-list">
          {categories.length ? categories.map((category, index) => {
            const largestFiles = asRecordArray(category.largest_files);
            const errors = asStringArray(category.errors);
            return (
              <article className="storage-row storage-row-rich" key={`${text(category.key, text(category.path))}-${index}`}>
                <div className="storage-row-head">
                  <strong>{storageLabel(language, category.label ?? category.key ?? 'category')}</strong>
                  <small>
                    {formatBytes(category.size_bytes)} · {text(category.file_count, '0')} {t(language, 'storage.files')} · {text(category.dir_count, '0')} {t(language, 'storage.dirs')}
                  </small>
                </div>
                <span>{storageDescription(language, category.description)}</span>
                <code>{text(category.path)}</code>
                <small>{t(language, 'storage.absolute')}: {text(category.absolute_path)}</small>
                <small>{t(language, 'storage.newest')}: {formatMtime(category.newest_mtime)}</small>
                {largestFiles.length ? (
                  <div className="storage-inline-list">
                    {largestFiles.slice(0, 3).map((file, fileIndex) => (
                      <span key={`${text(file.path)}-${fileIndex}`}>{text(file.path)} ({formatBytes(file.size_bytes)})</span>
                    ))}
                  </div>
                ) : null}
                {errors.length ? (
                  <div className="storage-inline-list">
                    {errors.slice(0, 3).map((item, errorIndex) => (
                      <span key={`${item}-${errorIndex}`}>{item}</span>
                    ))}
                  </div>
                ) : null}
              </article>
            );
          }) : <p className="empty-copy">{t(language, 'storage.noStorageAreas')}</p>}
        </div>
      </details>

      <details className="storage-block">
        <summary>{t(language, 'storage.section.neo4jProjection')}</summary>
        {neo4jError ? <p className="panel-error">{neo4jError}</p> : null}
        {neo4jLoading && !neo4j ? (
          <div className="storage-subgrid">
            <article className="storage-card">
              <LoadingBlock lines={['title', 'long', 'default', 'default']} />
            </article>
            <article className="storage-card">
              <LoadingBlock lines={['title', 'metric', 'default', 'default']} />
            </article>
          </div>
        ) : (
        <div className="storage-subgrid">
          <article className="storage-card">
            <strong>{t(language, 'storage.section.configuration')}</strong>
            <dl className="storage-mini-facts">
              <div><dt>{t(language, 'storage.meta.configured')}</dt><dd>{booleanLabel(language, neo4j?.configured)}</dd></div>
              <div><dt>{t(language, 'storage.meta.uri')}</dt><dd>{text(neo4jConfig.uri)}</dd></div>
              <div><dt>{t(language, 'storage.meta.database')}</dt><dd>{text(neo4jConfig.database)}</dd></div>
              <div><dt>{t(language, 'storage.meta.user')}</dt><dd>{text(neo4jConfig.user)}</dd></div>
            </dl>
          </article>
          <article className="storage-card">
            <strong>{t(language, 'storage.section.contents')}</strong>
            <dl className="storage-mini-facts">
              <div><dt>{t(language, 'storage.entities')}</dt><dd>{text(neo4jCounts.entities, '0')}</dd></div>
              <div><dt>{t(language, 'storage.relations')}</dt><dd>{text(neo4jCounts.relations, '0')}</dd></div>
              <div><dt>{t(language, 'storage.evidence')}</dt><dd>{text(neo4jCounts.evidence, '0')}</dd></div>
              <div><dt>{t(language, 'storage.size')}</dt><dd>{formatBytes(neo4jSize.size_bytes)}</dd></div>
            </dl>
          </article>
        </div>
        )}
        {neo4j?.error ? <p className="empty-copy">{text(neo4j.error)}</p> : null}
      </details>

      <details className="storage-block">
        <summary>{t(language, 'storage.section.cleanupHints')}</summary>
        <div className="storage-inline-list">
          {cleanupCommands.length ? cleanupCommands.map((command) => (
            <code key={command}>{command}</code>
          )) : <span>{t(language, 'storage.noCleanupHints')}</span>}
        </div>
      </details>
    </section>
  );
}
