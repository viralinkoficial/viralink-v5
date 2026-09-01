const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

async function verifyMetaSignature(req: Request, rawBody: string) {
  const appSecret = Deno.env.get("META_APP_SECRET");
  const signatureHeader = req.headers.get("x-hub-signature-256");

  // A assinatura fica obrigatória quando META_APP_SECRET estiver configurado.
  if (!appSecret) return true;
  if (!signatureHeader?.startsWith("sha256=")) return false;

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(appSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const digest = await crypto.subtle.sign("HMAC", key, encoder.encode(rawBody));
  const expected = `sha256=${Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")}`;

  if (expected.length !== signatureHeader.length) return false;

  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ signatureHeader.charCodeAt(i);
  }
  return diff === 0;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);

  if (req.method === "GET") {
    const mode = url.searchParams.get("hub.mode");
    const token = url.searchParams.get("hub.verify_token");
    const challenge = url.searchParams.get("hub.challenge");
    const verifyToken = Deno.env.get("WHATSAPP_VERIFY_TOKEN");

    if (!verifyToken) {
      console.error("WHATSAPP_VERIFY_TOKEN não configurado");
      return new Response("Webhook não configurado", { status: 500 });
    }

    if (mode === "subscribe" && token === verifyToken && challenge) {
      console.log("Webhook do WhatsApp verificado com sucesso");
      return new Response(challenge, {
        status: 200,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    return new Response("Verificação recusada", { status: 403 });
  }

  if (req.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { Allow: "GET, POST" },
    });
  }

  const rawBody = await req.text();

  if (!(await verifyMetaSignature(req, rawBody))) {
    console.warn("Assinatura Meta inválida");
    return new Response("Assinatura inválida", { status: 401 });
  }

  let payload: any;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return json({ ok: false, error: "JSON inválido" }, 400);
  }

  if (payload?.object !== "whatsapp_business_account") {
    return json({ ok: true, ignored: true });
  }

  for (const entry of payload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change?.value ?? {};

      for (const status of value.statuses ?? []) {
        console.log("WhatsApp status", {
          message_id: status.id ?? null,
          status: status.status ?? null,
          timestamp: status.timestamp ?? null,
        });
      }

      for (const message of value.messages ?? []) {
        console.log("WhatsApp message received", {
          message_id: message.id ?? null,
          type: message.type ?? null,
          timestamp: message.timestamp ?? null,
        });
      }
    }
  }

  return json({ ok: true });
});
