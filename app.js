const DATA_URL = './data/dashboard-data.json';
const assetGrid = document.querySelector('#asset-grid');
const tableBody = document.querySelector('#performance-table tbody');
const refreshButton = document.querySelector('#refresh-button');

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function fmtNumber(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return new Intl.NumberFormat('de-AT', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  }).format(value);
}

function changeClass(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'neutral';
  if (value > 0.05) return 'positive';
  if (value < -0.05) return 'negative';
  return 'neutral';
}

function sparkline(points) {
  if (!points || points.length < 2) return '<svg class="sparkline"></svg>';
  const values = points.map(p => p.close).filter(v => typeof v === 'number');
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 260;
  const height = 72;
  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - ((p.close - min) / range) * (height - 10) - 5;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = points.at(-1)?.close ?? 0;
  const first = points[0]?.close ?? 0;
  const cls = changeClass(((last / first) - 1) * 100);
  const stroke = cls === 'positive' ? 'var(--positive)' : cls === 'negative' ? 'var(--negative)' : 'var(--neutral)';
  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="90-Tage-Sparkline">
    <polyline fill="none" stroke="${stroke}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${coords}" />
  </svg>`;
}

function renderReason(asset) {
  const explanation = asset.explanation || {};
  const bullets = Array.isArray(explanation.bullets) ? explanation.bullets : [];
  const headlines = Array.isArray(explanation.headlines) ? explanation.headlines : [];
  const themes = Array.isArray(explanation.themes) ? explanation.themes : [];
  const confidence = explanation.confidence || 'niedrig';

  return `<div class="reason-box">
    <div class="reason-head">
      <span>Begründung / Quellenlage</span>
      <em>Qualität: ${escapeHtml(confidence)}</em>
    </div>
    ${themes.length ? `<div class="theme-row">${themes.map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>` : ''}
    <p>${escapeHtml(explanation.summary || 'Noch keine Einordnung verfügbar.')}</p>
    ${bullets.length ? `<ul>${bullets.slice(0, 4).map(b => `<li>${escapeHtml(b)}</li>`).join('')}</ul>` : ''}
    ${headlines.length ? `<div class="headline-list">
      <span class="small-label">Quellen</span>
      ${headlines.slice(0, 3).map(h => `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener noreferrer">
        ${escapeHtml(h.title)}
        <small>${escapeHtml(h.source || 'Quelle')} ${h.published ? '· ' + escapeHtml(h.published) : ''}</small>
      </a>`).join('')}
    </div>` : '<div class="no-headlines">Keine verwertbaren Schlagzeilen gefunden – keine Ursache wird behauptet.</div>'}
  </div>`;
}

function renderAssetCard(asset) {
  const dailyCls = changeClass(asset.change_pct);
  return `<article class="asset-card">
    <div class="asset-top">
      <div>
        <h3>${escapeHtml(asset.name)}</h3>
        <div class="ticker">${escapeHtml(asset.symbol)} · ${escapeHtml(asset.currency || '')} · Stand ${escapeHtml(asset.last_date || '–')}</div>
      </div>
      <div class="change ${dailyCls}">${fmtPct(asset.change_pct)}</div>
    </div>
    <div class="price"><strong>${fmtNumber(asset.last_close, asset.price_decimals ?? 2)}</strong><span>${escapeHtml(asset.currency || '')}</span></div>
    ${sparkline(asset.sparkline)}
    <div class="metric-row">
      <div class="metric"><span>5 Tage</span><strong>${fmtPct(asset.change_5d_pct)}</strong></div>
      <div class="metric"><span>1 Monat</span><strong>${fmtPct(asset.change_1m_pct)}</strong></div>
      <div class="metric"><span>YTD</span><strong>${fmtPct(asset.ytd_pct)}</strong></div>
    </div>
    ${renderReason(asset)}
  </article>`;
}

function renderSummary(assets) {
  const valid = assets.filter(a => typeof a.change_pct === 'number');
  const positives = valid.filter(a => a.change_pct > 0).length;
  const avg = valid.reduce((sum, a) => sum + a.change_pct, 0) / (valid.length || 1);
  const sorted = [...valid].sort((a, b) => b.change_pct - a.change_pct);
  const best = sorted[0];
  const worst = sorted.at(-1);

  let mood = 'Neutral';
  let comment = 'Gemischtes Bild. Kein klarer Risiko-Impuls über die Watchlist.';
  if (avg > 0.35 && positives >= 4) {
    mood = 'Risk-on';
    comment = 'Breite Stärke: Die meisten beobachteten Werte liegen im Plus.';
  } else if (avg < -0.35 && positives <= 1) {
    mood = 'Risk-off';
    comment = 'Breite Schwäche: Die Watchlist zeigt überwiegend Abwärtsdruck.';
  }

  document.querySelector('#market-mood').textContent = mood;
  document.querySelector('#market-comment').textContent = comment;
  document.querySelector('#positive-count').textContent = `${positives}/${valid.length}`;
  document.querySelector('#best-asset').textContent = best ? best.name : '–';
  document.querySelector('#best-asset-sub').textContent = best ? fmtPct(best.change_pct) : '–';
  document.querySelector('#worst-asset').textContent = worst ? worst.name : '–';
  document.querySelector('#worst-asset-sub').textContent = worst ? fmtPct(worst.change_pct) : '–';
}

function renderTable(assets) {
  tableBody.innerHTML = assets.map(a => {
    const cells = [a.change_pct, a.change_5d_pct, a.change_1m_pct, a.ytd_pct, a.change_1y_pct, a.volatility_30d_pct];
    return `<tr>
      <td><strong>${escapeHtml(a.name)}</strong><br><span class="asset-meta">${escapeHtml(a.symbol)}</span></td>
      ${cells.map(v => `<td class="${changeClass(v)}">${fmtPct(v)}</td>`).join('')}
    </tr>`;
  }).join('');
}

function renderErrors(errors) {
  const box = document.querySelector('#source-errors');
  if (!box) return;
  if (!Array.isArray(errors) || !errors.length) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `<details class="warning-box"><summary>Hinweis: ${errors.length} Daten-/Nachrichtenquelle(n) waren nicht erreichbar</summary>
    <ul>${errors.slice(0, 8).map(e => `<li>${escapeHtml(e.symbol || 'Quelle')}: ${escapeHtml(e.stage || 'Abruf')} – ${escapeHtml(e.error || '')}</li>`).join('')}</ul>
  </details>`;
}

async function loadDashboard() {
  assetGrid.innerHTML = '<div class="error">Dashboard-Daten werden geladen...</div>';
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const assets = data.assets || [];

    document.querySelector('#updated-at').textContent = data.generated_at_vienna || data.generated_at_utc || '–';
    document.querySelector('#data-source').textContent = `Datenquelle: ${data.source || 'Yahoo Finance'}`;
    renderErrors(data.errors || []);

    if (!assets.length || data.is_sample) {
      assetGrid.innerHTML = '<div class="error">Noch keine Live-Daten vorhanden. Starte in GitHub Actions den Workflow „Update dashboard data“ manuell oder warte auf die nächste geplante Aktualisierung.</div>';
      renderSummary([]);
      renderTable([]);
      return;
    }

    assetGrid.innerHTML = assets.map(renderAssetCard).join('');
    renderSummary(assets);
    renderTable(assets);
  } catch (error) {
    assetGrid.innerHTML = `<div class="error">Daten konnten nicht geladen werden: ${escapeHtml(error.message)}</div>`;
  }
}

refreshButton.addEventListener('click', loadDashboard);
loadDashboard();
