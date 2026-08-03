import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { createReadStream, readFileSync, statSync } from "node:fs";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const dataDirectory = resolve(currentDirectory, "../data");
const siteConfigPath = resolve(currentDirectory, "../config/site.json");

const contentTypes: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
};

function localDataPlugin(): Plugin {
  return {
    name: "local-public-data",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const requestUrl = new URL(request.url || "/", "http://localhost");
        if (requestUrl.pathname === "/site-config.json") {
          try {
            const config = JSON.parse(readFileSync(siteConfigPath, "utf8")) as Record<string, unknown>;
            const runtimeConfig = {
              site: config.site || {},
              twitch: config.twitch || {},
            };
            response.statusCode = 200;
            response.setHeader("Cache-Control", "no-store");
            response.setHeader("Content-Type", "application/json; charset=utf-8");
            response.end(JSON.stringify(runtimeConfig));
          } catch {
            response.statusCode = 500;
            response.end("Unable to read site configuration");
          }
          return;
        }
        if (!requestUrl.pathname.startsWith("/data/")) {
          next();
          return;
        }

        const relativePath = decodeURIComponent(requestUrl.pathname.slice("/data/".length));
        const resolvedPath = resolve(dataDirectory, relativePath);
        const allowedPrefix = `${dataDirectory}${sep}`;
        if (resolvedPath !== dataDirectory && !resolvedPath.startsWith(allowedPrefix)) {
          response.statusCode = 403;
          response.end("Forbidden");
          return;
        }

        try {
          const stats = statSync(resolvedPath);
          if (!stats.isFile()) {
            next();
            return;
          }
          response.statusCode = 200;
          response.setHeader("Cache-Control", "no-store");
          response.setHeader("Content-Type", contentTypes[extname(resolvedPath).toLowerCase()] || "application/octet-stream");
          createReadStream(resolvedPath).pipe(response);
        } catch {
          next();
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), localDataPlugin()],
  publicDir: resolve(currentDirectory, "public"),
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/@cloudflare/kumo")) return "kumo";
          if (id.includes("node_modules/@phosphor-icons")) return "icons";
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) return "react-vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    host: "localhost",
    port: 4174,
    strictPort: true,
  },
  preview: {
    host: "localhost",
    port: 4174,
    strictPort: true,
  },
});
