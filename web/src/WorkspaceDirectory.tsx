import * as uiMessages from "./messages";
import { useEffect, useRef, useState } from "react";
import { request } from "./api";
import type { Translate } from "./types";
import { Icon } from "./ui";

type DirectoryListing = {
  path: string;
  parent: string | null;
  directories: { name: string; path: string }[];
  truncated: boolean;
};

export default function WorkspaceDirectory({
  value,
  onChange,
  environment,
  token,
  disabled,
  browseEnabled,
  required = false,
  t,
}: {
  value: string;
  onChange: (value: string) => void;
  environment: string;
  token: string;
  disabled: boolean;
  browseEnabled: boolean;
  required?: boolean;
  t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("~");
  const [draftPath, setDraftPath] = useState("~");
  const [revision, setRevision] = useState(0);
  const [listing, setListing] = useState<DirectoryListing>();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const remote = environment !== "local";
  const title = remote
    ? t(...uiMessages.workspacedirectory_choose_a_remote_directory_376616)
    : t(...uiMessages.workspacedirectory_choose_a_local_directory_869c6c);
  function close() {
    setOpen(false);
    button.current?.focus();
  }
  function navigate(destination: string) {
    setPath(destination);
    setDraftPath(destination);
    setRevision((n) => n + 1);
  }

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setListing(undefined);
    setFailed(false);
    setLoading(true);
    void request<DirectoryListing>(
      token,
      `/api/directories?environment_id=${encodeURIComponent(environment)}&path=${encodeURIComponent(path)}`,
      undefined,
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!data.path || !Array.isArray(data.directories))
          throw new Error("Invalid directory listing");
        setListing(data);
        setDraftPath(data.path);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, environment, path, token, revision]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="workspace-directory" ref={root}>
      <label>
        {required
          ? t(
              ...uiMessages.workspacedirectory_project_directory_on_the_agent_device_dea251,
            )
          : t(
              ...uiMessages.workspacedirectory_working_directory_optional_36d77f,
            )}
        <input
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          spellCheck={false}
          placeholder={
            required
              ? t(
                  ...uiMessages.workspacedirectory_enter_this_project_s_absolute_path_be8842,
                )
              : remote
                ? t(
                    ...uiMessages.workspacedirectory_leave_blank_for_a_private_remote_directory_32991e,
                  )
                : t(
                    ...uiMessages.workspacedirectory_leave_blank_for_a_private_local_directory_f09251,
                  )
          }
        />
      </label>
      <button
        ref={button}
        type="button"
        className="icon-button directory-toggle"
        aria-label={title}
        title={title}
        aria-expanded={open}
        disabled={disabled || !browseEnabled}
        onClick={() => {
          if (open) close();
          else {
            navigate(value.trim() || "~");
            setOpen(true);
          }
        }}
      >
        <Icon name="folder" />
      </button>
      {open && (
        <div className="directory-picker" role="dialog" aria-label={title}>
          <div className="panel-heading">
            <strong>{title}</strong>
            <button
              type="button"
              className="icon-button"
              aria-label={t(
                ...uiMessages.workspacedirectory_close_directory_picker_3f5627,
              )}
              onClick={close}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="directory-navigation">
            <button
              type="button"
              className="icon-button"
              aria-label={t(
                ...uiMessages.workspacedirectory_parent_directory_8e56da,
              )}
              disabled={loading || !listing?.parent}
              onClick={() => listing?.parent && navigate(listing.parent)}
            >
              ↑
            </button>
            <input
              aria-label={t(
                ...uiMessages.workspacedirectory_directory_path_88239c,
              )}
              value={draftPath}
              onChange={(e) => setDraftPath(e.target.value)}
              spellCheck={false}
              autoFocus
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.nativeEvent.isComposing &&
                  e.nativeEvent.keyCode !== 229
                ) {
                  e.preventDefault();
                  e.stopPropagation();
                  navigate(draftPath.trim() || "~");
                }
              }}
            />
            <button
              type="button"
              className="text-button"
              disabled={loading || !draftPath.trim()}
              onClick={() => navigate(draftPath.trim())}
            >
              {t(...uiMessages.workspacedirectory_go_a823db)}
            </button>
          </div>
          <div className="directory-list" aria-busy={loading}>
            {loading && (
              <p role="status">
                {t(...uiMessages.workspacedirectory_loading_directories_9334a7)}
              </p>
            )}
            {failed && (
              <p role="alert">
                {t(
                  ...uiMessages.workspacedirectory_cannot_read_this_directory_check_the_path_or_ca94ab,
                )}
              </p>
            )}
            {!loading &&
              listing?.directories.map((item) => (
                <button
                  type="button"
                  key={item.path}
                  onClick={() => navigate(item.path)}
                >
                  <Icon name="folder" size={16} />
                  <span>{item.name}</span>
                  <span aria-hidden="true">›</span>
                </button>
              ))}
            {!loading && listing?.directories.length === 0 && (
              <p>
                {t(...uiMessages.workspacedirectory_no_subdirectories_37fd3d)}
              </p>
            )}
            {listing?.truncated && (
              <p>
                {t(
                  ...uiMessages.workspacedirectory_more_directories_available_enter_a_full_path_575a48,
                )}
              </p>
            )}
          </div>
          <button
            type="button"
            className="primary"
            disabled={loading || !listing}
            onClick={() => {
              if (listing) {
                onChange(listing.path);
                close();
              }
            }}
          >
            {t(...uiMessages.workspacedirectory_use_this_directory_13e7d1)}
          </button>
        </div>
      )}
    </div>
  );
}
