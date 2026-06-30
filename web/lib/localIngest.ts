import { existsSync } from "node:fs";
import { isIP } from "node:net";
import path from "node:path";

export const DEFAULT_ZIP_DIR = "/Users/kdh/Documents/KMU-Wiki-Zips";

export type IngestCommand = {
  command: string;
  args: string[];
  cwd: string;
};

export type LocalIngestEnv = Record<string, string | undefined>;

export function isSupportedLocalFolderPath(input: string): boolean {
  const value = input.trim();
  if (!value || value.includes("\0")) return false;
  if (path.isAbsolute(value)) return true;
  if (/^[A-Za-z]:[\\/]/.test(value)) return true;
  return /^\\\\[^\\]+\\[^\\]+/.test(value);
}

export function normalizeRequestedZipDir(input: unknown): string {
  if (typeof input !== "string") {
    throw new Error("ZIP 폴더는 문자열 절대경로로 입력해주세요.");
  }
  const value = input.trim();
  if (!isSupportedLocalFolderPath(value)) {
    throw new Error("ZIP 폴더는 로컬/NAS 절대경로로 입력해주세요.");
  }
  return value;
}

export function resolveZipDir(env: LocalIngestEnv = process.env, requestedZipDir?: unknown): string {
  if (requestedZipDir !== undefined && requestedZipDir !== null) {
    return normalizeRequestedZipDir(requestedZipDir);
  }
  return env.KMU_ZIP_DIR?.trim() || DEFAULT_ZIP_DIR;
}

export function isLoopbackHost(host: string | null | undefined): boolean {
  const hostname = requestHostname(host);
  if (!hostname) return false;
  if (hostname === "localhost" || hostname === "::1") return true;
  if (isIP(hostname) === 4) return hostname.split(".")[0] === "127";
  return false;
}

export function isPrivateNetworkHost(host: string | null | undefined): boolean {
  const hostname = requestHostname(host);
  if (!hostname) return false;
  if (isIP(hostname) !== 4) return false;

  const parts = hostname.split(".").map((part) => Number(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  const [first, second] = parts;
  return first === 10
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 168)
    || (first === 169 && second === 254);
}

function requestHostname(host: string | null | undefined): string {
  if (!host) return "";
  const cleaned = host.trim().toLowerCase();
  if (!cleaned) return "";
  if (cleaned.startsWith("[")) {
    const end = cleaned.indexOf("]");
    return end > 0 ? cleaned.slice(1, end) : cleaned.replace(/^\[/, "").replace(/\]$/, "");
  }
  const firstColon = cleaned.indexOf(":");
  const lastColon = cleaned.lastIndexOf(":");
  if (firstColon > -1 && firstColon === lastColon) return cleaned.slice(0, firstColon);
  return cleaned;
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
  const localHost = isLoopbackHost(requestHost) || isPrivateNetworkHost(requestHost);
  if (!localHost) return false;
  if (nodeEnv === "production") return enableFlag === "1";
  return true;
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
