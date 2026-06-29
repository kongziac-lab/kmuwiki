import { createClient } from "@supabase/supabase-js";

export function createSupabaseRouteClient(auth: string) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    throw new Error("Supabase 환경변수가 설정되지 않았습니다.");
  }
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      headers: {
        Authorization: auth,
      },
    },
  });
}
