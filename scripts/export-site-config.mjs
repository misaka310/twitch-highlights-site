import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadSiteConfig } from "./site-config-runtime.mjs";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const rootDir = resolve(__dirname, "..");
const outputPath = resolve(process.argv[2] || resolve(rootDir, "public", "site-config.json"));
const config = loadSiteConfig(rootDir);

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");

const publicDir = dirname(outputPath);
const baseUrl = config.site.base_url;
const robotsLines = ["User-agent: *", "Allow: /"];
if (baseUrl) {
  robotsLines.push("", `Sitemap: ${baseUrl}/sitemap.xml`);
}
writeFileSync(resolve(publicDir, "robots.txt"), `${robotsLines.join("\n")}\n`, "utf8");

if (baseUrl) {
  const sitemap = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    "  <url>",
    `    <loc>${escapeXml(baseUrl)}/</loc>`,
    "  </url>",
    "</urlset>",
    "",
  ].join("\n");
  writeFileSync(resolve(publicDir, "sitemap.xml"), sitemap, "utf8");
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
