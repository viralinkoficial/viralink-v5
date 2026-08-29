const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Content-Type": "application/json",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: corsHeaders });

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  try {
    if (req.method !== "POST") return json({ success: false, error: "Método não permitido." }, 405);

    const accessToken = Deno.env.get("INSTAGRAM_ACCESS_TOKEN");
    const instagramUserId = Deno.env.get("INSTAGRAM_USER_ID");
    if (!accessToken || !instagramUserId) {
      return json({ success: false, error: "Credenciais do Instagram não configuradas." }, 500);
    }

    const payload = await req.json().catch(() => ({}));
    const imageUrl = String(payload.image_url || "").trim();
    const caption = String(payload.caption || "").slice(0, 2200);

    if (!imageUrl.startsWith("https://")) {
      return json({ success: false, error: "A imagem precisa ter um endereço HTTPS público." }, 400);
    }

    const createResponse = await fetch(
      `https://graph.facebook.com/v23.0/${instagramUserId}/media`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: imageUrl,
          caption,
          access_token: accessToken,
        }),
      },
    );
    const createData = await createResponse.json().catch(() => ({}));

    if (!createResponse.ok || !createData.id) {
      const detail = createData?.error?.error_user_msg ||
        createData?.error?.message ||
        "O Instagram recusou a imagem ou a legenda.";
      return json({ success: false, error: detail }, 400);
    }

    const publishResponse = await fetch(
      `https://graph.facebook.com/v23.0/${instagramUserId}/media_publish`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          creation_id: createData.id,
          access_token: accessToken,
        }),
      },
    );
    const publishData = await publishResponse.json().catch(() => ({}));

    if (!publishResponse.ok || !publishData.id) {
      const detail = publishData?.error?.error_user_msg ||
        publishData?.error?.message ||
        "O Instagram não concluiu a publicação.";
      return json({ success: false, error: detail }, 400);
    }

    return json({ success: true, id: publishData.id });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erro interno na publicação.";
    return json({ success: false, error: message }, 500);
  }
});
