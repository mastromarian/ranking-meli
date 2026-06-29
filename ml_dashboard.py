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

import os
import sys
import io
import re
import time
import json
import urllib.request
import urllib.parse
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
    "yamaha mt 07",
    "yamaha mt 09",
    "yamaha nmax",
    "yamaha fz 4.0",
    "yamaha fz 25",
    "yamaha fz-x",
    "yamaha xtz 125",
    "yamaha xtz 250",
    "yamaha xmax 300",
    "yamaha ray 125",
    "yamaha fascino",
    "yamaha ttr 230",
    "yamaha tenere 700",
    # Hero
    "hero hunk 150",
    "hero xpulse 200",
    # Motomel
    "motomel skua 150",
    "motomel skua 250",
    "motomel blitz 110",
    "motomel blitz 110 full",
    "motomel cg s2 150",
    "motomel cg s2 150 full",
    # Siam
    "siam qu110",
    "siam qu110 full",
    "siam trender 150",
    "siam nomad 150",
    "siam twin roads",
    # TVS
    "tvs raider 125",
    "tvs rtr 200",
    # Ika
    "ika durban",
    # Gaf
    "gaf gx 70",
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
    if os.environ.get("HEADLESS"):
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    )
    if use_profile:
        # Perfil DEDICADO del scraper (no el de Chrome de todos los dias).
        # Logueate en ML una sola vez con --login; la sesion queda guardada aca.
        # Asi nunca choca con tu Chrome abierto.
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")
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

    # Titulos de publicaciones que estan corriendo Ads. ML las muestra en bloques
    # patrocinados (fuera de ui-search-layout__item) con un span "Ad" y un link de
    # tracking SIN MLA-id, pero la misma publicacion aparece en el listado organico.
    # Como no hay id, matcheamos por titulo normalizado.
    def _norm(t):
        return re.sub(r"[^a-z0-9]", "", (t or "").lower())
    ad_titles = set()
    for adspan in soup.select(".poly-component__ads-promotions"):
        li = adspan.find_parent("li")
        t = li.select_one(".poly-component__title") if li else None
        if t:
            ad_titles.add(_norm(t.get_text(strip=True)))

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

        # Marca isAd si esta publicacion aparece en el bloque patrocinado (match por titulo)
        is_ad = bool(item.select_one(".poly-component__ads-promotions")) or \
                (_norm(title) in ad_titles) or \
                "is_advertising=true" in (link_el["href"] if link_el else "")

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

    # Asignar rank limpio: los Ads NO ocupan puesto en el ranking, pero quedan
    # en el listado en el orden en que se encontraron (rank = None).
    rank = 0
    for r in results:
        if r.get("isAd"):
            r["rank"] = None
        else:
            rank += 1
            r["rank"] = rank

    return url, results, visitas


# ───────────────────────── SCRAPER VIA API DE LA APP ─────────────────────────
def load_app_session():
    """Carga el token/headers capturados de la app de Mercado Libre."""
    try:
        with open("app_session.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _app_headers(sess: dict) -> dict:
    return {
        "Authorization": "Bearer " + sess["token"],
        "x-meli-session-id": sess.get("session_id", ""),
        "x-d2id": sess.get("d2id", ""),
        "x-client-info": sess.get("client_info", ""),
        "User-Agent": sess.get("user_agent", "MercadoLibre-iOS/10.545.5"),
        "x-app-version": sess.get("app_version", ""),
        "x-polycard-lib": sess.get("polycard_lib", ""),
        "x-polycard-contract": sess.get("polycard_contract", ""),
        "x-card-type": "polycard",
        "accept-language": "es-AR",
        "Accept": "*/*",
    }


def _poly_field(comps, ctype):
    for c in comps:
        if isinstance(c, dict) and c.get("type") == ctype:
            return c
    return None


def scrape_modelo_app(query: str, sess: dict, top_n: int = 20):
    """Consulta el mismo endpoint que usa la app de ML y devuelve las filas
    en el orden REAL de la app. Devuelve (rows, ok)."""
    params = {
        "q": query, "pure_query": "true", "limit": "20", "offset": "0",
        "layout": "list", "zipcode": sess.get("zipcode", "1427"),
        "lat": sess.get("lat", ""), "lon": sess.get("lon", ""),
        "action": "zero", "retailer": "secondary", "mclicsOn": "true",
        "all_mercadolibre": "True", "sb": "all_mercadolibre",
    }
    url = "https://frontend.mercadolibre.com/sites/MLA/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_app_headers(sess))
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.load(r)

    polys = [c["polycard"] for c in data.get("components", [])
             if isinstance(c, dict) and "polycard" in c]
    results = []
    for pc in polys[:top_n]:
        meta = pc.get("metadata", {})
        comps = pc.get("components", [])
        tc = _poly_field(comps, "title")
        title = (tc.get("title", {}).get("text", "") if tc and isinstance(tc.get("title"), dict) else "")
        pcp = _poly_field(comps, "price")
        price_num = 0
        if pcp:
            price_num = int(pcp.get("price", {}).get("current_price", {}).get("value", 0) or 0)
        lc = _poly_field(comps, "location")
        location = lc.get("location", {}).get("text", "") if lc else ""
        ac = _poly_field(comps, "attributes_list")
        attrs = ac.get("attributes_list", {}).get("texts", []) if ac else []
        is_0km = any(str(a).strip().lower() == "0 km" for a in attrs)
        is_ad = "is_advertising=true" in meta.get("url_fragments", "")
        mid = meta.get("id", "")
        link = f"https://articulo.mercadolibre.com.ar/{mid[:3]}-{mid[3:]}-_JM" if mid else ""
        results.append({
            "title": title,
            "price_raw": "$" + f"{price_num:,}".replace(",", ".") if price_num else "",
            "price_num": price_num,
            "location": location,
            "is_0km": is_0km,
            "seller_listado": "",
            "seller": "",
            "isAd": is_ad,
            "link": link,
            "mla": mid,
        })

    # Filtrar 0km
    results = [r for r in results if r["is_0km"]]
    # Resolver vendedor por titulo/ubicacion (sin visitar)
    for r in results:
        name, _ = resolve_seller(r["title"], r["location"], "")
        r["seller"] = name or "(no visible)"
    # Rank: ads sin puesto
    rank = 0
    for r in results:
        if r.get("isAd"):
            r["rank"] = None
        else:
            rank += 1
            r["rank"] = rank
    return results, True


def _mla_of(link_or_id: str) -> str:
    m = re.search(r"MLA-?(\d+)", link_or_id or "")
    return m.group(1) if m else ""


def enrich_app_sellers(rows_web: list, rows_app: list):
    """Copia el vendedor ya resuelto del scrape web a las filas de la app,
    matcheando por MLA-id. Lo que no matchea queda como lo dejo resolve_seller."""
    web_by_mla = {}
    for r in rows_web or []:
        mla = _mla_of(r.get("link", ""))
        if mla and r.get("seller") and r["seller"] != "(no visible)":
            web_by_mla[mla] = r["seller"]
    for r in rows_app or []:
        mla = _mla_of(r.get("mla") or r.get("link", ""))
        if mla in web_by_mla:
            r["seller"] = web_by_mla[mla]


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
    os.makedirs("public", exist_ok=True)
    for fname in ("ml_ranking.html", os.path.join("public", "index.html")):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
    print("Dashboard regenerado en ml_ranking.html e index.html (desde datos existentes)")


def main(modelos: list, use_profile: bool = False):
    print(f"\nScrapeando {len(modelos)} modelos...")
    if use_profile:
        print(">> Modo perfil: usando perfil dedicado (chrome_profile) con tu sesion ML.\n")
    else:
        print()
    driver = get_driver(use_profile=use_profile)
    data = {}
    try:
        for i, modelo in enumerate(modelos, 1):
            print(f"[{i}/{len(modelos)}] {modelo}...", end="", flush=True)
            ok = False
            for intento in range(2):  # hasta 2 intentos (recrea el driver si se cae)
                try:
                    url, res, visitas = scrape_modelo(driver, modelo)
                    data[modelo] = {"url": url, "rows": res}
                    print(f" OK ({len(res)} 0km, {visitas} visitas)")
                    ok = True
                    break
                except Exception as e:
                    msg = str(e).split("\n")[0][:60]
                    if intento == 0:
                        print(f" reintentando (driver caido: {msg})...", end="", flush=True)
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = get_driver(use_profile=use_profile)
                    else:
                        print(f" ERROR: {msg}")
            if not ok:
                data[modelo] = {"url": search_to_url(modelo), "rows": []}
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Pasada por la API de la app (ranking REAL de la app de ML)
    app_sess = load_app_session()
    if app_sess and app_sess.get("token"):
        print("\nScrapeando ranking de la APP (API)...")
        for i, modelo in enumerate(modelos, 1):
            if modelo not in data:
                continue
            try:
                rows_app, _ = scrape_modelo_app(modelo, app_sess)
                enrich_app_sellers(data[modelo].get("rows", []), rows_app)
                data[modelo]["rows_app"] = rows_app
                print(f"  [{i}/{len(modelos)}] {modelo}... OK ({len(rows_app)} app)")
            except Exception as e:
                msg = str(e).split("\n")[0][:70]
                print(f"  [{i}/{len(modelos)}] {modelo}... ERROR app: {msg}")
                data[modelo]["rows_app"] = []
            time.sleep(0.4)
    else:
        print("\n(Sin app_session.json valido: se omite el ranking de la app)")

    # Mergear con lo que ya habia: reemplaza/agrega los modelos scrapeados,
    # mantiene el resto intacto. Asi correr 1 modelo no borra los demas.
    modelos_merged = data
    try:
        with open("ml_data.json", "r", encoding="utf-8") as f:
            prev = json.load(f)
        modelos_merged = dict(prev.get("modelos", {}))
        modelos_merged.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mi_cuenta": MI_CUENTA,
        "modelos": modelos_merged,
    }

    with open("ml_data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nDatos guardados en ml_data.json ({len(data)} scrapeados, {len(modelos_merged)} totales)")

    record_history(payload)
    print("Historial de ranking actualizado en ml_history.json")

    html = build_html(payload)
    os.makedirs("public", exist_ok=True)
    for fname in ("ml_ranking.html", os.path.join("public", "index.html")):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
    print("Dashboard generado en ml_ranking.html e index.html")
    print("\nAbri ml_ranking.html en tu navegador.\n")


