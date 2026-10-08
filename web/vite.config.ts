import {mkdirSync, readFileSync, writeFileSync} from "node:fs";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  define: {__APP_VERSION__: JSON.stringify(readFileSync(new URL("../agentdock/__init__.py", import.meta.url), "utf8").match(/__version__ = "([^"]+)"/)![1])},
  plugins: [react(), {
    name: "bundled-license-notices",
    writeBundle() {
      const destination = new URL("./dist/licenses/", import.meta.url);
      mkdirSync(destination, {recursive: true});
      for (const name of ["react", "react-dom", "scheduler", "@tanstack/query-core", "@tanstack/react-query"]) {
        writeFileSync(new URL(name.replaceAll("/", "-") + ".txt", destination),
          readFileSync(new URL("./node_modules/" + name + "/LICENSE", import.meta.url)));
      }
      writeFileSync(new URL("lobe-icons.txt", destination), readFileSync(new URL("./src/assets/providers/LICENSE", import.meta.url)));
    },
  }],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  test: { environment: "jsdom", clearMocks: true, restoreMocks: true },
});
