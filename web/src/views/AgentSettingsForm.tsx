import * as uiMessages from "../messages";
import AccountSelection, {
  accountSettings,
  deviceAccount,
  supportsAccounts,
} from "../AccountSelection";
import AgentConnection, { NEW_SSH_CONNECTION } from "../AgentConnection";
import ProviderSelect from "../ProviderSelect";
import WorkspaceDirectory from "../WorkspaceDirectory";
import type { PermissionMode } from "../types";
import { Icon } from "../ui";
import type { WorkspaceView } from "./WorkspaceController";
export default function AgentSettingsForm({
  view,
}: {
  view: Pick<
    WorkspaceView,
    | "editingAgent"
    | "t"
    | "setAgentForm"
    | "busy"
    | "demo"
    | "environment"
    | "mutate"
    | "editingAgentID"
    | "agentName"
    | "role"
    | "model"
    | "effort"
    | "runTimeout"
    | "permissionMode"
    | "provider"
    | "state"
    | "accountDraft"
    | "sessions"
    | "changingEnvironment"
    | "agentProject"
    | "workspace"
    | "draftTarget"
    | "setAgentID"
    | "setAgentName"
    | "setRole"
    | "setEditingAgentID"
    | "connectionDraft"
    | "setConnectionDraft"
    | "runtimeEnabled"
    | "setEnvironment"
    | "setAccountDraft"
    | "setWorkspace"
    | "setModel"
    | "setEffort"
    | "setRunTimeout"
    | "projectDirectory"
    | "token"
    | "connectionReady"
    | "setProvider"
    | "discovery"
    | "models"
    | "selectedProject"
    | "catalogLoading"
    | "catalogError"
    | "setPermissionMode"
    | "selectedAvailable"
  >;
}) {
  const {
    editingAgent,
    t,
    setAgentForm,
    busy,
    demo,
    environment,
    mutate,
    editingAgentID,
    agentName,
    role,
    model,
    effort,
    runTimeout,
    permissionMode,
    provider,
    state,
    accountDraft,
    sessions,
    changingEnvironment,
    agentProject,
    workspace,
    draftTarget,
    setAgentID,
    setAgentName,
    setRole,
    setEditingAgentID,
    connectionDraft,
    setConnectionDraft,
    runtimeEnabled,
    setEnvironment,
    setAccountDraft,
    setWorkspace,
    setModel,
    setEffort,
    setRunTimeout,
    projectDirectory,
    token,
    connectionReady,
    setProvider,
    discovery,
    models,
    selectedProject,
    catalogLoading,
    catalogError,
    setPermissionMode,
    selectedAvailable,
  } = view;
  return (
    <section className="panel inset-form" id="agent-form">
      <div className="panel-heading">
        <h2>
          {editingAgent
            ? t(
                `编辑 Agent · ${editingAgent.name}`,
                `Edit agent · ${editingAgent.name}`,
              )
            : t(...uiMessages.agentsettingsform_add_an_agent_ffe43e)}
        </h2>
        <button
          className="icon-button"
          onClick={() => setAgentForm(false)}
          aria-label={
            editingAgent
              ? t(...uiMessages.agentsettingsform_cancel_editing_agent_7b7fe0)
              : t(...uiMessages.agentsettingsform_cancel_adding_agent_fe4fef)
          }
          disabled={busy && !demo}
        >
          <Icon name="close" />
        </button>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (environment === NEW_SSH_CONNECTION) return;
          await mutate(
            editingAgentID
              ? `/api/agents/${encodeURIComponent(editingAgentID)}`
              : "/api/agents",
            editingAgentID
              ? {
                  name: agentName.trim(),
                  role: role.trim(),
                  model: model || null,
                  effort: effort || null,
                  run_timeout: runTimeout ? Number(runTimeout) * 60 : null,
                  permission_mode: permissionMode,
                  ...(supportsAccounts(provider) &&
                  (state.accounts?.length ||
                    editingAgent?.account_policy ||
                    accountDraft.account_id ||
                    accountDraft.account_policy !== "manual")
                    ? accountSettings(accountDraft)
                    : {}),
                  environment_id: environment,
                  ...(!sessions.some((s) => s.agent_id === editingAgentID) ||
                  changingEnvironment
                    ? {
                        project_id: agentProject || null,
                        workspace: workspace || null,
                      }
                    : {}),
                }
              : {
                  project_id: agentProject || null,
                  workspace: workspace || null,
                  model: model || null,
                  effort: effort || null,
                  run_timeout: runTimeout ? Number(runTimeout) * 60 : null,
                  permission_mode: permissionMode,
                  ...(supportsAccounts(provider) &&
                  (state.accounts?.length ||
                    editingAgent?.account_policy ||
                    accountDraft.account_id ||
                    accountDraft.account_policy !== "manual")
                    ? accountSettings(accountDraft)
                    : {}),
                  name: agentName.trim(),
                  provider,
                  environment_id: environment,
                  role: role.trim(),
                },
            (result) => {
              draftTarget.current = null;
              setAgentID(result.id);
              setAgentName("");
              setRole("");
              setEditingAgentID(null);
              setAgentForm(false);
            },
          );
        }}
      >
        <label>
          {t(...uiMessages.agentsettingsform_name_66f61d)}
          <input
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            required
            maxLength={100}
            placeholder={t(
              ...uiMessages.agentsettingsform_choose_a_name_for_this_agent_11d949,
            )}
          />
        </label>
        <AgentConnection
          value={environment}
          draft={connectionDraft}
          onDraftChange={setConnectionDraft}
          locked={false}
          environments={state.environments ?? []}
          t={t}
          busy={busy && !demo}
          runtimeEnabled={runtimeEnabled && !demo}
          mutate={mutate}
          onChange={(id) => {
            setEnvironment(id);
            setAccountDraft(deviceAccount);
            const original =
              editingAgent && id === (editingAgent.environment_id ?? "local")
                ? editingAgent
                : undefined;
            setWorkspace(
              original?.workspace_is_default ? "" : (original?.workspace ?? ""),
            );
            setModel(original?.model ?? "");
            setEffort(original?.effort ?? "");
            setRunTimeout(
              original?.run_timeout ? String(original.run_timeout / 60) : "",
            );
          }}
        >
          <WorkspaceDirectory
            key={environment}
            value={projectDirectory ?? workspace}
            onChange={setWorkspace}
            environment={environment}
            token={token}
            t={t}
            disabled={
              !!projectDirectory ||
              (!!editingAgentID &&
                !changingEnvironment &&
                sessions.some((s) => s.agent_id === editingAgentID)) ||
              busy ||
              demo
            }
            browseEnabled={
              environment !== NEW_SSH_CONNECTION &&
              (environment === "local" || (connectionReady && runtimeEnabled))
            }
          />
        </AgentConnection>
        <div className="form-grid">
          <ProviderSelect
            value={provider}
            onChange={(value) => {
              setProvider(value);
              setAccountDraft(deviceAccount);
              setModel("");
              setEffort("");
            }}
            disabled={!!editingAgentID}
            availability={discovery.providers}
            loading={discovery.loading}
            failed={discovery.failed}
            onRefresh={discovery.refresh}
            t={t}
          />
          <label>
            {t(...uiMessages.agentsettingsform_model_3fedbe)}
            <select
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                setEffort("");
              }}
            >
              <option value="">
                {t(...uiMessages.agentsettingsform_cli_default_ce7700)}
              </option>
              {model && !models.some((m) => m.id === model) && (
                <option value={model}>{model}</option>
              )}
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name || m.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t(...uiMessages.agentsettingsform_reasoning_effort_15aa31)}
            <select
              value={effort}
              disabled={!model}
              onChange={(e) => setEffort(e.target.value)}
            >
              <option value="">
                {t(...uiMessages.agentsettingsform_auto_156a8d)}
              </option>
              {effort &&
                !models
                  .find((m) => m.id === model)
                  ?.efforts.includes(effort) && (
                  <option value={effort}>{effort}</option>
                )}
              {(models.find((m) => m.id === model)?.efforts ?? []).map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
          {editingAgent?.project_id && (
            <label>
              {t(...uiMessages.agentsettingsform_project_4eca63)}
              <input readOnly value={selectedProject?.name ?? ""} />
            </label>
          )}
          <label>
            {t(
              ...uiMessages.agentsettingsform_execution_time_limit_minutes_cb1fe0,
            )}
            <input
              type="number"
              min="1"
              max="1440"
              step="1"
              placeholder={t(
                ...uiMessages.agentsettingsform_default_15_minutes_1a6d54,
              )}
              value={runTimeout}
              onChange={(event) => setRunTimeout(event.target.value)}
            />
          </label>
        </div>
        <p className="settings-note">
          {catalogLoading
            ? t(
                ...uiMessages.agentsettingsform_reading_models_from_the_selected_environment_4b2826,
              )
            : catalogError
              ? t(
                  ...uiMessages.agentsettingsform_model_list_unavailable_keep_client_settings_a_ad58dd,
                )
              : t(
                  ...uiMessages.agentsettingsform_model_and_effort_set_agent_defaults_conversat_6fbf74,
                )}
        </p>
        <AccountSelection
          accounts={state.accounts ?? []}
          provider={provider}
          environment={environment}
          value={accountDraft}
          onChange={(value) => {
            setAccountDraft(value);
            setModel("");
            setEffort("");
          }}
          disabled={busy && !demo}
          t={t}
        />
        <label>
          {t(...uiMessages.agentsettingsform_access_permissions_f5df3f)}
          <select
            value={permissionMode}
            aria-describedby="agent-permission-description"
            disabled={
              !!editingAgentID &&
              !changingEnvironment &&
              state.runs?.some(
                (run) =>
                  run.agent_id === editingAgentID &&
                  ["queued", "running"].includes(run.status),
              )
            }
            onChange={(e) =>
              setPermissionMode(e.target.value as PermissionMode)
            }
          >
            <option value="ask">
              {t(
                ...uiMessages.agentsettingsform_ask_for_approval_default_f2e5d8,
              )}
            </option>
            <option value="full_access">
              {t(...uiMessages.agentsettingsform_full_access_45f478)}
            </option>
          </select>
        </label>
        {provider === "pi" && (
          <p className="settings-note">
            {t(
              ...uiMessages.agentsettingsform_pi_tool_execution_requires_full_access_select_7783bd,
            )}
          </p>
        )}
        <p className="form-hint" id="agent-permission-description">
          {permissionMode === "full_access"
            ? t(
                ...uiMessages.agentsettingsform_the_agent_can_read_and_write_files_run_comman_332692,
              )
            : t(
                ...uiMessages.agentsettingsform_operations_that_need_approval_wait_for_your_c_0a3242,
              )}
        </p>
        <label>
          {t(...uiMessages.agentsettingsform_role_optional_7d64f6)}
          <textarea
            value={role}
            onChange={(e) => setRole(e.target.value)}
            rows={2}
            maxLength={4000}
            placeholder={t(
              ...uiMessages.agentsettingsform_describe_responsibilities_working_style_and_b_323733,
            )}
          />
        </label>
        <p className="form-hint">
          {t(
            ...uiMessages.agentsettingsform_you_define_the_name_and_role_changes_apply_to_511d1c,
          )}
        </p>
        {editingAgentID && (
          <p className="form-hint">
            {t(
              ...uiMessages.agentsettingsform_changing_the_runtime_location_applies_to_new_a80cfd,
            )}
          </p>
        )}
        <button
          className="primary"
          disabled={
            busy ||
            !agentName.trim() ||
            environment === NEW_SSH_CONNECTION ||
            (!editingAgentID && !selectedAvailable) ||
            (provider === "pi" && permissionMode !== "full_access")
          }
        >
          {editingAgentID
            ? t(...uiMessages.agentsettingsform_save_settings_a73136)
            : t(...uiMessages.agentsettingsform_create_agent_dc8d4a)}
        </button>
      </form>
    </section>
  );
}
