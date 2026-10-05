import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // Preserve the Vite 6 webview baseline when upgrading the bundler.
    target: ["chrome87", "edge88", "firefox78", "safari14"],
  },
});
