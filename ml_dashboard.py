#!/usr/bin/env python3
"""
ML Dashboard - Scrapea varios modelos y genera un HTML interactivo

Vistas del HTML:
  1) Por moto: elegis modelo y ves el ranking 0km
  2) Por vendedor: elegis vendedor y ves todos sus modelos y su posicion

Uso:
    python ml_dashboard.py              # usa la lista MODELOS de abajo
    python ml_dashboard.py "yamaha mt 03" "yamaha nmax"   # modelos custom

Genera:
    ml_data.json        (datos crudos)
    ml_ranking.html     (dashboard, abrilo en el navegador)

Instalacion:
    pip install selenium webdriver-manager beautifulsoup4
"""

import sys
import io
import re
import time
import json
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager


# ====== CONFIGURACION ======
# Modelos a trackear por defecto
MODELOS = [
    # Yamaha
    "yamaha mt 03",
    "yamaha nmax",
    "yamaha fz 4.0",
    "yamaha fz 25",
    "yamaha fz-x",
    "yamaha xtz 125",
    "yamaha xtz 250",
    "yamaha ray 125",
    "yamaha fascino",
    "yamaha ttr 230",
    # Hero
    "hero hunk 150",
    # Siam
    "siam qu110",
    "siam trender 150",
    "siam nomad 150",
    # TVS
    "tvs raider 125",
]

# Tu cuenta (para resaltarla en el dashboard)
MI_CUENTA = "Me20250312103450"

KNOWN_SELLERS = [
    "Cycles", "Ciclofox", "Motolandia", "Patronelli", "Motoswift", "Antrax",
    "Marelli", "Motozuni", "Urquiza", "Moto Roma", "Motoroma", "BRM Bikes",
    "Mg Bikes", "Storero", "Automoto Lanus", "Bikecenter", "Ruta 3", "Oeste Motos",
    "Tamburrino", "Delisio", "Hot Motos", "Arizona", "Biaggi", "Yamacity",
    "Motolandia", "Antrax Motos",
]
# ===========================


def search_to_url(query: str) -> str:
    if query.startswith("http"):
        return query
    slug = query.lower().strip().replace(" ", "-")
    return f"https://listado.mercadolibre.com.ar/{slug}"


def get_driver(use_profile: bool = False):
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    if use_profile:
        # Usa tu perfil real de Chrome (logueado, con ubicacion) -> ML sirve los ads
        # IMPORTANTE: cerra Chrome antes de correr con --profile
        import os
        profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def guess_seller_from_title(title: str) -> str:
    low = title.lower()
    for s in KNOWN_SELLERS:
        if s.lower() in low:
            return s
    return ""


def get_seller_from_page(driver, url: str) -> str:
    try:
        driver.get(url)
        time.sleep(1.2)
        text = BeautifulSoup(driver.page_source, "html.parser").get_text("\n")
        m = re.search(r"Informaci[oó]n de la (?:tienda|concesionaria)\s*\n([^\n]+)", text)
        if m:
            return m.group(1).strip()
        return "(no visible)"
    except Exception:
        return "(no visible)"


def resolve_seller(title: str, location: str, seller_listado: str):
    """
    Devuelve (nombre_vendedor, necesita_visita).
    Minimiza visitas: usa listado verificado o titulo cuando se puede.
    """
    low = title.lower()
    loc = location.lower()

    # 1) Ciclofox VERIFICADO (aparece en el listado) = Pueyrredon
    if seller_listado and "ciclofox" in seller_listado.lower():
        return "Ciclofox Pueyrredon", False

    # 2) Ciclofox NO verificado en Tigre (titulo dice Ciclofox/Pacheco) = Pacheco
    if ("ciclofox" in low or "pacheco" in low) and "tigre" in loc:
        return "Ciclofox Pacheco", False

    # 3) Otra tienda verificada del listado
    if seller_listado:
        return normalize_seller(seller_listado), False

    # 4) Ciclofox en titulo sin ubicacion Tigre -> asumir Pacheco igual
    if "ciclofox" in low or "pacheco" in low:
        return "Ciclofox Pacheco", False

    # 5) Vendedor conocido en el titulo
    g = guess_seller_from_title(title)
    if g:
        return normalize_seller(g), False

    # 6) Desconocido -> hay que entrar a la publicacion
    return None, True


