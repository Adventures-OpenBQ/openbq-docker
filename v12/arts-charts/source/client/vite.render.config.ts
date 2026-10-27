// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
// SPDX-License-Identifier: BUSL-1.1
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The snapshot renderer's page (render/): an app build, not the library one.
// `npx vite build -c vite.render.config.ts` writes render/dist, which the
// server's ARTS_CHARTS_RENDER_DIR points at.
export default defineConfig({
  plugins: [react()],
  root: "render",
  // One page, one bundle (the whole card, ~0.6 MB): nothing to split.
  build: { target: "es2022", outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1024 },
});
