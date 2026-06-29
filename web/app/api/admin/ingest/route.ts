export const runtime = "nodejs";

import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { bearerToken, errorResponse, requireAdmin } from "@/lib/adminAuth";
import { buildIngestCommand, isLocalIngestAllowed, resolveZipDir } from "@/lib/localIngest";

const execFileAsync = promisify(execFile);

function ingestStatus(req: Request) {
  const url = new URL(req.url);
  const zipDir = resolveZipDir();
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
    const status = ingestStatus(req);
    if (!status.allowed) {
      return new Response("local ingest is only available from localhost", { status: 409 });
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
