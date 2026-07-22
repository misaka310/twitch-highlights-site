import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadSiteConfig } from "./site-config-runtime.mjs";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const rootDir = resolve(__dirname, "..");
const siteDir = join(rootDir, "site");
const dataDir = join(rootDir, "data");
const host = process.env.HOST || "localhost";
const defaultPort = 8000;
const maxPort = 65535;

function resolveStartPort() {
  const rawPort = Number.parseInt(process.env.PORT || "", 10);
  if (Number.isInteger(rawPort) && rawPort > 0 && rawPort <= maxPort) {
    return rawPort;
  }
  return defaultPort;
}

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
  ".xml": "application/xml; charset=utf-8",
};

function isInside(childPath, parentPath) {
  const resolvedParent = resolve(parentPath);
  const resolvedChild = resolve(childPath);
  const pathFromParent = relative(resolvedParent, resolvedChild);
  return pathFromParent === "" || (!pathFromParent.startsWith("..") && !isAbsolute(pathFromParent));
}

function resolveRequestPath(urlPath) {
  const decodedPath = decodeURIComponent(urlPath);
  if (decodedPath.startsWith("/data/")) {
    return {
      baseDir: dataDir,
      filePath: join(dataDir, decodedPath.replace(/^\/data\//, "")),
    };
  }

  const sitePath = decodedPath === "/" ? "/index.html" : decodedPath;
  return {
    baseDir: siteDir,
    filePath: join(siteDir, sitePath),
  };
}

function sendNotFound(response) {
  response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
  response.end("Not found");
}

function sendSiteConfig(response) {
  try {
    const body = `${JSON.stringify(loadSiteConfig(rootDir), null, 2)}\n`;
    response.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    });
    response.end(body);
  } catch (error) {
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end(`Invalid site configuration: ${error.message}`);
  }
}

function createRequestHandler() {
  return (request, response) => {
    const url = new URL(request.url || "/", `http://${request.headers.host || host}`);
    if (url.pathname === "/site-config.json") {
      sendSiteConfig(response);
      return;
    }

    const { baseDir, filePath } = resolveRequestPath(url.pathname);
    const safePath = resolve(filePath);

    if (!isInside(safePath, baseDir) || !existsSync(safePath) || !statSync(safePath).isFile()) {
      sendNotFound(response);
      return;
    }

    response.writeHead(200, {
      "content-type": contentTypes[extname(safePath).toLowerCase()] || "application/octet-stream",
      "cache-control": "no-store",
    });
    createReadStream(safePath).pipe(response);
  };
}

function listenOnPort(portToTry) {
  return new Promise((resolvePromise, reject) => {
    const server = createServer(createRequestHandler());
    const onError = (error) => {
      server.removeListener("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.removeListener("error", onError);
      resolvePromise(server);
    };

    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(portToTry, host);
  });
}

async function startServer() {
  let port = resolveStartPort();
  while (port <= maxPort) {
    try {
      const server = await listenOnPort(port);
      return { server, port };
    } catch (error) {
      if (error && error.code === "EADDRINUSE") {
        port += 1;
        continue;
      }
      throw error;
    }
  }

  throw new Error(`No available port found between ${resolveStartPort()} and ${maxPort}`);
}

startServer()
  .then(({ port }) => {
    console.log(`Open manually: http://${host}:${port}/`);
  })
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
