import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// 브라우저용 Supabase 클라이언트. 로그인 세션의 access_token(JWT)을 /api/chat 에 실어
// 보내면 Python 서비스가 그 JWT로 RLS를 적용한다(권한 강제).
// env가 아직 설정되지 않았으면 null 을 반환한다 → 빌드 시 크래시 없이, 런타임엔
// 토큰 없음(deny-by-default)으로 동작.
let _client: SupabaseClient | null = null;

function client(): SupabaseClient | null {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  _client = createClient(url, key);
  return _client;
}

export async function getAccessToken(): Promise<string | null> {
  const c = client();
  if (!c) return null;
  const { data } = await c.auth.getSession();
  return data.session?.access_token ?? null;
}
