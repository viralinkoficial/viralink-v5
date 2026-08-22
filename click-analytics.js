async function trackProductClick(productId, source) {
  source = source || 'vitrine';
  if (!productId) return;
  try {
    await fetch(SUPABASE_URL + '/rest/v1/product_clicks', {
      method: 'POST',
      keepalive: true,
      headers: {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
      },
      body: JSON.stringify({ product_id: String(productId), source: String(source).slice(0, 30) })
    });
  } catch (err) {
    console.warn('Clique não registrado:', err);
  }
}

async function loadClickAnalytics() {
  if (!document.getElementById('clickSummary')) return;
  if (!isCEO()) {
    $('clickSummary').textContent = 'Faça login como CEO para visualizar os cliques.';
    return;
  }
  try {
    const sessionResult = await sb.auth.getSession();
    const token = sessionResult.data.session && sessionResult.data.session.access_token;
    if (!token) return;
    const response = await fetch(
      SUPABASE_URL + '/rest/v1/product_clicks?select=product_id,source,clicked_at&order=clicked_at.desc&limit=5000',
      { headers: { 'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + token } }
    );
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const clicks = await response.json();
    const counts = {};
    const hours = Array(24).fill(0);
    clicks.forEach(function (click) {
      counts[click.product_id] = (counts[click.product_id] || 0) + 1;
      const date = new Date(click.clicked_at);
      if (!Number.isNaN(date.getTime())) hours[date.getHours()] += 1;
    });
    const today = new Date().toISOString().slice(0, 10);
    const todayCount = clicks.filter(function (click) {
      return String(click.clicked_at || '').slice(0, 10) === today;
    }).length;
    $('mClicks').textContent = clicks.length;
    $('mClicksToday').textContent = todayCount + ' hoje';
    $('goalClicks').textContent = clicks.length + '/500';
    $('barClicks').style.width = Math.min(100, Math.round(clicks.length / 500 * 100)) + '%';
    const ranking = Object.entries(counts).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 5);
    $('clickRanking').innerHTML = ranking.length ? ranking.map(function (entry) {
      const id = entry[0], count = entry[1];
      const product = products.find(function (item) { return String(item.id) === String(id); });
      const share = clicks.length ? Math.round(count / clicks.length * 100) : 0;
      return '<tr><td>' + escapeHtml(product ? product.name : 'Produto ' + id) + '</td><td><b>' + count + '</b></td><td>' + share + '%</td></tr>';
    }).join('') : '<tr><td colspan="3" class="muted">Nenhum clique registrado ainda.</td></tr>';
    const peak = Math.max.apply(null, hours);
    const peakHour = peak ? hours.indexOf(peak) : null;
    $('clickSummary').textContent = peakHour === null
      ? clicks.length + ' cliques registrados.'
      : clicks.length + ' cliques registrados · melhor horário: ' + String(peakHour).padStart(2, '0') + 'h';
  } catch (err) {
    console.warn(err);
    $('clickSummary').textContent = 'Ative a estrutura de cliques no Supabase para carregar os dados.';
  }
}
