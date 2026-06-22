import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import {
  getPersonalFile,
  getPersonalFiles,
  getRepoIndex,
  savePersonalFile,
  saveRepoIndex,
} from '../../shared/api/monitor';
import type { PersonalFile, PersonalFileListItem, PersonalFilesResponse, RepoIndexFile } from '../../shared/api/types';
import { LoadingBlock, LoadingLine } from '../../shared/components/PanelLoading';
import './personal-panel.css';

export type PersonalPanelProps = {
  language?: MonitorLanguage;
  showHeading?: boolean;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function compact(value: unknown, limit: number, fallback: string) {
  const normalized = text(value, fallback);
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

export function PersonalPanel({ language = 'en', showHeading = true }: PersonalPanelProps) {
  const [filesData, setFilesData] = useState<PersonalFilesResponse | undefined>();
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<PersonalFile | undefined>();
  const [personalDraft, setPersonalDraft] = useState('');
  const [repoIndex, setRepoIndex] = useState<RepoIndexFile | undefined>();
  const [repoDraft, setRepoDraft] = useState('');
  const [error, setError] = useState('');
  const [personalSaveState, setPersonalSaveState] = useState('');
  const [repoSaveState, setRepoSaveState] = useState('');
  const [filesLoading, setFilesLoading] = useState(true);
  const [selectedFileLoading, setSelectedFileLoading] = useState(false);
  const [repoLoading, setRepoLoading] = useState(true);
  const [personalSaving, setPersonalSaving] = useState(false);
  const [repoSaving, setRepoSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFilesLoading(true);
    setRepoLoading(true);
    Promise.all([getPersonalFiles(), getRepoIndex()])
      .then(([personalFilesPayload, repoIndexPayload]) => {
        if (cancelled) return;
        setFilesData(personalFilesPayload);
        const first = (personalFilesPayload.files ?? [])[0];
        if (first?.path) setSelectedPath(first.path);
        else setFilesLoading(false);
        setRepoIndex(repoIndexPayload);
        setRepoDraft(repoIndexPayload.content ?? '');
        setRepoLoading(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setFilesLoading(false);
          setRepoLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedPath) return;
    let cancelled = false;
    setSelectedFileLoading(true);
    getPersonalFile(selectedPath)
      .then((payload) => {
        if (cancelled) return;
        setSelectedFile(payload);
        setPersonalDraft(payload.content ?? '');
        setSelectedFileLoading(false);
        setFilesLoading(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setSelectedFileLoading(false);
          setFilesLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPath]);

  async function persistPersonalFile() {
    if (!selectedPath) return;
    setPersonalSaveState('');
    setRepoSaveState('');
    setError('');
    setPersonalSaving(true);
    try {
      const payload = await savePersonalFile(selectedPath, personalDraft);
      setSelectedFile(payload);
      setPersonalDraft(payload.content ?? '');
      setFilesData((current) => {
        if (!current) return current;
        return {
          ...current,
          files: (current.files ?? []).map((file) => (
            file.path === selectedPath
              ? { ...file, preview: compact(payload.content, 120, t(language, 'personal.noPreview')) }
              : file
          )),
        };
      });
      setPersonalSaveState(t(language, 'personal.fileSaved'));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPersonalSaving(false);
    }
  }

  async function persistRepoIndex() {
    setRepoSaveState('');
    setPersonalSaveState('');
    setError('');
    setRepoSaving(true);
    try {
      const payload = await saveRepoIndex(repoDraft);
      setRepoIndex(payload);
      setRepoDraft(payload.content ?? '');
      setRepoSaveState(t(language, 'personal.repoSaved'));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRepoSaving(false);
    }
  }

  const files: PersonalFileListItem[] = filesData?.files ?? [];
  const frontmatter = asRecord(selectedFile?.frontmatter);

  return (
    <section className="personal-panel">
      {showHeading ? (
        <div className="panel-heading">
          <div>
            <p className="eyebrow">{t(language, 'app.section.personal')}</p>
            <h2>{t(language, 'personal.heading')}</h2>
          </div>
          <span>
            {text(filesData?.total, '0')} {t(language, 'personal.files')} · {text(filesData?.startup_safe, '0')} startup-safe
          </span>
        </div>
      ) : null}
      {error ? <p className="panel-error">{error}</p> : null}

      <div className="personal-subgrid">
        <article className="personal-card">
          <div className="personal-card-head">
            <strong>{t(language, 'personal.memory')}</strong>
            <small>{text(filesData?.private_count, '0')} {t(language, 'personal.privateFiles')}</small>
          </div>
          <div className="personal-files-layout">
            <div className="personal-file-list">
              {filesLoading ? (
                Array.from({ length: 4 }).map((_, index) => (
                  <div className="personal-file-button personal-file-button-loading" key={index}>
                    <LoadingLine variant="title" />
                    <LoadingLine variant="default" />
                    <LoadingLine variant="long" />
                  </div>
                ))
              ) : files.length ? files.map((file) => (
                <button
                  key={file.path}
                  className="personal-file-button"
                  data-selected={selectedPath === file.path ? 'true' : 'false'}
                  onClick={() => setSelectedPath(file.path ?? '')}
                  type="button"
                >
                  <strong>{text(file.title, file.path)}</strong>
                  <small>{text(file.path)}</small>
                  <span>{compact(file.preview, 120, t(language, 'personal.noPreview'))}</span>
                </button>
              )) : (
                <p className="empty-copy">{t(language, 'personal.noFiles')}</p>
              )}
            </div>
            <div className="personal-editor panel-loading-shell">
              <div className={selectedFileLoading ? 'panel-loading-dim' : ''} data-loading={selectedFileLoading ? 'true' : 'false'}>
                <div className="personal-meta">
                  <span>{selectedFileLoading ? `${t(language, 'common.loading')}...` : text(selectedFile?.path, t(language, 'personal.noFileSelected'))}</span>
                  <small>{selectedFileLoading ? `${t(language, 'common.loading')}...` : `${text(frontmatter.injection_policy, 'on_demand')} · ${text(frontmatter.sensitivity, 'normal')}`}</small>
                </div>
                <textarea className="personal-textarea" disabled={selectedFileLoading || personalSaving} onChange={(event) => setPersonalDraft(event.target.value)} value={personalDraft} />
                <div className="personal-actions">
                  <button disabled={!selectedPath || selectedFileLoading || personalSaving} onClick={() => void persistPersonalFile()} type="button">
                    {personalSaving ? t(language, 'personal.savingFile') : t(language, 'personal.saveFile')}
                  </button>
                </div>
                {personalSaveState ? <p className="personal-save-note">{personalSaveState}</p> : null}
              </div>
              {selectedFileLoading ? (
                <div className="panel-loading-overlay personal-editor-overlay" aria-hidden="true">
                  <LoadingLine variant="title" />
                  <LoadingLine variant="long" />
                  <LoadingLine variant="default" />
                </div>
              ) : null}
            </div>
          </div>
        </article>

        <article className="personal-card">
          <div className="personal-card-head">
            <strong>{t(language, 'personal.repoIndex')}</strong>
            <small>{text(repoIndex?.path, 'memory/knowledge/repos.md')}</small>
          </div>
          {repoLoading && !repoIndex ? (
            <div className="personal-repo-loading">
              <LoadingBlock lines={['title', 'long', 'default']} />
              <LoadingBlock lines={['long', 'default', 'default', 'short']} />
            </div>
          ) : (
            <>
              <p className="personal-privacy-note">
                {repoLoading ? `${t(language, 'common.loading')}...` : text(repoIndex?.privacy_note, t(language, 'personal.privacyFallback'))}
              </p>
              <textarea className="personal-textarea personal-textarea-large" disabled={repoLoading || repoSaving} onChange={(event) => setRepoDraft(event.target.value)} value={repoDraft} />
              <div className="personal-actions">
                <button disabled={repoLoading || repoSaving} onClick={() => void persistRepoIndex()} type="button">
                  {repoSaving ? t(language, 'personal.savingRepo') : t(language, 'personal.saveRepo')}
                </button>
              </div>
            </>
          )}
          {repoSaveState ? <p className="personal-save-note">{repoSaveState}</p> : null}
        </article>
      </div>
    </section>
  );
}
