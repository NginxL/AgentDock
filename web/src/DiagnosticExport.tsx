import * as uiMessages from "./messages";
import { useState } from "react";
import { request } from "./api";
import type { Translate } from "./types";

export default function DiagnosticExport({
  token,
  t,
  onError,
}: {
  token: string;
  t: Translate;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    try {
      const result = await request<{ data: string; filename: string }>(
        token,
        "/api/diagnostics",
      );
      const bytes = Uint8Array.from(atob(result.data), (value) =>
        value.charCodeAt(0),
      );
      const url = URL.createObjectURL(
        new Blob([bytes], { type: "application/zip" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      onError(
        error instanceof Error ? error.message : "Diagnostic export failed",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      className="text-button"
      disabled={busy}
      onClick={() => void download()}
    >
      {busy
        ? t(...uiMessages.diagnosticexport_exporting_6c31cf)
        : t(...uiMessages.diagnosticexport_export_diagnostics_fbb13c)}
    </button>
  );
}
