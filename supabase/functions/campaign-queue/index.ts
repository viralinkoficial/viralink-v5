import { createClient } from "https://esm.sh/@supabase/supabase-js@2.57.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json" } });

const CHANNELS: Record<string, number[]> = {
  instagram: [10, 14, 18],
  youtube: [9, 12, 16, 20],
  facebook: [9, 12, 15, 18, 21],
  pinterest: [9, 12, 15, 18, 21],
  blogger: [9, 12, 16, 18, 21],
  tiktok: [11, 17, 21],
  whatsapp: [10, 16, 20],
};
const VALID_CHANNELS = new Set(Object.keys(CHANNELS));

function nextSlots(hours: number[], count: number) {
  const now = new Date();
  const belemWall = new Date(now.getTime() - 3 * 60 * 60 * 1000);
  const slots: string[] = [];
  for (let day = 0; day < 10 && slots.length < count; day++) {
    for (const hour of hours) {
      const wall = new Date(Date.UTC(
        belemWall.getUTCFullYear(),
        belemWall.getUTCMonth(),
        belemWall.getUTCDate() + day,
        hour, 0, 0, 0,
      ));
      const instant = new Date(wall.getTime() + 3 * 60 * 60 * 1000);
      if (instant.getTime() > now.getTime() + 12 * 60 * 1000) slots.push(instant.toISOString());
      if (slots.length === count) break;
    }
  }
  return slots;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return json({ error: "Método não permitido." }, 405);

  const authHeader = req.headers.get("Authorization") || "";
  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const ceoEmail = (Deno.env.get("CEO_EMAIL") || "").toLowerCase();
  if (!authHeader.startsWith("Bearer ")) return json({ error: "Faça login como CEO." }, 401);
  if (!supabaseUrl || !anonKey || !serviceKey) return json({ error: "Servidor não configurado." }, 500);

  const userClient = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: authHeader } } });
  const { data: { user }, error: authError } = await userClient.auth.getUser();
  if (authError || !user) return json({ error: "Sessão inválida ou expirada." }, 401);
  if (!ceoEmail || String(user.email || "").toLowerCase() !== ceoEmail) {
    return json({ error: "Somente o CEO pode controlar o Robô Central." }, 403);
  }

  const admin = createClient(supabaseUrl, serviceKey);
  let body: { action?: string; channels?: string[]; id?: number } = {};
  try { body = await req.json(); } catch { return json({ error: "JSON inválido." }, 400); }
  const action = body.action || "status";

  if (action === "status") {
    const { data, error } = await admin.from("campaign_queue")
      .select("id,product_id,product_name,channel,scheduled_for,status,attempts,error_message,external_id,created_at")
      .order("scheduled_for", { ascending: true }).limit(100);
    if (error) return json({ configured: false, error: error.message }, 503);
    const counts = (data || []).reduce((acc: Record<string, number>, row) => {
      acc[row.status] = (acc[row.status] || 0) + 1;
      return acc;
    }, {});
    return json({ configured: true, queue: data || [], counts });
  }

  if (action === "plan") {
    const channels = [...new Set((body.channels || []).filter((ch) => VALID_CHANNELS.has(ch)))];
    if (!channels.length) return json({ error: "Selecione pelo menos um canal." }, 400);

    const { data: products, error: productError } = await admin.from("products")
      .select("id,name,description,price,platform,category,image_url,affiliate_url,status")
      .eq("status", "active").order("created_at", { ascending: false });
    if (productError) return json({ error: productError.message }, 500);
    const eligible = (products || []).filter((p) =>
      String(p.image_url || "").startsWith("https://") &&
      String(p.affiliate_url || "").startsWith("https://")
    );
    if (!eligible.length) return json({ error: "Não há produtos ativos com imagem e link válidos." }, 409);

    const since = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
    const { data: recent } = await admin.from("campaign_queue")
      .select("product_id,channel").gte("created_at", since).neq("status", "cancelled");
    const usedByChannel = new Map<string, Set<string>>();
    for (const row of recent || []) {
      if (!usedByChannel.has(row.channel)) usedByChannel.set(row.channel, new Set());
      usedByChannel.get(row.channel)?.add(String(row.product_id));
    }

    const jobs: Array<Record<string, unknown>> = [];
    const usedThisPlan = new Set<string>();
    let cursor = 0;
    for (const channel of channels) {
      const hours = CHANNELS[channel];
      const slots = nextSlots(hours, hours.length);
      const channelUsed = usedByChannel.get(channel) || new Set<string>();
      for (const scheduledFor of slots) {
        let picked = null;
        for (let attempt = 0; attempt < eligible.length; attempt++) {
          const candidate = eligible[(cursor + attempt) % eligible.length];
          const id = String(candidate.id);
          if (!channelUsed.has(id) && !usedThisPlan.has(id)) {
            picked = candidate;
            cursor = (cursor + attempt + 1) % eligible.length;
            break;
          }
        }
        if (!picked) break;
        const productId = String(picked.id);
        channelUsed.add(productId);
        usedThisPlan.add(productId);
        jobs.push({
          product_id: productId,
          product_name: picked.name || "Produto",
          channel,
          scheduled_for: scheduledFor,
          status: "pending",
          attempts: 0,
          created_by: user.id,
          payload: {
            name: picked.name,
            description: picked.description,
            price: picked.price,
            platform: picked.platform,
            category: picked.category,
            image_url: picked.image_url,
            affiliate_url: picked.affiliate_url,
          },
        });
      }
    }
    if (!jobs.length) return json({ error: "Pausa segura: faltam produtos novos para os canais selecionados." }, 409);

    const { data, error } = await admin.from("campaign_queue")
      .upsert(jobs, { onConflict: "channel,scheduled_for", ignoreDuplicates: true })
      .select("id,product_name,channel,scheduled_for,status");
    if (error) return json({ error: error.message }, 500);
    return json({ success: true, planned: data || [], requested: jobs.length });
  }

  if (action === "retry_failed") {
    const { data, error } = await admin.from("campaign_queue")
      .update({ status: "pending", error_message: null })
      .eq("status", "failed").lt("attempts", 3)
      .select("id");
    if (error) return json({ error: error.message }, 500);
    return json({ success: true, retried: data?.length || 0 });
  }

  if ((action === "pause" || action === "cancel") && Number.isInteger(body.id)) {
    const status = action === "pause" ? "paused" : "cancelled";
    const { error } = await admin.from("campaign_queue").update({ status }).eq("id", body.id);
    if (error) return json({ error: error.message }, 500);
    return json({ success: true, id: body.id, status });
  }

  return json({ error: "Ação desconhecida." }, 400);
});
