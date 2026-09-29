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
  t,
}: {
  value: string;
  onChange: (value: string) => void;
  environment: string;
  token: string;
  disabled: boolean;
  browseEnabled: boolean;
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
    ? t("选择远端目录", "Choose a remote directory")
    : t("选择本机目录", "Choose a local directory");
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
        {t("工作目录（可留空）", "Working directory (optional)")}
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          spellCheck={false}
          placeholder={
            remote
              ? t(
                  "留空在远端创建独立目录",
                  "Leave blank for a private remote directory",
                )
              : t(
                  "留空在本机创建独立目录",
                  "Leave blank for a private local directory",
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
              aria-label={t("关闭目录选择", "Close directory picker")}
              onClick={close}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="directory-navigation">
            <button
              type="button"
              className="icon-button"
              aria-label={t("上一级目录", "Parent directory")}
              disabled={loading || !listing?.parent}
              onClick={() => listing?.parent && navigate(listing.parent)}
            >
              ↑
            </button>
            <input
              aria-label={t("目录路径", "Directory path")}
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
              {t("前往", "Go")}
            </button>
          </div>
          <div className="directory-list" aria-busy={loading}>
            {loading && (
              <p role="status">{t("正在读取目录…", "Loading directories…")}</p>
            )}
            {failed && (
              <p role="alert">
                {t(
                  "无法读取此目录，请检查路径或连接。",
                  "Cannot read this directory. Check the path or connection.",
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
              <p>{t("此目录没有子目录", "No subdirectories")}</p>
            )}
            {listing?.truncated && (
              <p>
                {t(
                  "目录较多，可直接输入完整路径。",
                  "More directories available. Enter a full path to navigate.",
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
            {t("使用此目录", "Use this directory")}
          </button>
        </div>
      )}
    </div>
  );
}
