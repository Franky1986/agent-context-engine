import de from './de';
import en from './en';

type LanguageCode = 'de' | 'en';
type Params = Record<string, unknown>;
type MessageValue = string | ((params: Params) => string);
type Messages = Record<string, MessageValue>;

const catalogs: Record<LanguageCode, Messages> = { de, en };

function interpolate(template: string, params: Params) {
  return template.replace(/\{(\w+)\}/g, (_, key) => {
    const value = params[key];
    return value === null || value === undefined ? '' : String(value);
  });
}

export function hasMessage(key: string, language: LanguageCode = 'en') {
  return key in catalogs[language];
}

export function t(language: LanguageCode, key: string, params: Params = {}, fallback?: string) {
  const entry = catalogs[language][key] ?? catalogs.en[key];
  if (typeof entry === 'function') {
    return entry(params);
  }
  if (typeof entry === 'string') {
    return interpolate(entry, params);
  }
  return fallback ?? key;
}