HISTORY_PATH = "ml_history.json"


def record_history(payload: dict, path: str = HISTORY_PATH):
    """Guarda un snapshot del mejor rank por vendedor/modelo (web y app) con fecha.
    Series: hist['series'][vendedor][modelo] = [[fecha, rank_web, rank_app], ...]"""
    date = payload.get("generated")
    try:
        with open(path, "r", encoding="utf-8") as f:
            hist = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        hist = {"series": {}}
    series = hist.setdefault("series", {})
    for modelo, o in payload.get("modelos", {}).items():
        best = {}  # seller -> [web, app]
        for r in o.get("rows", []):
            s, rk = r.get("seller"), r.get("rank")
            if not s or rk is None:
                continue
            best.setdefault(s, [None, None])
            if best[s][0] is None or rk < best[s][0]:
                best[s][0] = rk
        for r in o.get("rows_app", []):
            s, rk = r.get("seller"), r.get("rank")
            if not s or rk is None:
                continue
            best.setdefault(s, [None, None])
            if best[s][1] is None or rk < best[s][1]:
                best[s][1] = rk
        for s, (w, a) in best.items():
            arr = series.setdefault(s, {}).setdefault(modelo, [])
            if arr and arr[-1][0] == date:
                arr[-1] = [date, w, a]   # reemplaza si ya hay snapshot de esa fecha
            else:
                arr.append([date, w, a])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    return hist


def _load_history(path: str = HISTORY_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"series": {}}