def scrape_modelo(driver, query: str, top_n: int = 20):
    url = search_to_url(query)
    driver.get(url)
    time.sleep(4)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    items = soup.select(".ui-search-layout__item")

    results = []
    for idx, item in enumerate(items[:top_n], 1):
        title_el = item.select_one(".poly-component__title")
        title = title_el.get_text(strip=True) if title_el else ""

        price_el = item.select_one(".andes-money-amount__fraction")
        price_raw = price_el.get_text(strip=True) if price_el else ""
        price_num = int(re.sub(r"[^\d]", "", price_raw)) if price_raw else 0

        location_el = item.select_one(".poly-component__location")
        location = location_el.get_text(strip=True) if location_el else ""

        attrs = [el.get_text(strip=True) for el in item.select(".poly-attributes_list__item")]
        is_0km = any(a.strip().lower() == "0 km" for a in attrs)

        link_el = item.select_one("a.poly-component__title, a[href*='MLA']")
        link = link_el["href"].split("#")[0] if link_el else ""

        # Vendedor del listado (solo tiendas oficiales/verificadas lo muestran)
        seller_el = item.select_one(".poly-component__seller")
        seller_listado = seller_el.get_text(strip=True) if seller_el else ""

        is_ad = "is_advertising=true" in (link_el["href"] if link_el else "") or \
                bool(item.select_one('[class*="advertising"]'))

        results.append({
            "title": title,
            "price_raw": "$" + price_raw if price_raw else "",
            "price_num": price_num,
            "location": location,
            "is_0km": is_0km,
            "seller_listado": seller_listado,
            "seller": "",
            "isAd": is_ad,
            "link": link,
        })

    # Filtrar solo 0km
    results = [r for r in results if r["is_0km"]]

    # Resolver vendedor SIN entrar (listado/titulo). Solo entra si es desconocido.
    visitas = 0
    for r in results:
        name, needs_visit = resolve_seller(r["title"], r["location"], r["seller_listado"])
        if needs_visit and r["link"]:
            real = get_seller_from_page(driver, r["link"])
            r["seller"] = normalize_seller(real) if real != "(no visible)" else "(no visible)"
            visitas += 1
        else:
            r["seller"] = name or "(no visible)"

    # Asignar rank limpio
    for rank, r in enumerate(results, 1):
        r["rank"] = rank

    return url, results, visitas


def normalize_seller(s: str) -> str:
    """Unifica variantes del mismo vendedor."""
    s = s.strip()
    low = s.lower()
    # Tu cuenta interna (codigo Me2025...) = Ciclofox Pacheco
    if low == MI_CUENTA.lower() or low.startswith("me2025"):
        return "Ciclofox Pacheco"
    if "ciclofox pacheco" in low: return "Ciclofox Pacheco"
    if "ciclofox pueyrredon" in low: return "Ciclofox Pueyrredon"
    if "ciclofox" in low: return "Ciclofox Pueyrredon"
    if "cycles" in low: return "Cycles Motoshop"
    if "motolandia" in low: return "Motolandia"
    if "moto roma" in low or "motoroma" in low: return "Moto Roma"
    if "urquiza" in low: return "Urquiza Motos"
    if "patronelli" in low: return "Patronelli"
    if "brm" in low: return "BRM Bikes"
    if "mg bikes" in low: return "Mg Bikes"
    if "yamacity" in low: return "Yamacity"
    if "automoto" in low or "automotolanus" in low: return "Automoto Lanus"
    if low == MI_CUENTA.lower(): return MI_CUENTA
    return s


def regenerar_html():
    """Reconstruye el HTML desde ml_data.json sin volver a scrapear."""
    with open("ml_data.json", encoding="utf-8") as f:
        payload = json.load(f)
    html = build_html(payload)
    for fname in ("ml_ranking.html", "index.html"):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
    print("Dashboard regenerado en ml_ranking.html e index.html (desde datos existentes)")


