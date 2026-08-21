import { createClient } from "https://esm.sh/@supabase/supabase-js@2.57.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-worker-secret, content-type",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json" } });

type QueueItem = {
  id: number;
  product_id: string;
  product_name: string;
  channel: string;
  scheduled_for: string;
  status: string;
  attempts: number;
  payload: Record<string, unknown>;
};

class PauseError extends Error {}

function required(name: string) {
  const value = Deno.env.get(name) || "";
  if (!value) throw new PauseError("Configuração ausente: " + name);
  return value;
}

function caption(payload: Record<string, unknown>) {
  const name = String(payload.name || "Achadinho");
  const description = String(payload.description || "").slice(0, 1400);
  const price = payload.price == null ? "" : "\n💰 R$ " + String(payload.price).replace(".", ",");
  const link = String(payload.affiliate_url || "");
  return (name + "\n\n" + description + price + "\n\n👉 Veja a oferta: " + link + "\n\n#achadinhos #oferta #viralink").slice(0, 2100);
}

async function graphPost(path: string, values: Record<string, string>) {
  const version = Deno.env.get("META_GRAPH_VERSION") || "v23.0";
  const response = await fetch("https://graph.facebook.com/" + version + "/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(values),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error("Instagram: " + (data.error?.message || response.status));
  return data;
}

async function publishInstagram(item: QueueItem) {
  const accountId = Deno.env.get("INSTAGRAM_BUSINESS_ID") || Deno.env.get("INSTAGRAM_USER_ID") || "";\n  if (!accountId) throw new PauseError("Configuração ausente: INSTAGRAM_BUSINESS_ID ou INSTAGRAM_USER_ID");
  const accessToken = required("INSTAGRAM_ACCESS_TOKEN");
  const imageUrl = String(item.payload.image_url || "");
  if (!imageUrl.startsWith("https://")) throw new PauseError("Imagem HTTPS ausente.");
  const container = await graphPost(accountId + "/media", {
    image_url: imageUrl,
    caption: caption(item.payload),
    access_token: accessToken,
  });
  if (!container.id) throw new Error("Instagram não criou o contêiner.");
  const published = await graphPost(accountId + "/media_publish", {
    creation_id: String(container.id),
    access_token: accessToken,
  });
  if (!published.id) throw new Error("Instagram não confirmou a publicação.");
  return String(published.id);
}

async function youtubeAccessToken() {
  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: required("YOUTUBE_CLIENT_ID"),
      client_secret: required("YOUTUBE_CLIENT_SECRET"),
      refresh_token: required("YOUTUBE_REFRESH_TOKEN"),
      grant_type: "refresh_token",
    }),
  });
  const data = await response.json();
  if (!response.ok || !data.access_token) throw new Error("YouTube OAuth: " + (data.error_description || data.error || response.status));
  return String(data.access_token);
}

async function publishYouTube(item: QueueItem) {
  const videoUrl = String(item.payload.video_url || "");
  if (!videoUrl.startsWith("https://")) throw new PauseError("Vídeo HTTPS ainda não preparado para este item.");
  const videoResponse = await fetch(videoUrl);
  if (!videoResponse.ok) throw new Error("Não foi possível baixar o vídeo: HTTP " + videoResponse.status);
  const size = Number(videoResponse.headers.get("content-length") || 0);
  if (size > 50 * 1024 * 1024) throw new PauseError("Vídeo acima do limite seguro de 50 MB.");
  const mime = videoResponse.headers.get("content-type") || "video/mp4";
  if (!mime.startsWith("video/")) throw new PauseError("O arquivo informado não é um vídeo.");
  const bytes = await videoResponse.arrayBuffer();
  if (bytes.byteLength > 50 * 1024 * 1024) throw new PauseError("Vídeo acima do limite seguro de 50 MB.");

  const token = await youtubeAccessToken();
  const title = String(item.payload.name || item.product_name || "Achadinho").slice(0, 100);
  const description = caption(item.payload);
  const start = await fetch("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json; charset=UTF-8",
      "X-Upload-Content-Length": String(bytes.byteLength),
      "X-Upload-Content-Type": mime,
    },
    body: JSON.stringify({
      snippet: { title, description, tags: ["achadinhos", "oferta", "viralink"], categoryId: "22" },
      status: { privacyStatus: "public", selfDeclaredMadeForKids: false },
    }),
  });
  if (!start.ok) throw new Error("YouTube iniciou com erro: HTTP " + start.status + " — " + await start.text());
  const uploadUrl = start.headers.get("location");
  if (!uploadUrl) throw new Error("YouTube não retornou a URL de envio.");
  const upload = await fetch(uploadUrl, {
    method: "PUT",
    headers: { Authorization: "Bearer " + token, "Content-Type": mime, "Content-Length": String(bytes.byteLength) },
    body: bytes,
  });
  const data = await upload.json().catch(() => ({}));
  if (!upload.ok || !data.id) throw new Error("YouTube não confirmou o vídeo: HTTP " + upload.status);
  return String(data.id);
}

async function publish(item: QueueItem) {
  if (item.channel === "instagram") return await publishInstagram(item);
  if (item.channel === "youtube") return await publishYouTube(item);
  throw new PauseError("Canal ainda sem executor automático: " + item.channel);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Método não permitido." }, 405);

  const expected = Deno.env.get("CAMPAIGN_WORKER_SECRET") || "";
  const received = req.headers.get("x-worker-secret") || "";
  if (!expected || received !== expected) return json({ error: "Executor não autorizado." }, 401);

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return json({ error: "Servidor não configurado." }, 500);
  const admin = createClient(supabaseUrl, serviceKey);

  const { data: due, error: dueError } = await admin.from("campaign_queue")
    .select("id,product_id,product_name,channel,scheduled_for,status,attempts,payload")
    .in("status", ["pending", "failed"])
    .lt("attempts", 3)
    .lte("scheduled_for", new Date().toISOString())
    .order("scheduled_for", { ascending: true })
    .limit(5);
  if (dueError) return json({ error: dueError.message }, 500);

  const results: Array<Record<string, unknown>> = [];
  for (const item of (due || []) as QueueItem[]) {
    const attempt = Number(item.attempts || 0) + 1;
    const { data: claimed, error: claimError } = await admin.from("campaign_queue")
      .update({ status: "processing", attempts: attempt, error_message: null })
      .eq("id", item.id)
      .in("status", ["pending", "failed"])
      .select("id")
      .maybeSingle();
    if (claimError || !claimed) {
      results.push({ id: item.id, status: "ignored", reason: "já processado por outro executor" });
      continue;
    }

    try {
      const externalId = await publish(item);
      const { error } = await admin.from("campaign_queue").update({
        status: "published",
        external_id: externalId,
        error_message: null,
      }).eq("id", item.id).eq("status", "processing");
      if (error) throw error;
      results.push({ id: item.id, channel: item.channel, status: "published", external_id: externalId });
    } catch (error) {
      const paused = error instanceof PauseError;
      const message = error instanceof Error ? error.message.slice(0, 500) : "Erro desconhecido.";
      await admin.from("campaign_queue").update({
        status: paused ? "paused" : "failed",
        error_message: message,
      }).eq("id", item.id).eq("status", "processing");
      results.push({ id: item.id, channel: item.channel, status: paused ? "paused" : "failed", error: message });
    }
  }

  return json({ success: true, processed: results.length, results });
});
