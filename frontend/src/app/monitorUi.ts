import { t } from './i18n';

export type MonitorLanguage = 'de' | 'en';
export type MemoryView = 'both' | 'deterministic' | 'semantic';

export function uiText(language: MonitorLanguage, german: string, english: string) {
  return language === 'de' ? german : english;
}

export function viewLabel(language: MonitorLanguage, view: MemoryView) {
  return t(language, `monitor.view.${view}`);
}