def main(modelos: list, use_profile: bool = False):
    print(f"\nScrapeando {len(modelos)} modelos...")
    if use_profile:
        print(">> Modo perfil: usando tu Chrome real (cerra Chrome antes). Captura ads.\n")
    else:
        print()
    driver = get_driver(use_profile=use_profile)
    data = {}
    try:
        for i, modelo in enumerate(modelos, 1):
            print(f"[{i}/{len(modelos)}] {modelo}...", end="", flush=True)
            try:
                url, res, visitas = scrape_modelo(driver, modelo)
                data[modelo] = {"url": url, "rows": res}
                print(f" OK ({len(res)} 0km, {visitas} visitas)")
            except Exception as e:
                print(f" ERROR: {e}")
                data[modelo] = {"url": search_to_url(modelo), "rows": []}
    finally:
        driver.quit()

    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mi_cuenta": MI_CUENTA,
        "modelos": data,
    }

    with open("ml_data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\nDatos guardados en ml_data.json")

    html = build_html(payload)
    for fname in ("ml_ranking.html", "index.html"):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
    print("Dashboard generado en ml_ranking.html e index.html")
    print("\nAbri ml_ranking.html en tu navegador.\n")


def build_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__DATA__", data_json)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ML Ranking Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f7; color: #1d1d1f; padding: 20px; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 28px; margin-bottom: 4px; }
  .meta { color: #86868b; font-size: 13px; margin-bottom: 20px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .tab { padding: 10px 20px; background: #fff; border: 1px solid #d2d2d7; border-radius: 10px;
         cursor: pointer; font-size: 15px; font-weight: 500; transition: all .15s; }
  .tab:hover { background: #f0f0f2; }
  .tab.active { background: #0071e3; color: #fff; border-color: #0071e3; }
  .controls { margin-bottom: 16px; }
  select { padding: 10px 14px; font-size: 15px; border: 1px solid #d2d2d7; border-radius: 10px;
           background: #fff; min-width: 260px; cursor: pointer; }
  .card { background: #fff; border-radius: 14px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
          margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 10px 12px; border-bottom: 2px solid #e8e8ed; color: #6e6e73;
       font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  td { padding: 11px 12px; border-bottom: 1px solid #f0f0f2; }
  tr:hover td { background: #fafafa; }
  .rank { font-weight: 700; color: #0071e3; width: 40px; }
  .ads { text-align: center; width: 50px; }
  .price { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px;
           font-weight: 600; }
  .badge-ad { background: #fff3cd; color: #856404; }
  .badge-plan { background: #e7f3ff; color: #0071e3; }
  .mine { background: #fff0f0 !important; }
  .mine td { font-weight: 600; }
  .mine .rank { color: #e3000f; }
  .tag-mine { background: #ffe0e0; color: #e3000f; }
  .puey { background: #eef7ff !important; }
  .puey td { font-weight: 600; }
  .puey .rank { color: #0066cc; }
  .seller-link { color: #0071e3; cursor: pointer; text-decoration: none; }
  .seller-link:hover { text-decoration: underline; }
  .summary { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { background: #fff; border-radius: 12px; padding: 14px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .stat .num { font-size: 26px; font-weight: 700; }
  .stat .lbl { font-size: 12px; color: #86868b; }
  .hidden { display: none; }
  a.pub { color: #1d1d1f; text-decoration: none; }
  a.pub:hover { color: #0071e3; text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>🏍️ ML Ranking Dashboard</h1>
  <div class="meta" id="meta"></div>

  <div class="tabs">
    <div class="tab active" data-view="moto" onclick="setView('moto')">Por Moto</div>
    <div class="tab" data-view="vendedor" onclick="setView('vendedor')">Por Vendedor</div>
  </div>

  <!-- VISTA POR MOTO -->
  <div id="view-moto">
    <div class="controls">
      <select id="sel-moto" onchange="renderMoto()"></select>
    </div>
    <div class="meta" id="moto-link"></div>
    <div class="summary" id="moto-summary"></div>
    <div class="card"><table id="tbl-moto"></table></div>
  </div>

  <!-- VISTA POR VENDEDOR -->
  <div id="view-vendedor" class="hidden">
    <div class="controls">
      <select id="sel-vendedor" onchange="renderVendedor()"></select>
      <select id="sel-vmarca" onchange="onMarcaChange()"></select>
      <select id="sel-vmodelo" onchange="renderVendedor()"></select>
    </div>
    <div class="summary" id="vendedor-summary"></div>
    <div class="card"><table id="tbl-vendedor"></table></div>
  </div>
</div>

<script>
const DATA = __DATA__;

document.getElementById('meta').textContent = 'Actualizado: ' + DATA.generated + ' · Solo 0km';

// ---- Helpers ----
function fmtPrice(r) {
  if (r.price_num && r.price_num < 1000000) {
    return '<span class="badge badge-plan">Plan ' + r.price_raw + '</span>';
  }
  return '<span class="price">' + (r.price_raw || '-') + '</span>';
}
const PACHECO = 'Ciclofox Pacheco';
const PUEYRREDON = 'Ciclofox Pueyrredon';
function isPacheco(seller) { return seller === PACHECO; }
function rowClass(seller) {
  if (seller === PACHECO) return 'mine';
  if (seller === PUEYRREDON) return 'puey';
  return '';
}

function rowsOf(m) { return (DATA.modelos[m] && DATA.modelos[m].rows) || []; }
function urlOf(m)  { return (DATA.modelos[m] && DATA.modelos[m].url) || ''; }

// ---- VISTA POR MOTO ----
function initMoto() {
  const sel = document.getElementById('sel-moto');
  Object.keys(DATA.modelos).forEach(m => {
    const o = document.createElement('option');
    o.value = m; o.textContent = m.toUpperCase();
    sel.appendChild(o);
  });
  renderMoto();
}
function renderMoto() {
  const m = document.getElementById('sel-moto').value;
  const rows = rowsOf(m);
  const url  = urlOf(m);
  const pacheco = rows.find(r => isPacheco(r.seller));

  // link de busqueda
  document.getElementById('moto-link').innerHTML =
    '🔎 Busqueda: <a href="' + url + '" target="_blank">' + url + '</a>';

  // summary
  const summary = document.getElementById('moto-summary');
  summary.innerHTML =
    stat(rows.length, '0km publicados') +
    stat(pacheco ? '#' + pacheco.rank : '—', 'Pos. Pacheco') +
    stat(new Set(rows.map(r => r.seller)).size, 'Vendedores distintos');

  // tabla
  let html = '<thead><tr><th>#</th><th>Ads</th><th>Vendedor</th><th>Precio</th><th>Ubicacion</th><th>Publicacion</th></tr></thead><tbody>';
  rows.forEach(r => {
    html += '<tr class="' + rowClass(r.seller) + '">' +
      '<td class="rank">' + r.rank + '</td>' +
      '<td class="ads">' + (r.isAd ? '✅' : '') + '</td>' +
      '<td><span class="seller-link" onclick="goVendedor(\'' + esc(r.seller) + '\')">' + r.seller + '</span></td>' +
      '<td>' + fmtPrice(r) + '</td>' +
      '<td>' + (r.location || '-') + '</td>' +
      '<td><a class="pub" href="' + r.link + '" target="_blank">' + r.title + '</a></td>' +
      '</tr>';
  });
  html += '</tbody>';
  document.getElementById('tbl-moto').innerHTML = html;
}

// ---- VISTA POR VENDEDOR ----
function initVendedor() {
  const sellers = new Set();
  Object.values(DATA.modelos).forEach(o => o.rows.forEach(r => sellers.add(r.seller)));
  const sel = document.getElementById('sel-vendedor');
  // Ciclofox Pacheco primero, Pueyrredon segundo
  const sorted = Array.from(sellers).sort((a,b) => {
    if (a === PACHECO) return -1; if (b === PACHECO) return 1;
    if (a === PUEYRREDON) return -1; if (b === PUEYRREDON) return 1;
    return a.localeCompare(b);
  });
  sorted.forEach(s => {
    const o = document.createElement('option');
    o.value = s;
    o.textContent = (s === PACHECO ? '⭐ ' : s === PUEYRREDON ? '🔵 ' : '') + s;
    sel.appendChild(o);
  });
  // Filtro por marca
  const selB = document.getElementById('sel-vmarca');
  const optBAll = document.createElement('option');
  optBAll.value = '__all__'; optBAll.textContent = 'Todas las marcas';
  selB.appendChild(optBAll);
  const marcas = [...new Set(Object.keys(DATA.modelos).map(brandOf))].sort();
  marcas.forEach(b => {
    const o = document.createElement('option');
    o.value = b; o.textContent = b.toUpperCase();
    selB.appendChild(o);
  });
  // Filtro por modelo
  fillModelos('__all__');
  renderVendedor();
}
function brandOf(modelo) { return modelo.split(' ')[0]; }

function fillModelos(marca) {
  const selM = document.getElementById('sel-vmodelo');
  selM.innerHTML = '';
  const optAll = document.createElement('option');
  optAll.value = '__all__'; optAll.textContent = 'Todos los modelos';
  selM.appendChild(optAll);
  Object.keys(DATA.modelos)
    .filter(m => marca === '__all__' || brandOf(m) === marca)
    .forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m.toUpperCase();
      selM.appendChild(o);
    });
}
function onMarcaChange() {
  const marca = document.getElementById('sel-vmarca').value;
  fillModelos(marca);
  renderVendedor();
}
function renderVendedor() {
  const v = document.getElementById('sel-vendedor').value;
  const fmarca = document.getElementById('sel-vmarca').value;
  const fmodelo = document.getElementById('sel-vmodelo').value;
  const rows = [];
  Object.entries(DATA.modelos).forEach(([modelo, o]) => {
    if (fmarca !== '__all__' && brandOf(modelo) !== fmarca) return;
    if (fmodelo !== '__all__' && modelo !== fmodelo) return;
    o.rows.forEach(r => {
      if (r.seller === v) rows.push({ ...r, modelo, searchUrl: o.url });
    });
  });
  rows.sort((a,b) => a.modelo.localeCompare(b.modelo) || a.rank - b.rank);

  const summary = document.getElementById('vendedor-summary');
  const avgRank = rows.length ? (rows.reduce((s,r)=>s+r.rank,0)/rows.length).toFixed(1) : '—';
  const top3 = rows.filter(r => r.rank <= 3).length;
  summary.innerHTML =
    stat(rows.length, 'Publicaciones') +
    stat(new Set(rows.map(r=>r.modelo)).size, 'Modelos') +
    stat(avgRank, 'Ranking promedio') +
    stat(top3, 'En top 3');

  let html = '<thead><tr><th>Modelo</th><th>#</th><th>Ads</th><th>Precio</th><th>Ubicacion</th><th>Publicacion</th><th>Busqueda</th></tr></thead><tbody>';
  rows.forEach(r => {
    html += '<tr class="' + rowClass(r.seller) + '">' +
      '<td><strong>' + r.modelo.toUpperCase() + '</strong></td>' +
      '<td class="rank">#' + r.rank + '</td>' +
      '<td class="ads">' + (r.isAd ? '✅' : '') + '</td>' +
      '<td>' + fmtPrice(r) + '</td>' +
      '<td>' + (r.location || '-') + '</td>' +
      '<td><a class="pub" href="' + r.link + '" target="_blank">' + r.title + '</a></td>' +
      '<td><a class="seller-link" href="' + r.searchUrl + '" target="_blank">🔎 ver</a></td>' +
      '</tr>';
  });
  html += '</tbody>';
  document.getElementById('tbl-vendedor').innerHTML = html;
}

function goVendedor(seller) {
  setView('vendedor');
  document.getElementById('sel-vendedor').value = seller;
  document.getElementById('sel-vmarca').value = '__all__';
  fillModelos('__all__');
  document.getElementById('sel-vmodelo').value = '__all__';
  renderVendedor();
}

function stat(num, lbl) {
  return '<div class="stat"><div class="num">' + num + '</div><div class="lbl">' + lbl + '</div></div>';
}
function esc(s){ return s.replace(/'/g,"\\'"); }

function setView(v) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === v));
  document.getElementById('view-moto').classList.toggle('hidden', v !== 'moto');
  document.getElementById('view-vendedor').classList.toggle('hidden', v !== 'vendedor');
}

initMoto();
initVendedor();
</script>
</body>
</html>"""


if __name__ == "__main__":
    flags = {"--profile", "--html-only"}
    use_profile = "--profile" in sys.argv
    html_only = "--html-only" in sys.argv
    custom = [a for a in sys.argv[1:] if a not in flags]
    modelos = custom if custom else MODELOS
    try:
        if html_only:
            regenerar_html()
        else:
            main(modelos, use_profile=use_profile)
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
