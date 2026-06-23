import { useEffect, useState } from 'react';
import { t } from '../../app/i18n';
import type { MonitorLanguage } from '../../app/monitorUi';
import { getInstallationCheck, getIntegrations, getMonitorStatus } from '../../shared/api/monitor';
import type { InstallationCheckResponse, IntegrationStatusItem, IntegrationSummary, MonitorStatus } from '../../shared/api/types';
import './integrations-panel.css';

export type IntegrationsPanelProps = {
  language?: MonitorLanguage;
  showHeading?: boolean;
};

function text(value: unknown, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function readinessTone(status: string | undefined) {
  if (status === 'ready') return 'good';
  if (status === 'installed') return 'warn';
  if (status === 'not_required_local') return 'good';
  return 'bad';
}

export function IntegrationsPanel({ language = 'en', showHeading = true }: IntegrationsPanelProps) {
  const [payload, setPayload] = useState<IntegrationSummary | undefined>();
  const [installation, setInstallation] = useState<InstallationCheckResponse | undefined>();
  const [status, setStatus] = useState<MonitorStatus | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  async function load(cancelled = false) {
    if (!cancelled) setLoading(true);
    try {
      const [integrations, installationCheck, monitorStatus] = await Promise.all([
        getIntegrations(),
        getInstallationCheck(),
        getMonitorStatus(),
      ]);
      if (!cancelled) {
        setPayload(integrations);
        setInstallation(installationCheck);
        setStatus(monitorStatus);
        setError('');
      }
    } catch (err: unknown) {
      if (!cancelled) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (!cancelled) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    let cancelled = false;
    void load(cancelled);
    return () => {
      cancelled = true;
    };
  }, []);

  const items: IntegrationStatusItem[] = payload?.items ?? [];
  const root = text(status?.root, '/Users/frankrichter/projects/agent-memory');
  const wrapperReadyCount = items.filter((item) => Boolean(item.wrapper_ready)).length;
  const manageableHooks = items.filter((item) => Boolean(item.hooks_manageable));
  const hooksEnabledCount = manageableHooks.filter((item) => Boolean(item.hooks_enabled)).length;
  const hookQueue = status?.hook_queue;
  const hookWorker = hookQueue?.worker;
  const hookQueueReasons = Array.isArray(hookQueue?.degradation_reasons) ? hookQueue.degradation_reasons : [];

  function normalizeCommandText(command: string) {
    const prefix = `cd '${root.replaceAll("'", `'\"'\"'`)}' && `;
    if (command.startsWith(prefix)) {
      const tail = command.slice(prefix.length);
      if (tail.startsWith('./')) return `${root}/${tail.slice(2)}`;
      return tail;
    }
    return command;
  }

  function absoluteCommand(command: string) {
    if (!command) return '';
    if (command.startsWith('./')) return `${root}/${command.slice(2)}`;
    return command;
  }

  function fallbackWrapperCommand(item: IntegrationStatusItem) {
    if (item.wrapper_command) return text(item.wrapper_command);
    if (item.client === 'codex') return './scripts/codex-ace';
    if (item.client === 'claude') return './scripts/claude-ace';
    if (item.client === 'antigravity') return './scripts/agy-ace';
    if (item.client === 'gemini') return './scripts/gemini-ace';
    if (item.client === 'opencode') return './scripts/opencode-ace';
    return '';
  }

  function fallbackUsageMode(item: IntegrationStatusItem) {
    if (text(item.usage_mode, '') !== '') return text(item.usage_mode);
    return item.client === 'cursor' ? 'project_activation' : 'wrapper';
  }

  function usageModeLabel(item: IntegrationStatusItem) {
    const mode = fallbackUsageMode(item);
    if (mode === 'wrapper') return t(language, 'integrations.usage.wrapper');
    if (mode === 'project_activation') return t(language, 'integrations.usage.projectActivation');
    return mode;
  }

  function ingressLabel(value: unknown) {
    const mode = text(value, '');
    if (mode === 'shell_hook') return t(language, 'integrations.ingress.shellHook');
    if (mode === 'plugin_bridge') return t(language, 'integrations.ingress.pluginBridge');
    return text(value);
  }

  function authLabel(value: unknown) {
    const mode = text(value, '');
    if (mode === 'unknown') return t(language, 'integrations.auth.unknown');
    if (mode === 'runtime_managed') return t(language, 'integrations.auth.runtimeManaged');
    if (mode === 'not_required_local') return t(language, 'integrations.auth.notRequiredLocal');
    return text(value);
  }

  function readinessLabel(item: IntegrationStatusItem) {
    const globalAvailable = Boolean(item.global_command_available);
    const wrapperClient = fallbackUsageMode(item) === 'wrapper';
    if (item.ready && wrapperClient && globalAvailable) return t(language, 'integrations.readiness.globallyReady');
    if (item.ready && wrapperClient) return t(language, 'integrations.readiness.readyInRoot');
    if (item.ready) return t(language, 'integrations.readiness.ready');
    const statusText = text(item.readiness_status, '');
    if (statusText === 'installed') return t(language, 'integrations.readiness.installed');
    if (statusText === 'missing_executable') return t(language, 'integrations.readiness.missingExecutable');
    if (statusText === 'model_missing') return t(language, 'integrations.readiness.modelMissing');
    if (statusText === 'ready') return t(language, 'integrations.readiness.ready');
    return statusText;
  }

  function fallbackUsageHint(item: IntegrationStatusItem) {
    if (text(item.usage_hint, '') !== '') {
      return text(item.usage_hint);
    }
    if (text(item.wrapper_state, '') === 'blocked_by_hooks') {
      return t(language, 'integrations.usageHint.blockedByHooks');
    }
    if (item.client === 'cursor') {
      return t(language, 'integrations.usageHint.cursor');
    }
    if (item.client === 'opencode') {
      if (item.global_command_available) {
        return t(language, 'integrations.usageHint.opencode.global');
      }
      return t(language, 'integrations.usageHint.opencode.root');
    }
    if (item.client === 'antigravity') {
      if (item.global_command_available) {
        return t(language, 'integrations.usageHint.antigravity.global');
      }
      return t(language, 'integrations.usageHint.antigravity.root');
    }
    if (item.client === 'gemini') {
      if (item.global_command_available) {
        return t(language, 'integrations.usageHint.gemini.global');
      }
      return t(language, 'integrations.usageHint.gemini.root');
    }
    if (item.client === 'claude') {
      if (item.global_command_available) {
        return t(language, 'integrations.usageHint.claude.global');
      }
      return t(language, 'integrations.usageHint.claude.root');
    }
    if (item.client === 'codex') {
      if (item.global_command_available) {
        return t(language, 'integrations.usageHint.codex.global');
      }
      return t(language, 'integrations.usageHint.codex.root');
    }
    return t(language, 'integrations.usageHint.default');
  }

  function fallbackTerminalCommand(item: IntegrationStatusItem) {
    if (item.terminal_command) return normalizeCommandText(text(item.terminal_command));
    const wrapper = fallbackWrapperCommand(item);
    return wrapper ? absoluteCommand(wrapper) : '';
  }

  function fallbackActivationCommand(item: IntegrationStatusItem) {
    if (item.activation_command) return normalizeCommandText(text(item.activation_command));
    if (item.client === 'cursor') return `${absoluteCommand('./scripts/agent-context-engine')} cursor-enable --target <project-path>`;
    if (item.client === 'antigravity') return `${absoluteCommand('./scripts/agent-context-engine')} antigravity-enable`;
    if (item.client === 'gemini') return `${absoluteCommand('./scripts/agent-context-engine')} gemini-enable`;
    if (item.client === 'opencode') return `${absoluteCommand('./scripts/agent-context-engine')} opencode-enable`;
    return '';
  }

  function fallbackGlobalActivationCommand(item: IntegrationStatusItem) {
    if (text(item.global_activation_command, '') !== '') return normalizeCommandText(text(item.global_activation_command));
    if (fallbackUsageMode(item) !== 'wrapper') return '';
    const command = globalWrapperCommand(item);
    if (!command || item.global_command_available) return '';
    return `${absoluteCommand('./scripts/agent-context-engine')} global-wrapper-enable ${command}`;
  }

  function fallbackGlobalStatusCommand(item: IntegrationStatusItem) {
    if (text(item.global_status_command, '') !== '') return normalizeCommandText(text(item.global_status_command));
    if (fallbackUsageMode(item) !== 'wrapper') return '';
    return `${absoluteCommand('./scripts/agent-context-engine')} global-wrapper-status`;
  }

  function fallbackHookDisableCommand(item: IntegrationStatusItem, projectPath?: string) {
    const client = text(item.client, '');
    return `hooks-disable --runner ${client}`;
  }

  function fallbackHookEnableCommand(item: IntegrationStatusItem, projectPath?: string) {
    const client = text(item.client, '');
    const target = text(projectPath, '');
    if (client === 'cursor') {
      if (!target) return `${absoluteCommand('./scripts/agent-context-engine')} cursor-enable --target <project-path>`;
      return `${absoluteCommand('./scripts/agent-context-engine')} cursor-enable --target ${target}`;
    }
    if (client === 'antigravity') {
      return `${absoluteCommand('./scripts/agent-context-engine')} antigravity-enable`;
    }
    if (client === 'gemini') {
      return `${absoluteCommand('./scripts/agent-context-engine')} gemini-enable`;
    }
    if (client === 'opencode') {
      return `${absoluteCommand('./scripts/agent-context-engine')} opencode-enable`;
    }
    const command = `${absoluteCommand('./scripts/agent-context-engine')} integration-hooks --client ${client} --action enable`;
    if (target) return `${command} --target ${target}`;
    return command;
  }

  function fallbackWorkingRoot(item: IntegrationStatusItem) {
    if (text(item.working_root, '') !== '') return text(item.working_root);
    return item.client === 'cursor' || fallbackWrapperCommand(item) ? root : t(language, 'integrations.root.projectSpecific');
  }

  function bindingTargetLabel(item: IntegrationStatusItem) {
    const targetRoot = text(item.hook_binding_target_root, '');
    const targetInstance = text(item.hook_binding_target_instance, '');
    if (!targetRoot) return '-';
    if (!targetInstance) return targetRoot;
    return `${targetRoot} (${targetInstance})`;
  }

  function globalWrapperLabel(item: IntegrationStatusItem) {
    if (item.client === 'cursor') return t(language, 'integrations.globalWrapper.notApplicable');
    if (item.global_command_available) return t(language, 'common.yes');
    return t(language, 'common.no');
  }

  function preparedLabel(item: IntegrationStatusItem) {
    return item.prepared ? t(language, 'integrations.prepared.prepared') : t(language, 'integrations.prepared.notPrepared');
  }

  function wrapperStateLabel(item: IntegrationStatusItem) {
    const value = text(item.wrapper_state, '');
    if (value === 'global_active') return t(language, 'integrations.wrapperState.globalActive');
    if (value === 'root_active') return t(language, 'integrations.wrapperState.rootActive');
    if (value === 'blocked_by_hooks') return t(language, 'integrations.wrapperState.blockedByHooks');
    if (value === 'runner_missing') return t(language, 'integrations.wrapperState.runnerMissing');
    if (value === 'project_activation') return t(language, 'integrations.wrapperState.projectActivation');
    if (value === 'not_prepared') return t(language, 'integrations.wrapperState.notPrepared');
    return text(item.wrapper_state, '-');
  }

  function wrapperStateHint(item: IntegrationStatusItem) {
    const value = text(item.wrapper_state, '');
    if (value === 'global_active') {
      return t(language, 'integrations.wrapperHint.globalActive');
    }
    if (value === 'root_active') {
      return t(language, 'integrations.wrapperHint.rootActive');
    }
    if (value === 'blocked_by_hooks') {
      return t(language, 'integrations.wrapperHint.blockedByHooks');
    }
    if (value === 'runner_missing') {
      return t(language, 'integrations.wrapperHint.runnerMissing');
    }
    if (value === 'project_activation') {
      return t(language, 'integrations.wrapperHint.projectActivation');
    }
    return t(language, 'integrations.wrapperHint.default');
  }

  function hooksLabel(item: IntegrationStatusItem) {
    const value = text(item.hooks_state, '');
    if (value === 'enabled') return t(language, 'integrations.hooks.enabled');
    if (value === 'disabled') return t(language, 'integrations.hooks.disabled');
    if (value === 'disabled_by_control_plane') return t(language, 'integrations.hooks.disabledByControlPlane');
    if (value === 'inactive_missing_binding') return t(language, 'integrations.hooks.inactiveMissingBinding');
    if (value === 'inactive_invalid_binding') return t(language, 'integrations.hooks.inactiveInvalidBinding');
    if (value === 'inactive_missing_target') return t(language, 'integrations.hooks.inactiveMissingTarget');
    if (value === 'inactive_missing_cli') return t(language, 'integrations.hooks.inactiveMissingCli');
    if (value === 'partial') return t(language, 'integrations.hooks.partial');
    if (value === 'configured_without_agent_memory') return t(language, 'integrations.hooks.configuredWithoutAgentMemory');
    if (value === 'not_supported') return t(language, 'integrations.hooks.notSupported');
    if (value === 'not_prepared') return t(language, 'integrations.hooks.notPrepared');
    return text(item.hooks_state, '-');
  }

  function projectHooksLabel(value: unknown) {
    const mode = text(value, '');
    if (mode === 'enabled') return t(language, 'integrations.hooks.enabled');
    if (mode === 'disabled') return t(language, 'integrations.hooks.disabled');
    if (mode === 'partial') return t(language, 'integrations.hooks.partial');
    if (mode === 'configured_without_agent_memory') return t(language, 'integrations.projectHooks.configuredWithoutAgentMemory');
    if (mode === 'not_prepared') return t(language, 'integrations.hooks.notPrepared');
    if (mode === 'project_missing') return t(language, 'integrations.projectHooks.projectMissing');
    return text(value, '-');
  }

  function canManageProjectHooks(item: IntegrationStatusItem) {
    return ['cursor'].includes(String(item.client));
  }

  function canShowProjectActivation(item: IntegrationStatusItem) {
    return ['cursor'].includes(String(item.client));
  }

  function globalWrapperCommand(item: IntegrationStatusItem) {
    if (item.client === 'antigravity') return 'agy-ace';
    return text(item.global_command_name, fallbackUsageMode(item) === 'wrapper' ? text(fallbackWrapperCommand(item)).replace('./scripts/', '') : '');
  }

  function globalDirectCommand(item: IntegrationStatusItem) {
    if (fallbackUsageMode(item) !== 'wrapper') return '';
    if (text(item.wrapper_state, '') !== 'global_active') return '';
    return globalWrapperCommand(item);
  }

  function projectActivationSummary(item: IntegrationStatusItem) {
    const count = Number(item.activated_project_count || 0);
    return t(language, 'integrations.projects.summary', { count });
  }

  function projectHookTotals(item: IntegrationStatusItem) {
    const projects = Array.isArray(item.activated_projects) ? item.activated_projects : [];
    const total = projects.length;
    const enabled = projects.filter((project) => project?.hooks_state === 'enabled').length;
    return { total, enabled };
  }

  function projectHookBadge(item: IntegrationStatusItem) {
    const { total, enabled } = projectHookTotals(item);
    return t(language, 'integrations.projects.badge', { enabled, total });
  }

  function workflowTone(ready: unknown) {
    return ready ? 'good' : 'warn';
  }

  function actionTone(command: string) {
    if (command.includes('repair-installation --apply')) return 'warn';
    if (command.includes(' login')) return 'warn';
    return 'good';
  }

  function renderActivatedProjects(item: IntegrationStatusItem) {
    if (Array.isArray(item.activated_projects) && item.activated_projects.length) {
      return (
        <details className="integrations-projects">
          <summary>{projectActivationSummary(item)}</summary>
          <div className="integrations-project-list">
            {item.activated_projects.map((project, index) => (
              <article className="integrations-project-card" key={`${text(project.path, 'project')}-${index}`}>
                <strong>{text(project.name, text(project.path, 'project'))}</strong>
                <small>{text(project.path)}</small>
                <small>{t(language, 'integrations.subtitle.hooks')}: {projectHooksLabel(project.hooks_state)}</small>
                <small>{t(language, 'integrations.meta.config')}: {text(project.hook_config_path)}</small>
                {Array.isArray(project.active_hook_events) && project.active_hook_events.length ? (
                  <code className="integrations-command">{project.active_hook_events.join(', ')}</code>
                ) : null}
                {canManageProjectHooks(item) ? (
                  <>
                    <p className="integrations-hint">{t(language, 'integrations.hooksCommand.protected')}</p>
                    <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.agentEnable')}</p>
                    <code className="integrations-command">{fallbackHookEnableCommand(item, text(project.path, ''))}</code>
                    <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.userDisable')}</p>
                    <code className="integrations-command">{fallbackHookDisableCommand(item, text(project.path, ''))}</code>
                  </>
                ) : null}
              </article>
            ))}
          </div>
        </details>
      );
    }
    if (canShowProjectActivation(item)) {
      return (
        <p className="integrations-hint">
          {t(language, 'integrations.projects.noneRecorded')}
        </p>
      );
    }
    return null;
  }

  function historyActionLabel(value: unknown) {
    const action = text(value, '');
    if (action === 'hooks_enable') return t(language, 'integrations.history.hooksEnable');
    if (action === 'hooks_disable') return t(language, 'integrations.history.hooksDisable');
    if (action === 'project_enabled') return t(language, 'integrations.history.projectEnabled');
    if (action === 'project_disabled') return t(language, 'integrations.history.projectDisabled');
    if (action === 'global_wrapper_enabled') return t(language, 'integrations.history.globalWrapperEnabled');
    if (action === 'global_wrapper_disabled') return t(language, 'integrations.history.globalWrapperDisabled');
    return action || '-';
  }

  function hooksHint(item: IntegrationStatusItem) {
    const value = text(item.hooks_state, '');
    if (value === 'enabled') {
      return t(language, 'integrations.hooksHint.enabled');
    }
    if (value === 'disabled') {
      return t(language, 'integrations.hooksHint.disabled');
    }
    if (value === 'disabled_by_control_plane') {
      return t(language, 'integrations.hooksHint.disabledByControlPlane');
    }
    if (value === 'inactive_missing_binding') {
      return t(language, 'integrations.hooksHint.inactiveMissingBinding');
    }
    if (value === 'inactive_invalid_binding') {
      return t(language, 'integrations.hooksHint.inactiveInvalidBinding');
    }
    if (value === 'inactive_missing_target') {
      return t(language, 'integrations.hooksHint.inactiveMissingTarget');
    }
    if (value === 'inactive_missing_cli') {
      return t(language, 'integrations.hooksHint.inactiveMissingCli');
    }
    if (value === 'partial') {
      return t(language, 'integrations.hooksHint.partial');
    }
    if (value === 'configured_without_agent_memory') {
      return t(language, 'integrations.hooksHint.configuredWithoutAgentMemory');
    }
    if (value === 'not_supported') {
      return t(language, 'integrations.hooksHint.notSupported');
    }
    return t(language, 'integrations.hooksHint.default');
  }

  function renderInstallationSection() {
    if (!installation) return null;
    const findings = Array.isArray(installation.findings) ? installation.findings : [];
    const workflowChecks = Array.isArray(installation.workflow_checks) ? installation.workflow_checks : [];
    const agentActions = Array.isArray(installation.agent_actions) ? installation.agent_actions : [];
    const manualActions = Array.isArray(installation.manual_actions) ? installation.manual_actions : [];
    return (
      <article className="integrations-card integrations-check-card">
        <div className="integrations-card-head">
          <div>
            <strong>{t(language, 'integrations.installation.title')}</strong>
            <small>{t(language, 'integrations.installation.subtitle')}</small>
          </div>
          <span className={`integrations-badge integrations-badge-${findings.length ? 'warn' : 'good'}`}>
            {findings.length
              ? t(language, 'integrations.installation.findings', { count: findings.length })
              : t(language, 'integrations.installation.ok')}
          </span>
        </div>
        <dl className="integrations-meta integrations-meta-runtime">
          <div className="integrations-meta-full">
            <dt>{t(language, 'integrations.installation.profile')}</dt>
            <dd>{text(installation.profile_path)}</dd>
          </div>
        </dl>
        <div className="integrations-check-list">
          {workflowChecks.map((check, index) => (
            <article className="integrations-project-card" key={`${text(check.key, 'workflow')}-${index}`}>
              <strong>{text(check.label, text(check.key, 'workflow'))}</strong>
              <small>{text(check.runner)} · {text(check.status, check.ready ? 'ready' : 'pending')}</small>
              {text(check.message, '') ? <p className="integrations-hint">{text(check.message, '')}</p> : null}
              <span className={`integrations-badge integrations-badge-${workflowTone(check.ready)}`}>
                {check.ready ? t(language, 'integrations.installation.workflowReady') : t(language, 'integrations.installation.workflowBlocked')}
              </span>
            </article>
          ))}
        </div>
        {findings.length ? (
          <div className="integrations-check-section">
            <p className="integrations-subtitle">{t(language, 'integrations.installation.findingsTitle')}</p>
            <div className="integrations-check-list">
              {findings.map((finding, index) => (
                <article className="integrations-project-card" key={`${text(finding.code, 'finding')}-${index}`}>
                  <strong>{text(finding.severity, 'warn')}</strong>
                  <p className="integrations-hint">{text(finding.message)}</p>
                </article>
              ))}
            </div>
          </div>
        ) : null}
        {agentActions.length ? (
          <div className="integrations-check-section">
            <p className="integrations-subtitle">{t(language, 'integrations.installation.agentActions')}</p>
            <div className="integrations-check-list">
              {agentActions.map((action, index) => (
                <article className="integrations-project-card" key={`${text(action.code, 'agent')}-${index}`}>
                  <strong>{text(action.message)}</strong>
                  <small>{t(language, 'integrations.installation.agentOnly')}</small>
                  <code className={`integrations-command integrations-command-tone-${actionTone(text(action.command, ''))}`}>{text(action.command)}</code>
                </article>
              ))}
            </div>
          </div>
        ) : null}
        {manualActions.length ? (
          <div className="integrations-check-section">
            <p className="integrations-subtitle">{t(language, 'integrations.installation.manualActions')}</p>
            <div className="integrations-check-list">
              {manualActions.map((action, index) => (
                <article className="integrations-project-card" key={`${text(action.code, 'manual')}-${index}`}>
                  <strong>{text(action.message)}</strong>
                  <code className={`integrations-command integrations-command-tone-${actionTone(text(action.command, ''))}`}>{text(action.command)}</code>
                </article>
              ))}
            </div>
          </div>
        ) : null}
      </article>
    );
  }

  function cardTone(item: IntegrationStatusItem) {
    const wrapperState = text(item.wrapper_state, '');
    const hooksState = text(item.hooks_state, '');
    if (wrapperState === 'project_activation') {
      const { total, enabled } = projectHookTotals(item);
      if (total > 0 && enabled === total) return 'good';
      if (total > 0 && enabled < total) return 'warn';
      return item.ready ? 'good' : readinessTone(text(item.readiness_status, ''));
    }
    if (
      wrapperState === 'blocked_by_hooks'
      || hooksState === 'disabled'
      || hooksState === 'disabled_by_control_plane'
      || hooksState === 'partial'
      || hooksState === 'inactive_missing_binding'
      || hooksState === 'inactive_invalid_binding'
      || hooksState === 'inactive_missing_target'
      || hooksState === 'inactive_missing_cli'
    ) return 'warn';
    if (item.wrapper_ready || item.ready) return 'good';
    return readinessTone(text(item.readiness_status, ''));
  }

  function cardLabel(item: IntegrationStatusItem) {
    const wrapperState = text(item.wrapper_state, '');
    const hooksState = text(item.hooks_state, '');
    if (wrapperState === 'project_activation') return projectHookBadge(item);
    if (wrapperState === 'blocked_by_hooks') return t(language, 'integrations.wrapperState.blockedByHooks');
    if (hooksState === 'disabled') return t(language, 'integrations.card.hooksDisabled');
    if (hooksState === 'disabled_by_control_plane') return t(language, 'integrations.card.hooksDisabledByControlPlane');
    if (hooksState === 'inactive_missing_binding') return t(language, 'integrations.card.hooksInactiveMissingBinding');
    if (hooksState === 'inactive_invalid_binding') return t(language, 'integrations.card.hooksInactiveInvalidBinding');
    if (hooksState === 'inactive_missing_target') return t(language, 'integrations.card.hooksInactiveMissingTarget');
    if (hooksState === 'inactive_missing_cli') return t(language, 'integrations.card.hooksInactiveMissingCli');
    if (hooksState === 'partial') return t(language, 'integrations.card.hooksPartial');
    if (wrapperState === 'global_active') return t(language, 'integrations.wrapperState.globalActive');
    if (wrapperState === 'root_active') return t(language, 'integrations.wrapperState.rootActive');
    if (wrapperState === 'project_activation') return t(language, 'integrations.card.projectBased');
    if (item.ready) return t(language, 'integrations.card.runtimeReady');
    return readinessLabel(item);
  }

  if (loading && !payload && !error) {
    return (
      <section className="integrations-panel" aria-busy="true">
        {showHeading ? (
          <div className="panel-heading">
            <div />
            <span>{t(language, 'integrations.loading')}</span>
          </div>
        ) : null}
        <div className="integrations-loading-grid">
          {Array.from({ length: 5 }).map((_, index) => (
            <article className="integrations-card integrations-card-loading" key={index}>
              <div className="integrations-loading-line integrations-loading-line-title" />
              <div className="integrations-loading-line integrations-loading-line-badge" />
              <div className="integrations-loading-block">
                <div className="integrations-loading-line" />
                <div className="integrations-loading-line" />
                <div className="integrations-loading-line integrations-loading-line-short" />
              </div>
              <div className="integrations-loading-block">
                <div className="integrations-loading-line" />
                <div className="integrations-loading-line integrations-loading-line-long" />
                <div className="integrations-loading-line integrations-loading-line-short" />
              </div>
            </article>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="integrations-panel">
      {showHeading ? (
        <div className="panel-heading">
          <div />
          <span>
            {text(payload?.ready, '0')}/{text(payload?.total, '0')} {t(language, 'integrations.summary.runtimeReady')} · {wrapperReadyCount}/{items.length} {t(language, 'integrations.summary.wrapperActive')} · {hooksEnabledCount}/{manageableHooks.length} {t(language, 'integrations.summary.hooksEnabled')}
          </span>
        </div>
      ) : null}
      {error ? <p className="panel-error">{error}</p> : null}
      {!loading ? (
        <p className="integrations-hint">
          {`hook queue ${text(hookQueue?.queued_events, '0')} · dead letters ${text(hookQueue?.failed_events, '0')} · ${hookWorker?.running ? 'worker active' : 'worker idle'} · heartbeat ${text(hookWorker?.heartbeat_at, '-')}${hookQueue?.degraded ? ` · degraded ${hookQueueReasons.join(', ')}` : ''}`}
        </p>
      ) : null}
      <div className="integrations-grid">
        {renderInstallationSection()}
        {items.map((item) => (
          <article className="integrations-card" key={item.client}>
            <div className="integrations-card-head">
              <div>
                <strong>{item.client === 'opencode' ? 'Opencode' : text(item.label, item.client)}</strong>
                <small>{ingressLabel(item.ingress_transport)}</small>
              </div>
              <span className={`integrations-badge integrations-badge-${cardTone(item)}`}>
                {cardLabel(item)}
              </span>
            </div>
              {canShowProjectActivation(item) ? renderActivatedProjects(item) : null}
            <dl className="integrations-meta integrations-meta-runtime">
              <div>
                <dt>{t(language, 'integrations.meta.runner')}</dt>
                <dd>{text(item.runner)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.provider')}</dt>
                <dd>{text(item.provider)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.defaultModel')}</dt>
                <dd>{text(item.selected_model)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.miniModel')}</dt>
                <dd>{text(item.selected_small_model)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.recommendation')}</dt>
                <dd>{text(item.recommended_small_model || item.recommended_model)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.authentication')}</dt>
                <dd>{authLabel(item.auth_status)}</dd>
              </div>
              <div>
                <dt>{t(language, 'integrations.meta.usage')}</dt>
                <dd>{usageModeLabel(item)}</dd>
              </div>
            </dl>
            <div className="integrations-usage">
              <p className="integrations-subtitle">{t(language, 'integrations.subtitle.wrapperAndUsage')}</p>
              <dl className="integrations-meta integrations-meta-block">
                <div>
                  <dt>{t(language, 'integrations.meta.wrapper')}</dt>
                  <dd>{text(fallbackWrapperCommand(item), t(language, 'common.none'))}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.globalCommand')}</dt>
                  <dd>{text(globalWrapperCommand(item), t(language, 'common.none'))}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.linkedInPath')}</dt>
                  <dd>{globalWrapperLabel(item)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.prepared')}</dt>
                  <dd>{preparedLabel(item)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.wrapperActive')}</dt>
                  <dd>{wrapperStateLabel(item)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.root')}</dt>
                  <dd>{fallbackWorkingRoot(item)}</dd>
                </div>
              </dl>
              <p className="integrations-hint">{wrapperStateHint(item)}</p>
              {globalDirectCommand(item) ? (
                <div className="integrations-direct-command">
                  <p className="integrations-direct-command-label">
                    {t(language, 'integrations.directTerminal')}
                  </p>
                  <code className="integrations-command integrations-command-inline">{globalDirectCommand(item)}</code>
                </div>
              ) : null}
              <p>{fallbackUsageHint(item)}</p>
              {fallbackTerminalCommand(item) ? (
                <code className="integrations-command">{fallbackTerminalCommand(item)}</code>
              ) : null}
              {fallbackGlobalActivationCommand(item) ? (
                <code className="integrations-command">{fallbackGlobalActivationCommand(item)}</code>
              ) : null}
              {fallbackGlobalStatusCommand(item) && !item.global_command_available ? (
                <code className="integrations-command">{fallbackGlobalStatusCommand(item)}</code>
              ) : null}
              {fallbackActivationCommand(item) ? (
                <code className="integrations-command">{fallbackActivationCommand(item)}</code>
              ) : null}
            </div>
            <div className="integrations-hooks">
              <p className="integrations-subtitle">{t(language, 'integrations.subtitle.hooks')}</p>
              <dl className="integrations-meta integrations-meta-block">
                <div>
                  <dt>{t(language, 'integrations.meta.status')}</dt>
                  <dd>{hooksLabel(item)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.activeEvents')}</dt>
                  <dd>{Array.isArray(item.active_hook_events) ? String(item.active_hook_events.length) : '-'}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.controlPlane')}</dt>
                  <dd>{text(item.hooks_control_state, '-')}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.lastChangedBy')}</dt>
                  <dd>{text(item.hooks_control_disabled_by || item.hooks_control_source)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.changedAt')}</dt>
                  <dd>{text(item.hooks_control_disabled_at)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.bindingState')}</dt>
                  <dd>{text(item.hook_binding_state, '-')}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.bindingTarget')}</dt>
                  <dd>{bindingTargetLabel(item)}</dd>
                </div>
                <div>
                  <dt>{t(language, 'integrations.meta.bindingError')}</dt>
                  <dd>{text(item.hook_binding_last_error)}</dd>
                </div>
                <div className="integrations-meta-full">
                  <dt>{t(language, 'integrations.meta.config')}</dt>
                  <dd>{text(item.hook_config_path)}</dd>
                </div>
                <div className="integrations-meta-full">
                  <dt>{t(language, 'integrations.meta.bindingFile')}</dt>
                  <dd>{text(item.hook_binding_path)}</dd>
                </div>
                <div className="integrations-meta-full">
                  <dt>{t(language, 'integrations.meta.disabledFile')}</dt>
                  <dd>{text(item.hook_disabled_path)}</dd>
                </div>
              </dl>
              <p className="integrations-hint">{hooksHint(item)}</p>
              {Array.isArray(item.active_hook_events) && item.active_hook_events.length ? (
                <code className="integrations-command">{item.active_hook_events.join(', ')}</code>
              ) : null}
              <p className="integrations-hint">{t(language, 'integrations.hooksCommand.protected')}</p>
              {item.hooks_manageable ? (
                <>
                  <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.agentEnable')}</p>
                  <code className="integrations-command">{fallbackHookEnableCommand(item)}</code>
                </>
              ) : null}
              <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.userDisable')}</p>
              <code className="integrations-command">{fallbackHookDisableCommand(item)}</code>
              <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.userEnable')}</p>
              <code className="integrations-command">{`hooks-enable --runner ${text(item.client, '')}`}</code>
              <p className="integrations-direct-command-label">{t(language, 'integrations.hooksCommand.userStatus')}</p>
              <code className="integrations-command">hooks-status</code>
              {canShowProjectActivation(item) ? null : renderActivatedProjects(item)}
              {Array.isArray(item.history) && item.history.length ? (
                <details className="integrations-projects">
                  <summary>{t(language, 'integrations.subtitle.history')}</summary>
                  <div className="integrations-project-list">
                    {item.history.map((entry, index) => (
                      <article className="integrations-project-card" key={`${text(entry.timestamp, 'history')}-${index}`}>
                        <strong>{historyActionLabel(entry.action)}</strong>
                        <small>{text(entry.timestamp)}</small>
                        <small>{t(language, 'integrations.history.source')}: {text(entry.source)}</small>
                        <small>{t(language, 'integrations.history.actor')}: {text(entry.actor)}</small>
                        {text(entry.target_path, '') ? <small>{t(language, 'integrations.history.target')}: {text(entry.target_path)}</small> : null}
                      </article>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
            <div className="integrations-models">
              <p className="integrations-subtitle">{t(language, 'integrations.subtitle.discoveredModels')}</p>
              {(item.models ?? []).length ? (
                <ul>
                  {(item.models ?? []).slice(0, 8).map((model) => (
                    <li key={model.id}>{model.id}</li>
                  ))}
                </ul>
              ) : (
                <p className="empty-copy">{t(language, 'integrations.models.none')}</p>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
