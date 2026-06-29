import { existsSync } from "node:fs";
import path from "node:path";

export const DEFAULT_ZIP_DIR = "/Users/kdh/Documents/KMU-Wiki-Zips";

export type IngestCommand = {
  command: string;
  args: string[];
  cwd: string;
};

export type LocalIngestEnv = Record<string, string | undefined>;

export function resolveZipDir(env: LocalIngestEnv = process.env): string {
  return env.KMU_ZIP_DIR?.trim() || DEFAULT_ZIP_DIR;
}

export function isLoopbackHost(host: string | null | undefined): boolean {
  if (!host) return false;
  const cleaned = host.toLowerCase().replace(/^\[/, "").replace(/\]$/, "");
  const hostname = cleaned.includes(":") && !cleaned.includes("::")
    ? cleaned.split(":")[0]
    : cleaned;
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

export function isLocalIngestAllowed({
  nodeEnv,
  requestHost,
  enableFlag,
}: {
  nodeEnv?: string;
  requestHost?: string | null;
  enableFlag?: string;
}): boolean {
  if (!isLoopbackHost(requestHost)) return false;
  if (enableFlag === "1") return true;
  return nodeEnv !== "production";
}

export function resolveIngestCwd(env: LocalIngestEnv = process.env, webCwd = process.cwd()): string {
  if (env.KMU_INGEST_CWD?.trim()) return env.KMU_INGEST_CWD.trim();
  const sibling = path.resolve(webCwd, "../ingest");
  if (existsSync(sibling)) return sibling;
  return path.resolve(webCwd, "ingest");
}

export function buildIngestCommand(
  zipDir: string,
  options: { pythonBin?: string; ingestCwd?: string } = {},
): IngestCommand {
  return {
    command: options.pythonBin || process.env.KMU_PYTHON_BIN || "python3",
    args: ["-m", "kmu_ingest.cli", "run", "--path", zipDir],
    cwd: options.ingestCwd || resolveIngestCwd(),
  };
}