def build_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    hist_json = json.dumps(_load_history(), ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA__", data_json)
    html = html.replace("__HISTORY__", hist_json)
    return html


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mercado Libre - Posicionamiento</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f7; color: #1d1d1f; padding: 20px; }
  .container { max-width: 1200px; margin: 0 auto; }
  .header-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  h1 { font-size: 20px; margin: 0; }
  .nav-tabs { display: inline-flex; background: #e8e8ed; border-radius: 10px; padding: 3px; gap: 3px; }
  .nav-btn { border: none; background: transparent; padding: 7px 18px; border-radius: 8px; font-size: 14px;
    font-weight: 600; color: #6e6e73; cursor: pointer; font-family: inherit; transition: all .15s; }
  .nav-btn:hover { color: #1d1d1f; }
  .nav-btn.active { background: #fff; color: #1d1d1f; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .meta { color: #86868b; font-size: 12px; margin-bottom: 0; }
  .update-banner {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 10px;
    font-size: 13px; font-weight: 600; border: 1.5px solid;
  }
  .update-banner .ub-icon { font-size: 16px; }
  .ub-fresh { background: #e9f9ee; color: #137a36; border-color: #34c759; }
  .ub-mid   { background: #fff8e6; color: #8a6d00; border-color: #ffcc00; }
  .ub-stale { background: #fdeaea; color: #b3000f; border-color: #ff3b30; }
  .panel { display: flex; gap: 16px; margin-bottom: 20px; }
  .panel-left { flex: 1; padding: 0 24px 8px 24px; background: #fff; border-radius: 14px;
                box-shadow: 0 1px 3px rgba(0,0,0,.06); }
  .panel-right { flex: 1; padding: 0 24px 8px 24px; background: #fff; border-radius: 14px;
                 box-shadow: 0 1px 3px rgba(0,0,0,.06); display: flex; flex-direction: column; }
  .panel-title { font-size: 13px; font-weight: 700; color: #1d1d1f; background: #e0e0e0; padding: 6px 24px;
                 margin: 0 -24px 10px -24px; border-radius: 14px 14px 0 0; }
  .subhead { font-size: 11px; font-weight: 700; color: #86868b; text-transform: uppercase; letter-spacing: .03em; margin-bottom: 6px; }
  .tabs { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
  .tabs-label { font-size: 15px; font-weight: 700; color: #1d1d1f; margin-right: 8px; }
  .tab { padding: 4px 12px; background: #f5f5f7; border: 1px solid #d2d2d7; border-radius: 8px;
         cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s; }
  .tab:hover { background: #e8e8ed; }
  .tab.active { background: #0071e3; color: #fff; border-color: #0071e3; }
  .controls { display: flex; flex-direction: column; align-items: stretch; gap: 4px; width: 100%; }
  .controls > div, .controls > span { display: flex; align-items: center; gap: 8px; width: 100%; }
  .controls-label { font-size: 12px; font-weight: 600; color: #1d1d1f; white-space: nowrap; }
  select { padding: 5px 10px; font-size: 12px; border: 1px solid #d2d2d7; border-radius: 8px;
           background: #fff; flex: 1; min-width: 0; cursor: pointer; }
  .card { background: #fff; border-radius: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
          margin-bottom: 16px; max-height: 375px; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 5px 12px; border-bottom: 2px solid #e8e8ed; color: #1d1d1f;
       font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .03em;
       position: sticky; top: 0; background: #e0e0e0; z-index: 1; }
  #tbl-vendedor th { cursor: pointer; user-select: none; }
  #tbl-vendedor th:hover { background: #d0d0d0; }
  #tbl-vendedor th .sort-arrow { font-size: 10px; margin-left: 4px; }
  td { padding: 6px 12px; border-bottom: 1px solid #f0f0f2; }
  tr:hover td { background: #fafafa; }
  .rank { color: #1d1d1f; width: 40px; }
  .ads { text-align: center; width: 50px; }
  .price { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px;
           font-weight: 600; }
  .badge-ad { background: #fff3cd; color: #856404; }
  .badge-plan { background: #e7f3ff; color: #0071e3; }
  /* Tooltip propio (info "i") */
  .tip { position: relative; display: inline-block; cursor: help; }
  .tip-i { display: inline-block; width: 15px; height: 15px; line-height: 15px; text-align: center;
           border-radius: 50%; background: #86868b; color: #fff; font-size: 10px; font-weight: 700;
           font-style: italic; vertical-align: middle; }
  .tip-box { display: none; position: absolute; top: 130%; left: 0; z-index: 1000;
             background: #1d1d1f; color: #fff; padding: 12px 14px; border-radius: 8px;
             font-size: 12.5px; font-weight: 400; line-height: 1.6; white-space: pre-line;
             width: 440px; max-width: 80vw; box-shadow: 0 4px 16px rgba(0,0,0,.25); }
  .tip:hover .tip-box, .tip.pinned .tip-box { display: block; }
  .tip-box--sm { width: 280px; font-style: normal; }
  /* Vista Moto: Pacheco amarillo, Pueyrredon azul */
  #tbl-moto .mine { background: #fff8e1 !important; }
  #tbl-moto .mine td { font-weight: 600; }
  #tbl-moto .mine .rank { color: #b8860b; }
  #tbl-moto .puey { background: #eef7ff !important; }
  #tbl-moto .puey td { font-weight: 600; }
  #tbl-moto .puey .rank { color: #0066cc; }
  /* Vista Concesionaria: todo lo resaltado en rojo (logica = mal rank) */
  #tbl-vendedor .mine, #tbl-vendedor .puey { background: #fff0f0 !important; }
  #tbl-vendedor .mine td, #tbl-vendedor .puey td { font-weight: 600; }
  #tbl-vendedor .mine .rank, #tbl-vendedor .puey .rank { color: #e3000f; }
  .seller-link { color: #1d1d1f; cursor: pointer; text-decoration: none; }
  .seller-link:hover { text-decoration: underline; }
  .seller-link:hover { text-decoration: underline; }
  .summary { display: flex; flex-direction: column; gap: 6px; }
  .stat { display: flex; align-items: baseline; gap: 8px; }
  .stat .num { font-size: 18px; font-weight: 700; min-width: 45px; text-align: right; }
  .stat .lbl { font-size: 12px; color: #555; white-space: nowrap; }
  .hidden { display: none; }
  a.pub { color: #1d1d1f; text-decoration: none; }
  a.pub:hover { color: #0071e3; text-decoration: underline; }
  body.readonly .rank-col { visibility: hidden; }
  #user-chip { display: flex; align-items: center; justify-content: flex-end; gap: 8px; font-size: 12px; color: #555; padding: 6px 0; }
  #user-chip button { background: none; border: 1px solid #ccc; border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; color: #555; }
  #user-chip button:hover { background: #f0f0f0; }
  #user-chip .role-badge { font-weight:700; padding:2px 8px; border-radius:999px; font-size:11px; letter-spacing:.5px; }
  #user-chip .role-admin { background:#dcfce7; color:#166534; }
  #user-chip .role-lectura { background:#e2e8f0; color:#475569; }
</style>
</head>
<body>

<!-- Supabase client (CDN) -->
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
  const SUPABASE_URL  = 'https://cazdzwigtazmecixhuiw.supabase.co';
  const SUPABASE_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhemR6d2lndGF6bWVjaXhodWl3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE5ODQ3OTQsImV4cCI6MjA5NzU2MDc5NH0.gDpzVh5apPBpDujdRN8olJk93FxULHCrS49XOVxGwvU';
  let sb = null;
  try { sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON, { auth: { persistSession: true, autoRefreshToken: true } }); }
  catch (e) { console.warn('Supabase no configurado:', e.message); }
</script>

<!-- Pantalla de login -->
<div id="auth-gate" style="position:fixed;inset:0;z-index:99999;background:#f5f5f7;display:flex;align-items:center;justify-content:center;padding:20px;">
  <div style="background:#fff;padding:30px 28px;border-radius:14px;width:340px;max-width:100%;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.12);border-top:4px solid #0071e3;">
    <div style="font-weight:800;font-size:17px;margin-bottom:4px;color:#1d1d1f;">Monitor de Posicionamiento</div>
    <div id="auth-sub" style="font-size:13px;color:#86868b;margin-bottom:18px;">Verificando sesión…</div>
    <div id="auth-form" style="display:none;">
      <input id="auth-email" type="email" placeholder="Email" autocomplete="username"
        style="width:100%;margin-bottom:8px;padding:11px 14px;border:1.5px solid #e8e8ed;border-radius:8px;font-size:15px;outline:none;font-family:inherit;"
        onkeydown="if(event.key==='Enter')document.getElementById('auth-pass').focus()">
      <input id="auth-pass" type="password" placeholder="Contraseña" autocomplete="current-password"
        style="width:100%;padding:11px 14px;border:1.5px solid #e8e8ed;border-radius:8px;font-size:15px;outline:none;font-family:inherit;"
        onkeydown="if(event.key==='Enter')doLogin()">
      <div id="auth-err" style="color:#e3000f;font-size:12px;font-weight:600;height:16px;margin-top:8px;"></div>
      <button id="auth-btn" onclick="doLogin()"
        style="width:100%;margin-top:10px;padding:11px;background:#0071e3;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;">
        Entrar
      </button>
    </div>
  </div>
</div>

<div class="container" id="main-app" style="display:none">
  <div id="user-chip"></div>
  <div class="header-row">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <img src="https://http2.mlstatic.com/frontend-assets/ml-web-navigation/ui-navigation/6.6.92/mercadolibre/logo_large_25years@2x.png" alt="Mercado Libre" style="height:24px">
      <div class="nav-tabs">
        <button id="nav-ranking" class="nav-btn active" onclick="showSection('ranking')">Ranking</button>
        <button id="nav-comparador" class="nav-btn" onclick="showSection('comparador')">Comparador</button>
      </div>
    </div>
    <div class="update-banner" id="update-banner"></div>
  </div>

  <div id="ranking-view">
  <div class="panel">
    <div class="panel-left">
      <div class="panel-title">Búsqueda</div>
      <div style="display:flex;gap:24px;align-items:stretch">
        <!-- IZQUIERDA: Visualización -->
        <div style="flex:1;min-width:0">
          <div class="subhead">Visualización</div>
          <div class="tabs" id="src-tabs">
            <span class="controls-label">Mercadolibre:</span>
            <div class="tab active" data-src="app" onclick="setSource('app')">📱 App</div>
            <div class="tab" data-src="web" onclick="setSource('web')">💻 Web</div>
          </div>
          <div class="tabs" id="view-tabs">
            <span class="controls-label">Vista:</span>
            <div class="tab active" data-view="vendedor" onclick="setView('vendedor')">Concesionaria</div>
            <div class="tab" data-view="moto" onclick="setView('moto')">Moto</div>
          </div>
          <div class="tabs" id="mode-tabs">
            <span class="controls-label">Período:</span>
            <div class="tab active" data-mode="actual" onclick="setMode('actual')">Actual</div>
            <div class="tab" data-mode="evolutivo" onclick="setMode('evolutivo')">📈 Evolutivo</div>
          </div>
        </div>
        <!-- DERECHA: Filtros -->
        <div id="filtros-col" style="flex:1;min-width:0;border-left:1px solid #e8e8ed;padding-left:24px">
          <div class="subhead">Filtros</div>
          <div id="controls-vendedor" class="controls hidden">
            <div><span class="controls-label">Concesionaria:</span>
            <select id="sel-vendedor" onchange="renderVendedor()"></select></div>
          </div>
          <div id="controls-moto" class="controls">
            <div><span class="controls-label">Marca:</span>
            <select id="sel-mmarca" onchange="onMotoMarcaChange()"></select></div>
            <div><span class="controls-label">Modelo:</span>
            <select id="sel-moto" onchange="renderMoto()"></select></div>
          </div>
          <div id="controls-vendedor-moto" class="controls hidden">
            <div><span class="controls-label">Marca:</span>
            <select id="sel-vmarca" onchange="onMarcaChange()"></select></div>
            <div><span class="controls-label">Modelo:</span>
            <select id="sel-vmodelo" onchange="renderVendedor()"></select></div>
          </div>
        </div>
      </div>
      <div id="moto-link" class="meta" style="margin-top:8px"></div>
    </div>
    <div class="panel-right" id="panel-resultados">
      <div class="panel-title">Resultados</div>
      <div style="display:flex;gap:24px;position:relative">
        <div>
          <div class="summary" id="moto-summary"></div>
          <div class="summary hidden" id="vendedor-summary"></div>
        </div>
        <div id="moto-insights" style="border-left:1px solid #e8e8ed;padding-left:20px;font-size:12px;color:#1d1d1f"></div>
        <div id="vendedor-insights" class="hidden" style="border-left:1px solid #e8e8ed;padding-left:20px;font-size:12px;color:#1d1d1f"></div>
        <button id="btn-wsp" class="hidden" onclick="copiarResumenWsp()"
          style="position:absolute;top:0;right:0;background:#25d366;color:#fff;border:none;border-radius:8px;
          padding:6px 10px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap">
          📋 Copiar resumen</button>
      </div>
    </div>
  </div>

  <!-- VISTA POR MOTO -->
  <div id="view-moto">
    <div class="card"><table id="tbl-moto"></table></div>
  </div>

  <!-- VISTA EVOLUCIÓN -->
  <div id="view-evolucion" class="hidden">
    <div class="card" style="max-height:none;overflow:visible;padding:16px">
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap">
        <span class="controls-label">Concesionaria:</span>
        <select id="ev-vendedor" onchange="onEvolVendedor()" style="flex:0 1 200px"></select>
        <span class="controls-label">Marca:</span>
        <select id="ev-marca" onchange="onEvolMarca()" style="flex:0 1 160px"></select>
        <span class="controls-label">Modelo:</span>
        <select id="ev-modelo" onchange="renderEvol()" style="flex:0 1 200px"></select>
      </div>
      <div id="ev-chart"></div>
      <div id="ev-empty" style="color:#86868b;font-size:13px;margin-top:8px"></div>
    </div>
  </div>

  <!-- VISTA POR VENDEDOR -->
  <div id="view-vendedor" class="hidden">
    <div class="card"><table id="tbl-vendedor"></table></div>
  </div>
  </div><!-- /ranking-view -->

  <!-- COMPARADOR -->
  <div id="comparador-view" class="hidden">
    <iframe src="comparador.html" style="width:100%;height:calc(100vh - 140px);border:none;background:#fff;border-radius:12px"></iframe>
  </div>
</div>

<script>
const DATA = __DATA__;
const HISTORY = __HISTORY__;

// ---- Navegación Ranking / Comparador ----
function showSection(sec) {
  var isRank = sec === 'ranking';
  document.getElementById('ranking-view').classList.toggle('hidden', !isRank);
  document.getElementById('comparador-view').classList.toggle('hidden', isRank);
  document.getElementById('nav-ranking').classList.toggle('active', isRank);
  document.getElementById('nav-comparador').classList.toggle('active', !isRank);
}

// ---- Banner de ultima actualizacion con semaforo ----
(function renderUpdateBanner() {
  const banner = document.getElementById('update-banner');
  // generated viene como "YYYY-MM-DD HH:MM"
  const gen = new Date((DATA.generated || '').replace(' ', 'T'));
  let cls = 'ub-stale', icon = '🔴', estado = 'Desactualizado';
  if (!isNaN(gen)) {
    const dias = Math.floor((Date.now() - gen.getTime()) / 86400000);
    if (dias <= 3)      { cls = 'ub-fresh'; icon = '🟢'; estado = 'Actualizado'; }
    else if (dias <= 7) { cls = 'ub-mid';   icon = '🟡'; estado = 'Conviene actualizar'; }
    else                { cls = 'ub-stale'; icon = '🔴'; estado = 'Desactualizado'; }
    const hace = dias === 0 ? 'hoy' : dias === 1 ? 'hace 1 día' : 'hace ' + dias + ' días';
    banner.className = 'update-banner ' + cls;
    banner.innerHTML =
      '<span class="ub-icon">' + icon + '</span>' +
      '<div>Última actualización: ' + DATA.generated + ' (' + hace + ')</div>';
  } else {
    banner.className = 'update-banner ub-stale';
    banner.innerHTML = '<span class="ub-icon">🔴</span><div>Fecha de actualización desconocida</div>';
  }
})();

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

var RANK_SOURCE = 'app';  // 'app' o 'web'
function srcRows(o) { if (!o) return []; return (RANK_SOURCE === 'app' ? (o.rows_app || o.rows) : o.rows) || []; }
function rowsOf(m) { return srcRows(DATA.modelos[m]); }
function urlOf(m)  { return (DATA.modelos[m] && DATA.modelos[m].url) || ''; }

// ---- VISTA POR MOTO ----
function modelLabel(m) {
  const parts = m.split(' ').slice(1).join(' ');
  return (parts || m).toUpperCase();
}
function titleCase(s) { return (s || '').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()); }
function brandLabel(m) { return titleCase(m.split(' ')[0]); }
function modelOnlyLabel(m) { const p = m.split(' ').slice(1).join(' '); return titleCase(p || m); }
function initMoto() {
  // Filtro por marca
  const selB = document.getElementById('sel-mmarca');
  const marcas = [...new Set(Object.keys(DATA.modelos).map(brandOf))].sort();
  const sorted = marcas.filter(b => b === 'yamaha');
  const rest = marcas.filter(b => b !== 'yamaha');
  function addMarcaOpt(b) { const o = document.createElement('option'); o.value = b; o.textContent = b.toUpperCase(); selB.appendChild(o); }
  function addMarcaSep() { const o = document.createElement('option'); o.disabled = true; o.textContent = '─────────────'; selB.appendChild(o); }
  sorted.forEach(addMarcaOpt);
  if (sorted.length && rest.length) addMarcaSep();
  rest.forEach(addMarcaOpt);
  const defaultMarca = marcas.includes('yamaha') ? 'yamaha' : marcas[0];
  selB.value = defaultMarca;
  fillMotoModelos(defaultMarca);
  renderMoto();
}
function fillMotoModelos(marca) {
  const sel = document.getElementById('sel-moto');
  sel.innerHTML = '';
  Object.keys(DATA.modelos)
    .filter(m => brandOf(m) === marca)
    .sort((a, b) => modelLabel(a).localeCompare(modelLabel(b), 'es', {numeric: true}))
    .forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = modelLabel(m);
      sel.appendChild(o);
    });
}
function onMotoMarcaChange() {
  fillMotoModelos(document.getElementById('sel-mmarca').value);
  renderMoto();
}
function renderMoto() {
  const m = document.getElementById('sel-moto').value;
  const rows = rowsOf(m);
  const url  = urlOf(m);
  const pacheco = rows.find(r => isPacheco(r.seller));

  // link de busqueda
  document.getElementById('moto-link').innerHTML =
    '<span class="tip"><span style="font-weight:600">🔎 Busqueda</span> <span class="tip-i">i</span>' +
    '<span class="tip-box">' + TIP_PROCESO + '</span></span>: <a href="' + url + '" target="_blank">' + url + '</a>';

  // summary — muestra el mejor rank organico; si solo tiene Ad, muestra "Ad"
  const summary = document.getElementById('moto-summary');
  summary.innerHTML =
    posStat(sellerRankDisp(rows, isPacheco), 'Ciclofox Pacheco') +
    posStat(sellerRankDisp(rows, r => r.seller === PUEYRREDON), 'Ciclofox Pueyrredón') +
    stat(new Set(rows.map(r => r.seller)).size, 'Vendedores únicos');

  // insights
  var ins = [];
  var hasOutlier = false, minP = 0;
  var realPrices = rows.filter(r => r.price_num >= 1000000);
  if (realPrices.length) {
    var prices = realPrices.map(r => r.price_num);
    minP = Math.min(...prices);
    var moda = prices.sort()[Math.floor(prices.length/2)];
    var cheapSellers = realPrices.filter(r => r.price_num < moda);
    var uniquePrices = [...new Set(prices)];
    var minSellers = [...new Set(realPrices.filter(r => r.price_num === minP).map(r => r.seller))];
    var totalSellers = [...new Set(realPrices.map(r => r.seller))];
    hasOutlier = uniquePrices.length > 1 && minSellers.length < totalSellers.length / 2;
    if (hasOutlier) {
      ins.push('💰 Precio más bajo: <b>$' + minP.toLocaleString('es-AR') + '</b> (' + minSellers.join(', ') + ')');
    }
  }
  var planes = rows.filter(r => r.price_num > 0 && r.price_num < 1000000);
  if (planes.length > 0) {
    var planSellers = [...new Set(planes.map(r => r.seller))];
    if (planSellers.length === 1) ins.push('📋 <b>' + planSellers[0] + '</b> es el único que ofrece Plan de Ahorro');
    else ins.push('📋 Ofrecen Plan de Ahorro: <b>' + planSellers.join(', ') + '</b>');
  }
  var adSellers = [...new Set(rows.filter(r => r.isAd).map(r => r.seller))];
  if (adSellers.length > 0) ins.push('📢 Con Ads activos: <b>' + adSellers.join(', ') + '</b>');
  document.getElementById('moto-insights').innerHTML = comentariosHeader(TIP_MOTO) + (ins.length ? ins.map(i => '<div style="margin-bottom:4px">' + i + '</div>').join('') : '<div style="color:#86868b">Sin comentarios para este modelo.</div>');

  // tabla — ads siempre arriba (sin rank), luego organicos por rank
  const displayRows = rows.slice().sort((a, b) => {
    if (a.isAd !== b.isAd) return a.isAd ? -1 : 1;
    if (a.isAd && b.isAd) return 0;
    return a.rank - b.rank;
  });
  let html = '<thead><tr><th class="rank-col">Rank</th><th>Vendedor</th><th>Precio</th><th>Ubicacion</th><th>Publicacion</th></tr></thead><tbody>';
  displayRows.forEach(r => {
    html += '<tr class="' + rowClass(r.seller) + '">' +
      '<td class="rank rank-col">' + (r.rank == null ? '<span style="color:#86868b;font-size:11px">Ad</span>' : r.rank) + '</td>' +
      '<td><span class="seller-link" onclick="goVendedor(\'' + esc(r.seller) + '\')">' + r.seller + '</span></td>' +
      '<td>' + (hasOutlier && r.price_num === minP ? '<span style="color:#ff3b30;font-weight:700">' + r.price_raw + '</span>' : fmtPrice(r)) + '</td>' +
      '<td>' + (r.location || '-') + '</td>' +
      '<td>' + mismatchIcon(m, r.title) + '<a class="pub" href="' + r.link + '" target="_blank">' + r.title + '</a></td>' +
      '</tr>';
  });
  html += '</tbody>';
  document.getElementById('tbl-moto').innerHTML = html;
}

// ---- VISTA POR VENDEDOR ----
function initVendedor() {
  const sellers = new Set();
  Object.values(DATA.modelos).forEach(o => {
    (o.rows || []).forEach(r => sellers.add(r.seller));
    (o.rows_app || []).forEach(r => sellers.add(r.seller));
  });
  const sel = document.getElementById('sel-vendedor');
  const pinned1 = [PACHECO, PUEYRREDON];
  const pinned2 = ['Cycles Motoshop', 'Moto Roma', 'Urquiza Motos', 'Automoto Lanus', 'BRM Bikes', 'Palermo Bikes', 'Motolandia', 'Marelli', 'Yamacity'];
  const allSellers = Array.from(sellers);
  const rest = allSellers.filter(s => !pinned1.includes(s) && !pinned2.includes(s)).sort();
  function addOpt(s) { const o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o); }
  function addSep(label) { const o = document.createElement('option'); o.disabled = true; o.textContent = '─────────────'; sel.appendChild(o); }
  pinned1.filter(s => allSellers.includes(s)).forEach(addOpt);
  addSep();
  pinned2.filter(s => allSellers.includes(s)).forEach(addOpt);
  addSep();
  rest.forEach(addOpt);
  // Filtro por marca
  const selB = document.getElementById('sel-vmarca');
  const optBAll = document.createElement('option');
  optBAll.value = '__all__'; optBAll.textContent = 'Todas';
  selB.appendChild(optBAll);
  const marcas = [...new Set(Object.keys(DATA.modelos).map(brandOf))].sort();
  function addVSep() { const o = document.createElement('option'); o.disabled = true; o.textContent = '─────────────'; selB.appendChild(o); }
  function addVOpt(b) { const o = document.createElement('option'); o.value = b; o.textContent = b.toUpperCase(); selB.appendChild(o); }
  addVSep();
  if (marcas.includes('yamaha')) { addVOpt('yamaha'); addVSep(); }
  marcas.filter(b => b !== 'yamaha').forEach(addVOpt);
  // Filtro por modelo
  fillModelos('__all__');
  renderVendedor();
}
function brandOf(modelo) { return modelo.split(' ')[0]; }

function fillModelos(marca) {
  const selM = document.getElementById('sel-vmodelo');
  selM.innerHTML = '';
  const optAll = document.createElement('option');
  optAll.value = '__all__'; optAll.textContent = 'Todos';
  selM.appendChild(optAll);
  Object.keys(DATA.modelos)
    .filter(m => marca === '__all__' || brandOf(m) === marca)
    .sort((a, b) => modelLabel(a).localeCompare(modelLabel(b), 'es', {numeric: true}))
    .forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = modelLabel(m);
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
    srcRows(o).forEach(r => {
      if (r.seller === v) rows.push({ ...r, modelo, searchUrl: o.url });
    });
  });
  // ads (rank null) siempre arriba de todo; luego organicos por modelo + rank
  rows.sort((a,b) => {
    if (a.isAd !== b.isAd) return a.isAd ? -1 : 1;
    return a.modelo.localeCompare(b.modelo) || (a.rank == null ? 999 : a.rank) - (b.rank == null ? 999 : b.rank);
  });

  const summary = document.getElementById('vendedor-summary');
  const organicRows = rows.filter(r => r.rank != null);  // los Ads no cuentan para rank
  // Ranking promedio = promedio del MEJOR rank de cada modelo (ignora publis que no son del modelo)
  const bestPerModel = {};
  organicRows.forEach(r => {
    if (titleMismatch(r.modelo, r.title)) return;
    if (!(r.modelo in bestPerModel) || r.rank < bestPerModel[r.modelo]) bestPerModel[r.modelo] = r.rank;
  });
  const bestVals = Object.values(bestPerModel);
  const avgRank = bestVals.length ? (bestVals.reduce((a,b)=>a+b,0)/bestVals.length).toFixed(1) : '—';
  const top3 = bestVals.filter(rk => rk <= 3).length;
  summary.innerHTML =
    stat(rows.length, 'Publicaciones') +
    stat(new Set(rows.map(r=>r.modelo)).size, 'Modelos') +
    stat(avgRank, 'Ranking promedio') +
    stat(top3, 'En top 3');

  // comentarios vendedor
  var vIns = [];
  var isCiclofox = v === PACHECO || v === PUEYRREDON;
  if (isCiclofox && rows.length) {
    var bestByModel = {};
    organicRows.forEach(r => {
      if (titleMismatch(r.modelo, r.title)) return;  // ignora publis que no son del modelo
      if (!bestByModel[r.modelo] || r.rank < bestByModel[r.modelo].rank)
        bestByModel[r.modelo] = r;
    });
    var allBad = Object.values(bestByModel).filter(r => r.rank >= 9).sort((a,b) => b.rank - a.rank);
    var badModels = allBad.slice(0, 3);
    if (badModels.length > 0) {
      vIns.push('⚠️ Revisar posicionamiento:');
      badModels.forEach(r => { vIns.push('&nbsp;&nbsp;• <b>' + r.modelo.toUpperCase() + '</b> — posición #' + r.rank); });
      if (allBad.length > 3) { var extra = allBad.length - 3; vIns.push('&nbsp;&nbsp;+ hay <b>' + extra + '</b> modelo' + (extra > 1 ? 's' : '') + ' más con rank mayor a #8 para revisar'); }
    }
  }
  // modelos de este vendedor con Ads activos
  var adModelos = [...new Set(rows.filter(r => r.isAd).map(r => r.modelo))];
  if (adModelos.length > 0) {
    vIns.push('📢 Con Ads activos:');
    adModelos.slice(0, 3).forEach(m => { vIns.push('&nbsp;&nbsp;• <b>' + m.toUpperCase() + '</b>'); });
    if (adModelos.length > 3) { var extraAd = adModelos.length - 3; vIns.push('&nbsp;&nbsp;+ tiene <b>' + extraAd + '</b> modelo' + (extraAd > 1 ? 's' : '') + ' más con Ads'); }
  }
  document.getElementById('vendedor-insights').innerHTML = comentariosHeader(TIP_VENDEDOR) + (vIns.length ? vIns.map(i => '<div style="margin-bottom:4px">' + i + '</div>').join('') : '<div style="color:#86868b">Sin comentarios para esta concesionaria.</div>');

  window._vRows = rows;
  window._vIsCiclofox = isCiclofox;
  window._vSortCol = null;
  window._vSortAsc = true;
  renderVendedorTable(rows, isCiclofox);
}

var vCols = ['marca','modelo','rank','precio','ubicacion','publicacion','busqueda'];
function sortVendedor(colIdx) {
  var key = vCols[colIdx];
  if (window._vSortCol === key) window._vSortAsc = !window._vSortAsc;
  else { window._vSortCol = key; window._vSortAsc = true; }
  var sorted = window._vRows.slice().sort(function(a, b) {
    var va, vb;
    if (key === 'marca') { va = brandLabel(a.modelo).toLowerCase(); vb = brandLabel(b.modelo).toLowerCase(); }
    else if (key === 'modelo') { va = modelOnlyLabel(a.modelo).toLowerCase(); vb = modelOnlyLabel(b.modelo).toLowerCase(); }
    else if (key === 'rank') { va = a.rank == null ? 999 : a.rank; vb = b.rank == null ? 999 : b.rank; }
    else if (key === 'precio') { va = a.price_num || 0; vb = b.price_num || 0; }
    else if (key === 'ubicacion') { va = (a.location||'').toLowerCase(); vb = (b.location||'').toLowerCase(); }
    else if (key === 'publicacion') { va = a.title.toLowerCase(); vb = b.title.toLowerCase(); }
    else { va = 0; vb = 0; }
    if (va < vb) return window._vSortAsc ? -1 : 1;
    if (va > vb) return window._vSortAsc ? 1 : -1;
    return 0;
  });
  renderVendedorTable(sorted, window._vIsCiclofox);
}
function renderVendedorTable(rows, isCiclofox) {
  var headers = ['Marca','Modelo','Rank','Precio','Ubicacion','Publicacion','Busqueda'];
  var hhtml = '<thead><tr><th style="cursor:default;width:30px;text-align:center">&nbsp;</th>';
  headers.forEach(function(h, i) {
    var arrow = '';
    if (window._vSortCol === vCols[i]) arrow = '<span class="sort-arrow">' + (window._vSortAsc ? '▲' : '▼') + '</span>';
    hhtml += '<th class="' + (i === 2 ? 'rank-col' : '') + '" onclick="sortVendedor(' + i + ')">' + h + arrow + '</th>';
  });
  hhtml += '</tr></thead><tbody>';
  rows.forEach(function(r, idx) {
    var cls = (isCiclofox && r.rank != null && r.rank >= 9) ? rowClass(r.seller) : '';
    hhtml += '<tr class="' + cls + '">' +
      '<td style="text-align:center;color:#999;font-size:12px">' + (idx + 1) + '</td>' +
      '<td>' + brandLabel(r.modelo) + '</td>' +
      '<td>' + modelOnlyLabel(r.modelo) + '</td>' +
      '<td class="rank rank-col">' + (r.rank == null ? '<span style="color:#86868b;font-size:11px">Ad</span>' : '#' + r.rank) + '</td>' +
      '<td>' + fmtPrice(r) + '</td>' +
      '<td>' + (r.location || '-') + '</td>' +
      '<td>' + mismatchIcon(r.modelo, r.title) + '<a class="pub" href="' + r.link + '" target="_blank">' + r.title + '</a></td>' +
      '<td><a class="seller-link" href="' + r.searchUrl + '" target="_blank">🔎 ver</a></td>' +
      '</tr>';
  });
  hhtml += '</tbody>';
  document.getElementById('tbl-vendedor').innerHTML = hhtml;
}

// Modelo con formato lindo para WhatsApp (codigos en mayuscula: FZ, MT, XTZ...)
function wsModel(m) {
  return m.split(' ').map(w =>
    (/^[a-z0-9-]{1,4}$/.test(w) && !/[aeiou]/.test(w)) ? w.toUpperCase()
    : w.charAt(0).toUpperCase() + w.slice(1)
  ).join(' ');
}
function _bestByModel(seller, src) {
  var best = {};
  Object.entries(DATA.modelos).forEach(([modelo, o]) => {
    (o[src] || []).forEach(r => {
      if (r.seller !== seller || r.rank == null) return;
      if (titleMismatch(modelo, r.title)) return;  // ignora publis que no son del modelo
      if (!(modelo in best) || r.rank < best[modelo]) best[modelo] = r.rank;
    });
  });
  return best;
}
function copiarResumenWsp() {
  var seller = document.getElementById('sel-vendedor').value;
  var pubs = new Set(), mods = new Set();
  Object.entries(DATA.modelos).forEach(([modelo, o]) => {
    ['rows', 'rows_app'].forEach(src => (o[src] || []).forEach(r => {
      if (r.seller !== seller) return;
      var id = (r.link || '').match(/MLA-?(\d+)/);
      pubs.add(id ? id[1] : (r.link || modelo)); mods.add(modelo);
    }));
  });
  function block(src) {
    var best = _bestByModel(seller, src);
    var n = Object.keys(best).length;
    var vals = Object.values(best);
    var avg = vals.length ? (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : '—';
    var bad = Object.entries(best).filter(e => e[1] >= 9).sort((a, b) => b[1] - a[1]);
    var lines = bad.map(e => '· ' + wsModel(e[0]) + ' (#' + e[1] + ')').join('\n');
    return 'Ranking promedio: #' + avg + '\n' +
      bad.length + ' / ' + n + ' modelos con mal rank\n' +
      (bad.length ? 'Modelos a revisar:\n' + lines + '\n' : '');
  }
  var gen = DATA.generated || '';
  var fecha = gen.length >= 16 ? gen.slice(8, 10) + '/' + gen.slice(5, 7) + ' ' + gen.slice(11, 16) : gen;
  var txt =
    '*RANKING MERCADO LIBRE — ' + seller.toUpperCase() + '*\n' +
    '_Actualizado: ' + fecha + '_\n\n' +
    '*Resumen:*\n' + pubs.size + ' publicaciones totales\n' + mods.size + ' modelos diferentes\n\n' +
    '*Web:*\n' + block('rows') + '\n' +
    '*App:*\n' + block('rows_app');
  navigator.clipboard.writeText(txt).then(() => {
    var b = document.getElementById('btn-wsp'), o = b.innerHTML;
    b.innerHTML = '✓ Copiado'; setTimeout(() => b.innerHTML = o, 1500);
  }).catch(() => { window.prompt('Copiá el resumen:', txt); });
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

// ---- VISTA EVOLUCIÓN ----
function initEvol() {
  const series = (HISTORY && HISTORY.series) || {};
  const sel = document.getElementById('ev-vendedor');
  sel.innerHTML = '';
  // mismo orden que el selector de concesionaria: Ciclofox primero
  const pinned = [PACHECO, PUEYRREDON];
  const all = Object.keys(series);
  const ordered = pinned.filter(s => all.includes(s)).concat(all.filter(s => !pinned.includes(s)).sort());
  ordered.forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o); });
  onEvolVendedor();
}
function onEvolVendedor() {
  const series = (HISTORY && HISTORY.series) || {};
  const v = document.getElementById('ev-vendedor').value;
  const selMk = document.getElementById('ev-marca');
  selMk.innerHTML = '';
  const modelos = Object.keys(series[v] || {});
  const marcas = [...new Set(modelos.map(m => m.split(' ')[0]))].sort((a,b)=>a.localeCompare(b,'es'));
  marcas.forEach(mk => { const o = document.createElement('option'); o.value = mk; o.textContent = titleCase(mk); selMk.appendChild(o); });
  onEvolMarca();
}
function onEvolMarca() {
  const series = (HISTORY && HISTORY.series) || {};
  const v = document.getElementById('ev-vendedor').value;
  const mk = document.getElementById('ev-marca').value;
  const selM = document.getElementById('ev-modelo');
  selM.innerHTML = '';
  const modelos = Object.keys(series[v] || {}).filter(m => m.split(' ')[0] === mk)
    .sort((a,b)=>modelLabel(a).localeCompare(modelLabel(b),'es',{numeric:true}));
  modelos.forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = modelLabel(m); selM.appendChild(o); });
  renderEvol();
}
function renderEvol() {
  const series = (HISTORY && HISTORY.series) || {};
  const v = document.getElementById('ev-vendedor').value;
  const m = document.getElementById('ev-modelo').value;
  const pts = ((series[v] || {})[m]) || [];
  const empty = document.getElementById('ev-empty');
  if (pts.length === 0) {
    document.getElementById('ev-chart').innerHTML = '';
    empty.textContent = 'Sin historial todavía para esta selección.';
    return;
  }
  if (pts.length === 1) {
    empty.innerHTML = '📌 Hay <b>1 sola medición</b> por ahora (' + pts[0][0] + '). El gráfico de evolución se va a ver cuando haya al menos 2 actualizaciones. Valores actuales — App: <b>' + (pts[0][2] ?? '—') + '</b> · Web: <b>' + (pts[0][1] ?? '—') + '</b>.';
  } else {
    empty.textContent = '';
  }
  document.getElementById('ev-chart').innerHTML = evolChart(pts);
}
// Gráfico SVG de líneas: rank en el tiempo (1 arriba). Verde=App, Gris=Web.
function evolChart(pts) {
  const W = 760, H = 320, padL = 38, padR = 16, padT = 16, padB = 56;
  const ranks = [];
  pts.forEach(p => { if (p[1] != null) ranks.push(p[1]); if (p[2] != null) ranks.push(p[2]); });
  const maxR = Math.max(5, ...ranks), minR = 1;
  const n = pts.length;
  const x = i => padL + (n === 1 ? (W-padL-padR)/2 : i * (W - padL - padR) / (n - 1));
  const y = r => padT + (r - minR) * (H - padT - padB) / (maxR - minR || 1);
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto;font-family:inherit">';
  // grilla horizontal + labels de rank
  const steps = Math.min(maxR, 8);
  for (let k = 0; k <= steps; k++) {
    const r = Math.round(minR + k * (maxR - minR) / steps);
    const yy = y(r);
    svg += '<line x1="' + padL + '" y1="' + yy + '" x2="' + (W-padR) + '" y2="' + yy + '" stroke="#eee"/>';
    svg += '<text x="' + (padL-6) + '" y="' + (yy+4) + '" text-anchor="end" font-size="10" fill="#999">#' + r + '</text>';
  }
  // labels de fecha (x)
  pts.forEach((p, i) => {
    const d = (p[0] || '').slice(0, 10);
    svg += '<text x="' + x(i) + '" y="' + (H-padB+18) + '" text-anchor="middle" font-size="9" fill="#999" transform="rotate(0)">' + d + '</text>';
  });
  function line(idx, color) {
    let d = '', dots = '';
    pts.forEach((p, i) => {
      const val = p[idx];
      if (val == null) return;
      const px = x(i), py = y(val);
      d += (d ? ' L' : 'M') + px + ' ' + py;
      dots += '<circle cx="' + px + '" cy="' + py + '" r="3.5" fill="' + color + '"/>';
    });
    return (d ? '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2"/>' : '') + dots;
  }
  svg += line(2, '#0071e3');  // App
  svg += line(1, '#86868b');  // Web
  svg += '</svg>';
  // leyenda
  svg += '<div style="display:flex;gap:18px;margin-top:6px;font-size:12px">' +
    '<span><span style="display:inline-block;width:12px;height:3px;background:#0071e3;vertical-align:middle;margin-right:5px"></span>App</span>' +
    '<span><span style="display:inline-block;width:12px;height:3px;background:#86868b;vertical-align:middle;margin-right:5px"></span>Web</span>' +
    '<span style="color:#86868b">(menor = mejor posición)</span></div>';
  return svg;
}
var TIP_MOTO =
  '💰 <b>Precio más bajo:</b> aparece solo si el precio mínimo lo tienen menos de la mitad de los vendedores (no cuenta planes de ahorro).\n' +
  '📋 <b>Plan de Ahorro:</b> publicaciones en cuotas (precio bajo). Indica qué vendedores lo ofrecen.\n' +
  '📢 <b>Con Ads activos:</b> vendedores que están pauteando este modelo.';
var TIP_VENDEDOR =
  '⚠️ <b>Revisar posicionamiento</b> (solo Ciclofox): modelos cuyo mejor rank orgánico es #9 o peor. Muestra los 3 peores.\n' +
  '📢 <b>Con Ads activos:</b> modelos de esta concesionaria que tienen Ads (muestra hasta 3).';
var TIP_PROCESO =
  '<b>¿Cómo se arma este ranking?</b>\n\n' +
  '1. Se busca el modelo en Mercado Libre (link de abajo) y se toman las primeras 20 publicaciones del listado.\n' +
  '2. Se filtran solo las 0km (se descartan usadas).\n' +
  '3. De cada publicación se identifica el vendedor: primero por el dato del listado o el título; si no se puede, se entra a la publicación para confirmarlo.\n' +
  '4. Las publicaciones patrocinadas (Ads) se muestran arriba de todo pero no ocupan puesto en el ranking. Tené en cuenta que los Ads pueden variar según el usuario y el día en que se hace la búsqueda.\n' +
  '5. Al resto se le asigna el rank según el orden en que Mercado Libre las muestra (posición 1, 2, 3…).\n\n' +
  '⚠️ Mercado Libre puede incluir publicaciones de modelos relacionados de la misma marca, por eso a veces el título de la publicación no coincide exactamente con el modelo buscado.\n\n' +
  'La actualización es manual; la fecha figura arriba a la derecha.';
function comentariosHeader(tip) {
  return '<div style="margin-bottom:6px"><span class="tip" style="font-weight:700">Comentarios ' +
    '<span class="tip-i">i</span><span class="tip-box">' + tip + '</span></span></div>';
}
// True si el titulo NO corresponde al modelo buscado.
// Match por tokens (alfa y numéricos) sin exigir orden ni contigüidad, así
// "Yamaha Ray Zr 125" matchea con "ray 125", pero "Skua 250" no matchea "skua 150".
// "full" es opcional (una base no se marca como distinta de la full y viceversa).
function titleMismatch(modelo, title) {
  var t = (title || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  var rest = modelo.split(' ').slice(1).join(' ').toLowerCase().replace(/full/g, ' ');
  var toks = rest.match(/[a-z]+|[0-9]+/g) || [];
  if (!toks.length) return false;
  // Los tokens deben aparecer en orden y CERCA (hasta 6 chars entre uno y otro):
  // "Ray Zr 125" matchea "ray 125"; "Skua 250 0km No 150" NO matchea "skua 150".
  var re = new RegExp(toks.join('[a-z0-9]{0,6}'));
  return !re.test(t);
}
function mismatchIcon(modelo, title) {
  if (!titleMismatch(modelo, title)) return '';
  return '<span class="tip tip-float" style="margin-right:4px">⚠️' +
    '<span class="tip-box tip-box--sm">El título de la publicación <b>no coincide</b> con el modelo buscado. ' +
    'Mercado Libre incluye resultados de modelos relacionados de la misma marca, por eso esta publicación puede ser de otro modelo.</span></span>';
}
function posColor(rank) {
  if (!rank || rank === '—' || rank === 'Ad') return '#86868b';
  var n = parseInt(String(rank).replace('#',''));
  if (isNaN(n)) return '#86868b';
  if (n <= 3) return '#34c759';
  if (n <= 8) return '#e8a317';
  return '#ff3b30';
}
// Mejor rank organico de un vendedor; si solo tiene Ad muestra "Ad"; si no, "—"
function sellerRankDisp(rows, pred) {
  var organic = rows.find(r => pred(r) && r.rank != null);
  if (organic) return '#' + organic.rank;
  if (rows.some(r => pred(r))) return 'Ad';
  return '—';
}
function posStat(rank, lbl) {
  var display = rank || '—';
  var color = posColor(rank);
  return '<div class="stat"><div class="num rank-col" style="color:' + color + '">' + display + '</div><div class="lbl">' + lbl + '</div></div>';
}
function esc(s){ return s.replace(/'/g,"\\'"); }

function setSource(s) {
  RANK_SOURCE = s;
  document.querySelectorAll('.tab[data-src]').forEach(t => t.classList.toggle('active', t.dataset.src === s));
  if (!document.getElementById('view-moto').classList.contains('hidden')) renderMoto();
  if (!document.getElementById('view-vendedor').classList.contains('hidden')) renderVendedor();
}
var currentView = 'vendedor';
var MODE = 'actual';
function setView(v) {
  currentView = v;
  document.querySelectorAll('.tab[data-view]').forEach(t => t.classList.toggle('active', t.dataset.view === v));
  if (MODE !== 'actual') return;
  document.getElementById('view-moto').classList.toggle('hidden', v !== 'moto');
  document.getElementById('view-vendedor').classList.toggle('hidden', v !== 'vendedor');
  document.getElementById('controls-moto').classList.toggle('hidden', v !== 'moto');
  document.getElementById('controls-vendedor').classList.toggle('hidden', v !== 'vendedor');
  document.getElementById('controls-vendedor-moto').classList.toggle('hidden', v !== 'vendedor');
  document.getElementById('moto-summary').classList.toggle('hidden', v !== 'moto');
  document.getElementById('vendedor-summary').classList.toggle('hidden', v !== 'vendedor');
  document.getElementById('moto-link').classList.toggle('hidden', v !== 'moto');
  document.getElementById('moto-insights').classList.toggle('hidden', v !== 'moto');
  document.getElementById('vendedor-insights').classList.toggle('hidden', v !== 'vendedor');
  document.getElementById('btn-wsp').classList.toggle('hidden', v !== 'vendedor');
}
function setMode(m) {
  MODE = m;
  document.querySelectorAll('.tab[data-mode]').forEach(t => t.classList.toggle('active', t.dataset.mode === m));
  var evo = (m === 'evolutivo');
  document.getElementById('view-evolucion').classList.toggle('hidden', !evo);
  document.getElementById('panel-resultados').classList.toggle('hidden', evo);
  document.getElementById('src-tabs').classList.toggle('hidden', evo);
  document.getElementById('view-tabs').classList.toggle('hidden', evo);
  document.getElementById('filtros-col').classList.toggle('hidden', evo);
  if (evo) {
    ['view-moto','view-vendedor','controls-moto','controls-vendedor','controls-vendedor-moto',
     'moto-summary','vendedor-summary','moto-link','moto-insights','vendedor-insights','btn-wsp']
      .forEach(id => document.getElementById(id).classList.add('hidden'));
    renderEvol();
  } else {
    setView(currentView);
  }
}

// ---- AUTH ----
let CURRENT_USER = null;

async function doLogin() {
  const email = document.getElementById('auth-email').value.trim();
  const pass  = document.getElementById('auth-pass').value;
  const errEl = document.getElementById('auth-err');
  const btn   = document.getElementById('auth-btn');
  errEl.textContent = '';
  if (!email || !pass) { errEl.textContent = 'Completá email y contraseña'; return; }
  btn.disabled = true; btn.textContent = 'Entrando…';
  const { error } = await sb.auth.signInWithPassword({ email, password: pass });
  btn.disabled = false; btn.textContent = 'Entrar';
  if (error) { errEl.textContent = 'Email o contraseña incorrectos'; document.getElementById('auth-pass').select(); return; }
  await enterApp();
}

async function loadRole() {
  const { data: { user } } = await sb.auth.getUser();
  if (!user) { CURRENT_USER = null; return; }
  let role = 'lectura';
  const { data } = await sb.from('profiles').select('role').eq('id', user.id).single();
  if (data && data.role) role = data.role;
  CURRENT_USER = { email: user.email, role };
}

function applyMode() {
  const isAdmin = !!(CURRENT_USER && CURRENT_USER.role === 'admin');
  document.body.classList.toggle('readonly', !isAdmin);
  const chip = document.getElementById('user-chip');
  if (chip && CURRENT_USER) {
    chip.innerHTML =
      '<span>' + CURRENT_USER.email + '</span>' +
      (isAdmin ? '<span class="role-badge role-admin">ADMIN</span>' : '<span class="role-badge role-lectura">LECTURA</span>') +
      '<button onclick="logout()">Salir</button>';
  }
}

async function logout() {
  try { await sb.auth.signOut(); } catch (e) {}
  location.reload();
}

async function enterApp() {
  await loadRole();
  applyMode();
  document.getElementById('auth-gate').remove();
  document.getElementById('main-app').style.display = '';
  initMoto();
  initVendedor();
  initEvol();
  setView('vendedor');
}

async function startApp() {
  const sub = document.getElementById('auth-sub');
  if (!sb) { if (sub) sub.textContent = 'Error de configuración Supabase.'; return; }
  try {
    const { data: { session } } = await sb.auth.getSession();
    if (session) { await enterApp(); return; }
  } catch (e) { console.warn('getSession falló:', e.message || e); }
  if (sub) sub.textContent = 'Ingresá con tu usuario';
  document.getElementById('auth-form').style.display = 'block';
  document.getElementById('auth-email').focus();
}

// Posiciona los tooltips de tabla (tip-float) con position:fixed para que no
// los recorte el scroll del contenedor.
function positionFloatTip(tip) {
  var box = tip.querySelector('.tip-box');
  if (!box) return;
  var r = tip.getBoundingClientRect();
  var w = box.offsetWidth || 280;
  box.style.position = 'fixed';
  box.style.top = (r.bottom + 4) + 'px';
  box.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
}
document.addEventListener('mouseover', function(e) {
  var tip = e.target.closest('.tip-float');
  if (tip) positionFloatTip(tip);
});

// Click en "Comentarios"/ícono "i"/⚠️ fija el tooltip; click afuera lo cierra
document.addEventListener('click', function(e) {
  var tip = e.target.closest('.tip');
  document.querySelectorAll('.tip.pinned').forEach(function(t) { if (t !== tip) t.classList.remove('pinned'); });
  if (tip) { e.stopPropagation(); tip.classList.toggle('pinned'); if (tip.classList.contains('tip-float')) positionFloatTip(tip); }
});

startApp();
</script>
</body>
</html>"""


def login_once():
    """Abre Chrome con el perfil dedicado y espera a que te loguees en ML.
    Corre esto UNA sola vez. Despues el perfil queda con la sesion guardada."""
    print(">> Abriendo Chrome con el perfil del scraper.")
    print(">> Logueate en Mercado Libre en la ventana que se abre.")
    driver = get_driver(use_profile=True)
    driver.get("https://www.mercadolibre.com.ar/")
    input(">> Cuando termines de loguearte, volve aca y apreta ENTER...")
    driver.quit()
    print(">> Sesion guardada. Ya podes correr: python ml_dashboard.py --profile")


if __name__ == "__main__":
    flags = {"--profile", "--html-only", "--login"}
    use_profile = "--profile" in sys.argv
    html_only = "--html-only" in sys.argv
    do_login = "--login" in sys.argv
    custom = [a for a in sys.argv[1:] if a not in flags]
    modelos = custom if custom else MODELOS
    try:
        if do_login:
            login_once()
        elif html_only:
            regenerar_html()
        else:
            main(modelos, use_profile=use_profile)
            # En una corrida completa (sin modelos custom) tambien refresca el comparador
            if not custom:
                print("\n=== Actualizando comparador de publicaciones ===")
                import subprocess
                r = subprocess.run([sys.executable, "comparador.py"],
                                   cwd=os.path.dirname(os.path.abspath(__file__)))
                if r.returncode != 0:
                    print("(El comparador termino con error; el ranking ya quedo actualizado)")
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
