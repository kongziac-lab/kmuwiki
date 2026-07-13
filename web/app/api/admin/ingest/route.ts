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
  const allowed = isLocalIngestAllowed({
    nodeEnv: process.env.NODE_ENV,
    requestHost: url.host,
    enableFlag: process.env.KMU_ENABLE_LOCAL_INGEST,
  });
  return {
    allowed,
    zipDir,
    host: url.host,
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
    // 선택 강화: KMU_LOCAL_INGEST_ALLOWED_DIRS(콤마 구분)를 설정하면 그 하위 경로만 허용.
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
