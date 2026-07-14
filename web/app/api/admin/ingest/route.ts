export const runtime = "nodejs";

import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { ApiError, bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";
import {
  buildIngestCommand,
  isLocalIngestAllowed,
  isZipDirAllowed,
  parseAllowedIngestDirs,
  resolveZipDir,
  trustedClientAddress,
} from "@/lib/localIngest";

const execFileAsync = promisify(execFile);

type IngestBody = {
  zipDir?: unknown;
};

async function readIngestBody(req: Request): Promise<IngestBody> {
  const text = await req.text();
  if (!text.trim()) return {};
  try {
    const body = JSON.parse(text) as IngestBody;
    return body && typeof body === "object" ? body : {};
  } catch {
    throw new ApiError(400, "invalid ingest request body");
  }
}

function ingestStatus(req: Request, requestedZipDir?: unknown) {
  const url = new URL(req.url);
  const zipDir = resolveZipDir(process.env, requestedZipDir);
  const allowedDirs = parseAllowedIngestDirs(process.env.KMU_LOCAL_INGEST_ALLOWED_DIRS);
  const networkAllowed = isLocalIngestAllowed({
    nodeEnv: process.env.NODE_ENV,
    requestHost: url.host,
    enableFlag: process.env.KMU_ENABLE_LOCAL_INGEST,
    trustProxyHeaders: process.env.KMU_TRUST_PROXY_HEADERS,
    clientAddress: trustedClientAddress(req, process.env.KMU_TRUST_PROXY_HEADERS),
  });
  return {
    allowed: networkAllowed && allowedDirs.length > 0,
    zipDir,
    host: url.host,
    clientAddress: trustedClientAddress(req, process.env.KMU_TRUST_PROXY_HEADERS),
    allowedDirCount: allowedDirs.length,
    production: process.env.NODE_ENV === "production",
  };
}

export async function GET(req: Request) {
  try {
    await requireAdmin(bearerToken(req));
    return Response.json(ingestStatus(req));
  } catch (error) {
    return errorResponse(error);
  }
}

export async function POST(req: Request) {
  try {
    await requireAdmin(bearerToken(req));
    const body = await readIngestBody(req);
    let status: ReturnType<typeof ingestStatus>;
    try {
      status = ingestStatus(req, body.zipDir);
    } catch (error) {
      throw new ApiError(400, error instanceof Error ? error.message : "invalid ZIP folder");
    }
    if (!status.allowed) {
      return new Response("local ingest is only available from localhost or a private LAN host", { status: 409 });
    }
    // 필수 경계: 허용 목록이 없거나 그 밖의 경로면 실행하지 않는다.
    const allowedDirs = parseAllowedIngestDirs(process.env.KMU_LOCAL_INGEST_ALLOWED_DIRS);
    if (!isZipDirAllowed(status.zipDir, allowedDirs)) {
      return new Response("zip folder is outside KMU_LOCAL_INGEST_ALLOWED_DIRS", { status: 403 });
    }

    const command = buildIngestCommand(status.zipDir);
    const result = await execFileAsync(command.command, command.args, {
      cwd: command.cwd,
      env: process.env,
      timeout: Number(process.env.KMU_LOCAL_INGEST_TIMEOUT_MS ?? 600000),
      maxBuffer: 10 * 1024 * 1024,
    });

    return Response.json({
      ok: true,
      zipDir: status.zipDir,
      command: [command.command, ...command.args],
      cwd: command.cwd,
      stdout: result.stdout,
      stderr: result.stderr,
    });
  } catch (error) {
    return errorResponse(error);
  }
}
