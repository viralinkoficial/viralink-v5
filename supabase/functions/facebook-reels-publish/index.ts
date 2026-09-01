import { createClient } from "https://esm.sh/@supabase/supabase-js@2.57.4";

const GRAPH_VERSION = "v26.0";
const ALLOWED_RIGHTS = new Set(["owned", "licensed", "public_domain", "official_remix"]);

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });

async function graphPost(path: string, values: Record<string, string>) {
  const body = new URLSearchParams(values);
  const response = await fetch(`https://graph.facebook.com/${GRAPH_VERSION}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error?.message || "Falha na API da Meta.");
  }
  return data;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Método não permitido." }, 405);

  const authHeader = req.headers.get("Authorization") || "";
  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  const ceoEmail = (Deno.env.get("CEO_EMAIL") || "").toLowerCase();
  const pageId = Deno.env.get("FACEBOOK_PAGE_ID") || "";
  const pageToken = Deno.env.get("FACEBOOK_PAGE_ACCESS_TOKEN") || "";

  if (!authHeader.startsWith("Bearer ")) return json({ error: "Faça login como CEO." }, 401);
  if (!supabaseUrl || !anonKey) return json({ error: "Supabase não configurado." }, 500);

  const supabase = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: { user }, error: userError } = await supabase.auth.getUser();
  if (userError || !user) return json({ error: "Sessão inválida ou expirada." }, 401);
  if (!ceoEmail || String(user.email || "").toLowerCase() !== ceoEmail) {
    return json({ error: "Somente o CEO pode publicar Reels." }, 403);
  }

  let payload: Record<string, unknown>;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "JSON inválido." }, 400);
  }

  if (payload.action === "status") {
    if (!pageId || !pageToken) {
      return json({
        configured: false,
        destination: "facebook_page",
        error: "Defina FACEBOOK_PAGE_ID e FACEBOOK_PAGE_ACCESS_TOKEN nos segredos do Supabase.",
      }, 503);
    }
    const url = new URL(`https://graph.facebook.com/${GRAPH_VERSION}/${encodeURIComponent(pageId)}`);
    url.searchParams.set("fields", "id,name");
    url.searchParams.set("access_token", pageToken);
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok || data.error) {
      return json({ configured: false, error: data.error?.message || "Falha ao consultar a Página." }, 502);
    }
    return json({ configured: true, destination: "facebook_page", page: { id: data.id, name: data.name } });
  }

  const mediaUrl = String(payload.media_url || "");
  const description = String(payload.description || "").trim().slice(0, 5000);
  const rightsBasis = String(payload.rights_basis || "");
  const sourceUrl = String(payload.source_url || "");
  const permissionReference = String(payload.permission_reference || "").trim();

  if (!mediaUrl.startsWith("https://")) {
    return json({ error: "media_url precisa ser HTTPS e apontar para um vídeo acessível pela Meta." }, 400);
  }
  if (!description) return json({ error: "A descrição do Reel é obrigatória." }, 400);
  if (!ALLOWED_RIGHTS.has(rightsBasis)) {
    return json({ error: "rights_basis deve ser owned, licensed, public_domain ou official_remix." }, 400);
  }
  if (rightsBasis !== "owned" && (!sourceUrl.startsWith("https://") || !permissionReference)) {
    return json({
      error: "Conteúdo reutilizado exige source_url e permission_reference que comprovem licença, domínio público ou remix autorizado.",
    }, 400);
  }

  if (payload.dry_run === true) {
    return json({
      valid: true,
      destination: "facebook_page",
      rights: { basis: rightsBasis, source_url: sourceUrl || null, permission_reference: permissionReference || null },
      note: "Validação concluída; nenhum Reel foi publicado.",
    });
  }

  if (!pageId || !pageToken) {
    return json({
      configured: false,
      error: "Defina FACEBOOK_PAGE_ID e FACEBOOK_PAGE_ACCESS_TOKEN nos segredos do Supabase.",
    }, 503);
  }

  try {
    const start = await graphPost(`${encodeURIComponent(pageId)}/video_reels`, {
      upload_phase: "start",
      access_token: pageToken,
    });

    const videoId = String(start.video_id || "");
    const uploadUrl = String(start.upload_url || "");
    if (!videoId || !uploadUrl.startsWith("https://")) {
      throw new Error("A Meta não retornou uma sessão de upload válida.");
    }

    const uploadResponse = await fetch(uploadUrl, {
      method: "POST",
      headers: {
        Authorization: `OAuth ${pageToken}`,
        file_url: mediaUrl,
      },
    });
    const uploadData = await uploadResponse.json();
    if (!uploadResponse.ok || uploadData.error) {
      throw new Error(uploadData.error?.message || "Falha ao enviar o vídeo para a Meta.");
    }

    const finish = await graphPost(`${encodeURIComponent(pageId)}/video_reels`, {
      upload_phase: "finish",
      video_id: videoId,
      video_state: "PUBLISHED",
      description,
      access_token: pageToken,
    });

    return json({
      success: true,
      destination: "facebook_page",
      video_id: videoId,
      published: finish.success === true,
      rights: { basis: rightsBasis, source_url: sourceUrl || null, permission_reference: permissionReference || null },
    });
  } catch (error) {
    return json({ success: false, error: error instanceof Error ? error.message : "Falha ao publicar o Reel." }, 502);
  }
});
