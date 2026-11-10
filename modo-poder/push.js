// Modo Poder — Web Push subscriptions (Android PWA)
(() => {
  const SUPABASE_URL = "https://pfbzdktlfdotsgfarhel.supabase.co";
  const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_nXkBQxBy18WoOH21matfzg_CQdDCvLi";
  const VAPID_PUBLIC_KEY = "BF2Op5CuVIpHbKaTIFHMyWYx1vdmHhIbendkQ0-cBG7eIhkl8dYpbNX0sdmqvOSqj1eVCvWbXkxWwl9inMcjHUU";
  const statusEl = document.getElementById("pushStatus");
  const button = document.getElementById("pushEnableBtn");
  if (!button || !window.supabase) return;
  const client = window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
  });
  function setStatus(message) { if (statusEl) statusEl.textContent = message; }
  function base64UrlToUint8Array(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map(char => char.charCodeAt(0)));
  }
  async function enablePush() {
    button.disabled = true;
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        throw new Error("Este navegador não oferece notificações push. Instale o Modo Poder pelo Chrome no Android.");
      }
      const { data: { session }, error: sessionError } = await client.auth.getSession();
      if (sessionError) throw sessionError;
      if (!session?.user) throw new Error("Entre na sua conta do Modo Poder antes de ativar os alarmes.");
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Permissão de notificações não concedida. Ative-a nas configurações do Android.");
      const registration = await navigator.serviceWorker.ready;
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64UrlToUint8Array(VAPID_PUBLIC_KEY)
        });
      }
      const json = subscription.toJSON();
      const { error } = await client.from("mp_push_subscriptions").upsert({
        user_id: session.user.id,
        endpoint: json.endpoint,
        p256dh: json.keys?.p256dh,
        auth: json.keys?.auth,
        updated_at: new Date().toISOString()
      }, { onConflict: "endpoint" });
      if (error) throw error;
      setStatus("Inscrição deste aparelho salva. O envio pelo servidor será ativado na próxima configuração.");
      button.textContent = "Alarmes ativados";
    } catch (error) {
      setStatus(error?.message || "Não foi possível ativar os alarmes.");
      button.disabled = false;
    }
  }
  button.addEventListener("click", enablePush);
})();
