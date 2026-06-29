import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") ?? "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    throw new ApiError(401, "missing authorization");
  }
  return auth.slice("bearer ".length).trim();
}

export function userSupabase(token: string): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new ApiError(500, "Supabase environment is not configured");
  }
  return createClient(url, key, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function requireAdmin(token: string): Promise<SupabaseClient> {
  const client = userSupabase(token);
  const { data, error } = await client.rpc("current_user_is_admin");
  if (error) throw new ApiError(500, error.message);
  if (data !== true) throw new ApiError(403, "admin role required");
  return client;
}

export function errorResponse(error: unknown): Response {
  if (error instanceof ApiError) {
    return new Response(error.message, { status: error.status });
  }
  const message = error instanceof Error ? error.message : "internal error";
  return new Response(message, { status: 500 });
}
