import { createClient } from "https://esm.sh/@supabase/supabase-js@2.57.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Método não permitido." }, 405);

  const authHeader = req.headers.get("Authorization") || "";
  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  const pageId = Deno.env.get("FACEBOOK_PAGE_ID") || "";
  const pageToken = Deno.env.get("FACEBOOK_PAGE_ACCESS_TOKEN") || "";

  if (!authHeader.startsWith("Bearer ")) return json({ error: "Faça login como CEO." }, 401);
  if (!supabaseUrl || !anonKey) return json({ error: "Supabase não configurado." }, 500);

  const supabase = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: { user }, error: userError } = await supabase.auth.getUser();
  if (userError || !user) return json({ error: "Sessão inválida ou expirada." }, 401);

  const ceoEmail = (Deno.env.get("CEO_EMAIL") || "").toLowerCase();
  if (!ceoEmail || String(user.email || "").toLowerCase() !== ceoEmail) {
    return json({ error: "Somente o CEO pode programar publicações." }, 403);
  }
  if (!pageId || !pageToken) {
    return json({
      configured: false,
      error: "Defina FACEBOOK_PAGE_ID e FACEBOOK_PAGE_ACCESS_TOKEN nos segredos do Supabase.",
    }, 503);
  }

  let payload: { action?: string; posts?: Array<Record<string, unknown>> };
  try {
    payload = await req.json();
  } catch {
    return json({ error: "JSON inválido." }, 400);
  }

  if (payload.action === "status") {
    const url = new URL(`https://graph.facebook.com/v26.0/${encodeURIComponent(pageId)}`);
    url.searchParams.set("fields", "id,name");
    url.searchParams.set("access_token", pageToken);
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok || data.error) return json({ configured: false, error: data.error?.message || "Falha ao consultar a Página." }, 502);
    return json({ configured: true, page: { id: data.id, name: data.name } });
  }

  const posts = Array.isArray(payload.posts) ? payload.posts.slice(0, 5) : [];
  if (!posts.length) return json({ error: "Nenhuma publicação recebida." }, 400);

  const results: Array<Record<string, unknown>> = [];
  for (const post of posts) {
    const imageUrl = String(post.image_url || "");
    const caption = String(post.message || "").slice(0, 6000);
    const publishDate = new Date(String(post.publish_at || ""));
    if (!imageUrl.startsWith("https://") || !caption || Number.isNaN(publishDate.getTime())) {
      results.push({ product_id: post.product_id, success: false, error: "Dados incompletos." });
      continue;
    }
    if (publishDate.getTime() < Date.now() + 10 * 60 * 1000) {
      results.push({ product_id: post.product_id, success: false, error: "O horário precisa estar pelo menos 10 minutos no futuro." });
      continue;
    }

    const form = new URLSearchParams({
      url: imageUrl,
      caption,
      published: "false",
      scheduled_publish_time: String(Math.floor(publishDate.getTime() / 1000)),
      unpublished_content_type: "SCHEDULED",
      access_token: pageToken,
    });
    const response = await fetch(
      `https://graph.facebook.com/v26.0/${encodeURIComponent(pageId)}/photos`,
      { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form },
    );
    const data = await response.json();
    results.push(response.ok && !data.error
      ? { product_id: post.product_id, success: true, post_id: data.post_id || data.id, publish_at: publishDate.toISOString() }
      : { product_id: post.product_id, success: false, error: data.error?.message || "Falha ao programar." });
  }

  return json({ success: results.some((item) => item.success), results });
});
