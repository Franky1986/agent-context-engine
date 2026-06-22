import { t } from '../../app/i18n';

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { accept: 'application/json' } });
  if (!response.ok) {
    throw await apiError(response);
  }
  return response.json() as Promise<T>;
}

declare global {
  interface Window {
    MONITOR_TOKEN?: string;
    MONITOR_LANGUAGE?: 'de' | 'en';
  }
}

function jsonHeaders() {
  const headers: Record<string, string> = {
    accept: 'application/json',
    'content-type': 'application/json',
  };
  if (window.MONITOR_TOKEN) headers['x-agent-context-engine-monitor-token'] = window.MONITOR_TOKEN;
  return headers;
}

function currentLanguage() {
  return window.MONITOR_LANGUAGE === 'de' ? 'de' : 'en';
}

async function apiError(response: Response): Promise<Error> {
  let detail = '';
  let errorCode = '';
  try {
    const payload = (await response.json()) as { error?: string; answer?: string; error_code?: string };
    detail = String(payload.error || payload.answer || '').trim();
    errorCode = String(payload.error_code || '').trim();
  } catch {
    detail = '';
    errorCode = '';
  }
  const language = currentLanguage();
  if (errorCode) {
    const key = `api.error.${errorCode}`;
    return new Error(
      t(language, key, { status: response.status, detail, statusText: response.statusText }, detail
        ? t(language, 'api.error.requestFailedWithDetail', { status: response.status, detail })
        : t(language, 'api.error.requestFailed', { status: response.status, statusText: response.statusText })),
    );
  }
  if (detail) {
    return new Error(t(language, 'api.error.requestFailedWithDetail', { status: response.status, detail }));
  }
  return new Error(t(language, 'api.error.requestFailed', { status: response.status, statusText: response.statusText }));
}

export async function apiPost<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await apiError(response);
  }
  return response.json() as Promise<T>;
}

export async function apiDelete<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await apiError(response);
  }
  return response.json() as Promise<T>;
}
