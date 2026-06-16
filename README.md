# Market Pulse Dashboard

Ein kostenlos hostbares Aktienmarkt-Dashboard für GitHub Pages.

## Beobachtete Produkte

| Dashboard-Name | Daten-Proxy | Stooq-Symbol |
|---|---|---|
| MSCI World | iShares Core MSCI World UCITS ETF | `iwda.uk` |
| MSCI Emerging Markets | iShares Core MSCI EM IMI UCITS ETF | `eimi.uk` |
| MSCI World Small Caps | iShares MSCI World Small Cap UCITS ETF | `iusn.de` |
| Alphabet | Alphabet Inc. Class A | `googl.us` |
| Gold | Gold Spotpreis USD/oz | `xauusd` |

## Was das Dashboard zeigt

- letzte verfügbare Kurse
- Tagesbewegung
- 5-Tage-, 1-Monats-, YTD- und 1-Jahres-Performance
- 30-Tage-Volatilität
- 90-Tage-Sparkline
- Markt-Kompass: Risk-on / Neutral / Risk-off
- stärkster und schwächster Wert der Watchlist

## Lokal testen

```bash
python scripts/update_data.py
python -m http.server 8000
```

Dann öffnen: <http://localhost:8000>

## Auf GitHub Pages veröffentlichen

1. Neues öffentliches GitHub-Repository erstellen, z. B. `market-pulse-dashboard`.
2. Alle Dateien aus diesem Ordner in das Repository hochladen.
3. In GitHub: **Settings → Pages** öffnen.
4. Bei **Build and deployment** als Source **Deploy from a branch** wählen.
5. Branch: `main`, Folder: `/root` auswählen und speichern.
6. In **Actions** den Workflow **Update dashboard data** einmal manuell starten: **Run workflow**.
7. Nach dem ersten erfolgreichen Lauf ist die Seite typischerweise erreichbar unter:

```text
https://DEIN-GITHUB-NAME.github.io/market-pulse-dashboard/
```

## Automatische Aktualisierung

Die Datei `.github/workflows/update-dashboard.yml` aktualisiert `data/dashboard-data.json` automatisch um 04:00 und 16:00 UTC.
Das entspricht während der österreichischen Sommerzeit 06:00 und 18:00 Uhr.

Wichtig: GitHub Actions verwendet bei `cron` UTC. Für exakte Winterzeit 06:00/18:00 CET ändere den Cron auf:

```yaml
- cron: "0 5,17 * * *"
```

## Hinweis

Die Daten können verzögert sein. Dieses Dashboard ist keine Anlageberatung und dient nur der privaten Marktübersicht.
