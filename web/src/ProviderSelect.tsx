import { useEffect, useId, useRef, useState } from "react";
import ProviderIcon, { providerNames } from "./ProviderIcon";
import type { Provider, Translate } from "./types";
import { Icon } from "./ui";

const providers: Provider[] = ["codex", "claude"];

export default function ProviderSelect({
  value,
  onChange,
  disabled,
  t,
}: {
  value: Provider;
  onChange: (provider: Provider) => void;
  disabled: boolean;
  t: Translate;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  function show() {
    setActive(providers.indexOf(value));
    setOpen(true);
  }
  function choose(provider: Provider) {
    if (provider !== value) onChange(provider);
    close();
  }

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div
      className="provider-select"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
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
            else
              setActive(
                (index) =>
                  (index +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    providers.length) %
                  providers.length,
              );
          } else if (open && (event.key === "Home" || event.key === "End")) {
            event.preventDefault();
            setActive(event.key === "Home" ? 0 : providers.length - 1);
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
      {open && (
        <div className="provider-select-popover">
          <div className="provider-select-heading">
            <span>{t("选择服务", "Select provider")}</span>
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
          >
            {providers.map((provider, index) => (
              <div
                id={`${id}-${provider}`}
                key={provider}
                role="option"
                aria-selected={value === provider}
                className={`provider-option ${active === index ? "active" : ""}`}
                onPointerMove={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(provider)}
              >
                <ProviderIcon provider={provider} size={22} />
                <span>{providerNames[provider]}</span>
                <span className="provider-option-check" aria-hidden="true">
                  {value === provider ? "✓" : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
