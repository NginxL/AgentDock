import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import ProviderIcon, { providerNames, providers } from "./ProviderIcon";
import type { Provider, ProviderAvailability, Translate } from "./types";
import { Icon } from "./ui";

export default function ProviderSelect({
  value,
  onChange,
  disabled,
  availability,
  loading = false,
  failed = false,
  onRefresh,
  t,
}: {
  value: Provider;
  onChange: (provider: Provider) => void;
  disabled: boolean;
  availability?: ProviderAvailability;
  loading?: boolean;
  failed?: boolean;
  onRefresh?: () => void;
  t: Translate;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const options = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<CSSProperties>();
  const revealActive = useRef(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const enabled = providers
    .map((p, i) => (availability?.[p]?.available === true ? i : -1))
    .filter((i) => i >= 0);
  function revealOption(index: number) {
    const list = options.current;
    const option = document.getElementById(`${id}-${providers[index]}`);
    if (!list || !option) return;
    const bounds = list.getBoundingClientRect();
    const item = option.getBoundingClientRect();
    if (item.top < bounds.top) list.scrollTop += item.top - bounds.top;
    else if (item.bottom > bounds.bottom)
      list.scrollTop += item.bottom - bounds.bottom;
  }
  function navigate(index: number) {
    setActive(index);
    revealOption(index);
  }
  function move(direction: number) {
    if (!enabled.length) return;
    const index = enabled.indexOf(active);
    if (index < 0)
      navigate(
        direction > 0
          ? (enabled.find((i) => i > active) ?? enabled[0])
          : ([...enabled].reverse().find((i) => i < active) ??
              enabled[enabled.length - 1]),
      );
    else
      navigate(enabled[(index + direction + enabled.length) % enabled.length]);
  }
  function description(provider: Provider) {
    if (loading) return t("正在检测…", "Checking…");
    if (failed)
      return t("检测失败，点击刷新重试", "Check failed. Refresh to retry.");
    const reason = availability?.[provider]?.reason;
    if (reason === "connect_required")
      return t("请先连接所选设备", "Connect the selected device first");
    if (provider === "pi")
      return t(
        "需要 Pi CLI 和 pi-acp 适配器",
        "Requires Pi CLI and the pi-acp adapter",
      );
    if (provider === "antigravity")
      return t(
        "需要 Antigravity ACP 服务",
        "Requires the Antigravity ACP server",
      );
    return t("所选设备未找到此 CLI", "CLI not found on this device");
  }

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  function show() {
    setPlacement(undefined);
    revealActive.current = true;
    setActive(providers.indexOf(value));
    setOpen(true);
  }
  function choose(provider: Provider) {
    if (availability?.[provider]?.available !== true) return;
    if (provider !== value) onChange(provider);
    close();
  }

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  useLayoutEffect(() => {
    if (!open) return;
    function position() {
      const anchor = trigger.current?.getBoundingClientRect();
      if (!anchor) return;
      const viewport = window.visualViewport;
      const x = viewport?.offsetLeft ?? 0;
      const y = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth;
      const height = viewport?.height ?? window.innerHeight;
      if (
        anchor.width > 0 &&
        anchor.height > 0 &&
        (anchor.bottom <= y ||
          anchor.top >= y + height ||
          anchor.right <= x ||
          anchor.left >= x + width)
      ) {
        setOpen(false);
        return;
      }
      const margin = 8;
      const gap = 6;
      const below = Math.max(0, y + height - anchor.bottom - gap - margin);
      const above = Math.max(0, anchor.top - y - gap - margin);
      const upwards = below < 560 && above > below;
      const menuWidth = Math.min(anchor.width, Math.max(0, width - 2 * margin));
      setPlacement({
        left: Math.max(
          x + margin,
          Math.min(anchor.left, x + width - margin - menuWidth),
        ),
        width: menuWidth,
        maxHeight: Math.min(560, upwards ? above : below),
        ...(upwards
          ? { bottom: window.innerHeight - anchor.top + gap }
          : { top: anchor.bottom + gap }),
      });
    }
    function scroll(event: Event) {
      // List scrolling never moves the anchor or needs to reposition the menu.
      if (
        !(
          event.target instanceof Node &&
          popover.current?.contains(event.target)
        )
      )
        position();
    }
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", scroll, true);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(position);
    if (trigger.current) observer?.observe(trigger.current);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", scroll, true);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
      observer?.disconnect();
    };
  }, [open]);
  useLayoutEffect(() => {
    if (!open || !placement || !revealActive.current) return;
    // Scroll only the list, never its form/page ancestors. Hover is deliberately
    // excluded so wheel and trackpad scrolling cannot pull the list back up.
    revealOption(active);
    revealActive.current = false;
  }, [open, active, id, placement]);
  function contains(target: EventTarget | null) {
    return (
      target instanceof Node &&
      (root.current?.contains(target) || popover.current?.contains(target))
    );
  }
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div
      className="provider-select"
      ref={root}
      onBlur={(event) => {
        if (!contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (open && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}
    >
      <label htmlFor={id}>{t("服务", "Provider")}</label>
      <button
        id={id}
        ref={trigger}
        type="button"
        className="provider-select-trigger"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${id}-options` : undefined}
        aria-activedescendant={open ? `${id}-${providers[active]}` : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.preventDefault();
            event.stopPropagation();
            close();
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!open) show();
            else move(event.key === "ArrowDown" ? 1 : -1);
          } else if (open && (event.key === "Home" || event.key === "End")) {
            event.preventDefault();
            if (enabled.length) {
              navigate(
                event.key === "Home" ? enabled[0] : enabled[enabled.length - 1],
              );
            }
          } else if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (open) choose(providers[active]);
            else show();
          } else if (event.key === "Tab") setOpen(false);
        }}
      >
        <ProviderIcon provider={value} size={22} />
        <span>{providerNames[value]}</span>
        <span className="provider-select-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>
      {open &&
        createPortal(
          <div
            ref={popover}
            className="provider-select-popover"
            style={placement ?? { visibility: "hidden" }}
          >
            <div className="provider-select-heading">
              <span>{t("选择服务", "Select provider")}</span>
              {onRefresh && (
                <button
                  type="button"
                  className="icon-button"
                  disabled={loading}
                  aria-label={t("重新检测服务", "Refresh providers")}
                  onClick={onRefresh}
                >
                  ↻
                </button>
              )}
              <button
                type="button"
                className="icon-button"
                aria-label={t("关闭服务选择", "Close provider selection")}
                onClick={close}
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <div
              id={`${id}-options`}
              role="listbox"
              aria-label={t("服务", "Provider")}
              className="provider-options"
              ref={options}
            >
              {providers.map((provider, index) => (
                <div
                  id={`${id}-${provider}`}
                  key={provider}
                  role="option"
                  aria-selected={value === provider}
                  aria-disabled={availability?.[provider]?.available !== true}
                  className={`provider-option ${active === index ? "active" : ""}`}
                  onPointerMove={() => {
                    revealActive.current = false;
                    setActive(index);
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(provider)}
                >
                  <ProviderIcon provider={provider} size={22} />
                  <span className="provider-option-label">
                    <span>
                      {providerNames[provider]}
                      {availability?.[provider]?.available !== true && (
                        <small className="provider-unavailable">
                          {t("不可用", "Unavailable")}
                        </small>
                      )}
                    </span>
                    {availability?.[provider]?.available !== true && (
                      <small>{description(provider)}</small>
                    )}
                  </span>
                  <span className="provider-option-check" aria-hidden="true">
                    {value === provider ? "✓" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
