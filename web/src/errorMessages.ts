export const errorCopy: Record<string, readonly [string, string]> = {
  choose_an_agent_in_this_project: [
    "请选择当前项目中的 Agent。",
    "Choose an Agent in this project",
  ],
  task_agents_must_use_the_project_device: [
    "负责人和协作 Agent 需要使用项目所在设备。",
    "Task Agents must use the project device",
  ],
  resume_this_task_before_submitting_more_work: [
    "请先接续任务，再提交执行要求。",
    "Resume this task before submitting more work",
  ],
  reopen_this_task_before_adding_requirements: [
    "请先重新打开任务，再补充要求。",
    "Reopen this task before adding requirements",
  ],
  wait_for_the_current_work_before_changing_discussion_or_execution_mode: [
    "请等待当前执行结束，或先暂停任务，再切换处理方式。",
    "Wait for the current work before changing discussion or execution mode",
  ],
  this_run_does_not_support_live_adjustment_queue_the_input_or_stop_it_first: [
    "本轮暂不支持即时调整，请选择排队处理，或先暂停。",
    "This run does not support live adjustment; queue the input or stop it first",
  ],
  the_active_task_run_changed: [
    "当前执行已变化，请刷新后选择发送时机。",
    "The active task run changed",
  ],
  the_previous_task_processes_are_still_stopping: [
    "上一次执行仍在停止中，请稍后接续。",
    "The previous task processes are still stopping",
  ],
  a_previous_native_process_still_owns_this_task_conversation: [
    "旧执行进程仍在使用会话，请等它停止后再接续。",
    "A previous native process still owns this task conversation",
  ],
  remote_execution_is_still_stopping_retry_after_it_settles: [
    "远端执行尚未停止，请稍后重试。",
    "Remote execution is still stopping; retry after it settles",
  ],
  pause_execution_before_changing_task_requirements: [
    "请先暂停执行，待进程停止后再修改任务要求。",
    "Pause execution before changing task requirements",
  ],
  wait_for_task_execution_and_delegated_results: [
    "请等待执行结束并收回协作结果。",
    "Wait for task execution and delegated results",
  ],
  answer_the_pending_task_questions_first: [
    "请先回答待确认的问题。",
    "Answer the pending task questions first",
  ],
  the_task_owner_has_not_submitted_a_delivery: [
    "负责人还未提交交付结果。",
    "The task owner has not submitted a delivery",
  ],
  all_acceptance_checks_need_passing_evidence: [
    "还有验收项未通过验证，请让负责人补齐证据。",
    "All acceptance checks need passing evidence",
  ],
  an_approved_independent_review_is_required_before_final_delivery: [
    "需要另一位 Agent 审查通过后才能验收。",
    "An approved independent review is required before final delivery",
  ],
  request_a_new_review_after_the_latest_delegated_changes: [
    "最新协作修改尚未审查，请重新安排审查。",
    "Request a new review after the latest delegated changes",
  ],
  reassign_or_cancel_this_agent_s_project_tasks_before_deleting_it: [
    "请先更换该 Agent 的项目任务负责人，或取消相关任务后再删除。",
    "Reassign or cancel this Agent's project tasks before deleting it",
  ],
  use_the_project_task_input_to_continue_this_conversation: [
    "请打开对应项目任务，继续补充要求。",
    "Use the project task input to continue this conversation",
  ],
  commit_or_save_project_changes_before_creating_an_isolated_worktree: [
    "项目目录有未提交的修改，请先保存为提交，再创建独立工作区。",
    "Commit or save project changes before creating an isolated worktree",
  ],
  this_cli_does_not_advertise_a_read_only_planning_mode_choose_another_agent_: [
    "该 CLI 尚未提供只读规划模式，请选择其他 Agent 进行讨论或审查。",
    "This CLI does not advertise a read-only planning mode. Choose another Agent for discussion or review.",
  ],
  stop_active_tasks_before_deleting_an_agent: [
    "请先停止该 Agent 的未完成任务，再删除。",
    "Stop active tasks before deleting an agent",
  ],
  wait_for_linked_tasks_before_deleting_an_agent: [
    "请等待该 Agent 的协作任务结束后再删除。",
    "Wait for linked tasks before deleting an agent",
  ],
  invalid_session_model_settings: [
    "请选择有效的会话模型与推理等级。",
    "Invalid session model settings",
  ],
  stop_active_tasks_before_deleting_a_session: [
    "请先停止当前任务，再删除会话。",
    "Stop active tasks before deleting a session",
  ],
  wait_for_linked_tasks_before_deleting_a_session: [
    "请等待关联的协作任务结束后再删除会话。",
    "Wait for linked tasks before deleting a session",
  ],
  enable_execution_to_clean_up_a_remote_session: [
    "请启用执行后再删除远端会话。",
    "Enable execution to clean up a remote session",
  ],
  could_not_clean_up_the_remote_session_check_the_ssh_connection_and_retry_th: [
    "远端会话清理失败，请检查 SSH 连接后重试。会话记录已保留。",
    "Could not clean up the remote session. Check the SSH connection and retry. The session has been kept.",
  ],
  could_not_prepare_isolated_codex_session_storage_no_prompt_was_sent: [
    "无法准备独立的 Codex 会话目录，任务尚未发送。",
    "Could not prepare isolated Codex session storage; no prompt was sent.",
  ],
  invalid_agent_permission_mode: [
    "请选择有效的 Agent 访问权限。",
    "Invalid agent permission mode",
  ],
  wait_for_active_tasks_before_changing_agent_settings: [
    "请等待排队或执行中的任务结束后再修改 Agent 设置。",
    "Wait for active tasks before changing agent settings",
  ],
  ssh_connection_failed_check_ssh_access_python_3_9_and_the_installed_clis: [
    "SSH 连接失败，请检查连接权限、远端 Python 3.11+ 及 CLI 安装情况。",
    "SSH connection failed. Check SSH access, Python 3.11+ and the installed CLIs.",
  ],
  connect_this_ssh_environment_before_starting_an_agent: [
    "请先打开 Agent 设置，点击「连接 / 检查」，再重试任务。",
    "Connect this SSH environment before starting an agent.",
  ],
  the_selected_native_cli_was_not_found_on_this_environment: [
    "所选环境中未找到该 Agent CLI。",
    "The selected native CLI was not found on this environment.",
  ],
  use_an_ssh_host_alias_without_flags_or_shell_commands: [
    "请填写 SSH Host 别名或 user@host，不要附加参数或命令。",
    "Use an SSH Host alias, without flags or shell commands",
  ],
  invalid_remote_python_executable: [
    "请填写远端 Python 命令名或可执行文件的绝对路径。",
    "Invalid remote Python executable",
  ],
  use_an_absolute_directory_on_the_remote_host: [
    "请填写远端主机上的绝对目录路径。",
    "Use an absolute directory on the remote host",
  ],
  this_environment_is_still_in_use: [
    "该环境仍有关联的项目或 Agent，无法移除。",
    "This environment is still in use",
  ],
  remote_operation_failed_reconnect_the_environment_and_check_the_remote_cli: [
    "远端操作失败，请在 Agent 设置中检查连接及远端 CLI。",
    "Remote operation failed. Reconnect the environment and check the remote CLI.",
  ],
  the_remote_working_directory_does_not_exist: [
    "远端工作目录不存在，请检查目录设置。",
    "The remote working directory does not exist.",
  ],
  codex_selected_a_different_working_directory_no_prompt_was_sent: [
    "Codex 返回的工作目录与设置不一致，任务尚未发送。",
    "Codex selected a different working directory; no prompt was sent.",
  ],
  ssh_remained_disconnected_the_remote_task_will_stop_when_its_90_second_leas: [
    "SSH 持续断开，远端任务将在 90 秒连接租约到期后停止。",
    "SSH remained disconnected. The remote task will stop when its 90-second lease expires.",
  ],
  remote_worker_stopped_unexpectedly: [
    "远端执行进程意外退出。",
    "Remote worker stopped unexpectedly.",
  ],
  remote_native_cli_failed: [
    "远端 Agent CLI 执行失败。",
    "Remote native CLI failed.",
  ],
  execution_disabled: [
    "当前仅可查看，请先启用任务执行。",
    "Execution is disabled for review.",
  ],
  experimental_disabled: [
    "请先在账号页启用对应实验功能。",
    "Enable this experiment on the Accounts page first.",
  ],
};
// Compatibility with servers predating stable error codes.
export const legacyErrorCodes: Record<string, string> = {
  "Choose an Agent in this project": "choose_an_agent_in_this_project",
  "Task Agents must use the project device":
    "task_agents_must_use_the_project_device",
  "Resume this task before submitting more work":
    "resume_this_task_before_submitting_more_work",
  "Reopen this task before adding requirements":
    "reopen_this_task_before_adding_requirements",
  "Wait for the current work before changing discussion or execution mode":
    "wait_for_the_current_work_before_changing_discussion_or_execution_mode",
  "This run does not support live adjustment; queue the input or stop it first":
    "this_run_does_not_support_live_adjustment_queue_the_input_or_stop_it_first",
  "The active task run changed": "the_active_task_run_changed",
  "The previous task processes are still stopping":
    "the_previous_task_processes_are_still_stopping",
  "A previous native process still owns this task conversation":
    "a_previous_native_process_still_owns_this_task_conversation",
  "Remote execution is still stopping; retry after it settles":
    "remote_execution_is_still_stopping_retry_after_it_settles",
  "Pause execution before changing task requirements":
    "pause_execution_before_changing_task_requirements",
  "Wait for task execution and delegated results":
    "wait_for_task_execution_and_delegated_results",
  "Answer the pending task questions first":
    "answer_the_pending_task_questions_first",
  "The task owner has not submitted a delivery":
    "the_task_owner_has_not_submitted_a_delivery",
  "All acceptance checks need passing evidence":
    "all_acceptance_checks_need_passing_evidence",
  "An approved independent review is required before final delivery":
    "an_approved_independent_review_is_required_before_final_delivery",
  "Request a new review after the latest delegated changes":
    "request_a_new_review_after_the_latest_delegated_changes",
  "Reassign or cancel this Agent's project tasks before deleting it":
    "reassign_or_cancel_this_agent_s_project_tasks_before_deleting_it",
  "Use the project task input to continue this conversation":
    "use_the_project_task_input_to_continue_this_conversation",
  "Commit or save project changes before creating an isolated worktree":
    "commit_or_save_project_changes_before_creating_an_isolated_worktree",
  "This CLI does not advertise a read-only planning mode. Choose another Agent for discussion or review.":
    "this_cli_does_not_advertise_a_read_only_planning_mode_choose_another_agent_",
  "Stop active tasks before deleting an agent":
    "stop_active_tasks_before_deleting_an_agent",
  "Wait for linked tasks before deleting an agent":
    "wait_for_linked_tasks_before_deleting_an_agent",
  "Invalid session model settings": "invalid_session_model_settings",
  "Stop active tasks before deleting a session":
    "stop_active_tasks_before_deleting_a_session",
  "Wait for linked tasks before deleting a session":
    "wait_for_linked_tasks_before_deleting_a_session",
  "Enable execution to clean up a remote session":
    "enable_execution_to_clean_up_a_remote_session",
  "Could not clean up the remote session. Check the SSH connection and retry. The session has been kept.":
    "could_not_clean_up_the_remote_session_check_the_ssh_connection_and_retry_th",
  "Could not prepare isolated Codex session storage; no prompt was sent.":
    "could_not_prepare_isolated_codex_session_storage_no_prompt_was_sent",
  "Invalid agent permission mode": "invalid_agent_permission_mode",
  "Wait for active tasks before changing agent settings":
    "wait_for_active_tasks_before_changing_agent_settings",
  "SSH connection failed. Check SSH access, Python 3.11+ and the installed CLIs.":
    "ssh_connection_failed_check_ssh_access_python_3_9_and_the_installed_clis",
  "SSH connection failed. Check SSH access, Python 3.9+ and the installed CLIs.":
    "ssh_connection_failed_check_ssh_access_python_3_9_and_the_installed_clis",
  "Connect this SSH environment before starting an agent.":
    "connect_this_ssh_environment_before_starting_an_agent",
  "The selected native CLI was not found on this environment.":
    "the_selected_native_cli_was_not_found_on_this_environment",
  "Use an SSH Host alias, without flags or shell commands":
    "use_an_ssh_host_alias_without_flags_or_shell_commands",
  "Invalid remote Python executable": "invalid_remote_python_executable",
  "Use an absolute directory on the remote host":
    "use_an_absolute_directory_on_the_remote_host",
  "This environment is still in use": "this_environment_is_still_in_use",
  "Remote operation failed. Reconnect the environment and check the remote CLI.":
    "remote_operation_failed_reconnect_the_environment_and_check_the_remote_cli",
  "The remote working directory does not exist.":
    "the_remote_working_directory_does_not_exist",
  "Codex selected a different working directory; no prompt was sent.":
    "codex_selected_a_different_working_directory_no_prompt_was_sent",
  "SSH remained disconnected. The remote task will stop when its 90-second lease expires.":
    "ssh_remained_disconnected_the_remote_task_will_stop_when_its_90_second_leas",
  "Remote worker stopped unexpectedly.": "remote_worker_stopped_unexpectedly",
  "Remote native CLI failed.": "remote_native_cli_failed",
};
