function text(value: unknown, fallback = '') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function sectionText(markdown: string, heading: string) {
  const lines = markdown.split('\n');
  const out: string[] = [];
  let inSection = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line === `## ${heading}`) {
      inSection = true;
      continue;
    }
    if (inSection && line.startsWith('## ')) {
      break;
    }
    if (inSection) {
      out.push(rawLine);
    }
  }
  return out.join('\n').trim();
}

function findDreamMarkdown(item: Record<string, unknown>) {
  const files = [
    ...list(item.audit_files),
    ...list(item.downstream_files),
    ...list(item.memory_files),
  ].map(record);
  return files.find((file) => {
    const path = text(file.path);
    return path.includes('/01-dream-narrative/dream.md') || path.endsWith('/dream.md');
  });
}

export function dreamNarrativeSections(item: Record<string, unknown>) {
  const markdown = text(findDreamMarkdown(item)?.content);
  return {
    compact: text(sectionText(markdown, 'Startup Brief') || item.episode_short),
    summary: text(sectionText(markdown, 'Compact Summary') || item.episode_short),
    full: markdown,
  };
}
