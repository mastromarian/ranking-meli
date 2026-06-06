#!/usr/bin/env python3
"""
ML Ranking - Top 20 de MercadoLibre Argentina con vendedor

Vendedor:
  - Tiendas oficiales/certificadas: nombre real desde el listado
  - Resto: se deduce del titulo (heuristica) o queda como "(no visible)"

Uso:
    python ml_ranking.py "yamaha mt 03"
    python ml_ranking.py "yamaha nmax"
    python ml_ranking.py "hero hunk 150"

Instalacion:
    pip install selenium webdriver-manager beautifulsoup4
"""

import sys
import io
import re
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager


# Vendedores conocidos para deducir del titulo
KNOWN_SELLERS = [
    "Cycles", "Ciclofox", "Motolandia", "Patronelli", "Motoswift", "Antrax",
    "Marelli", "Motozuni", "Urquiza", "Moto Roma", "Motoroma", "BRM Bikes",
    "Mg Bikes", "Storero", "Automoto Lanus", "Bikecenter", "Ruta 3", "Oeste Motos",
    "Tamburrino", "Delisio", "Hot Motos", "Arizona", "Biaggi",
]


def search_to_url(query: str) -> str:
    if query.startswith("http"):
        return query
    slug = query.lower().strip().replace(" ", "-")
    return f"https://listado.mercadolibre.com.ar/{slug}"


def get_driver():
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
    """Entra a la publicacion y extrae el vendedor."""
    try:
        driver.get(url)
        time.sleep(1.5)
        text = BeautifulSoup(driver.page_source, "html.parser").get_text("\n")
        m = re.search(r"Informaci[oó]n de la (?:tienda|concesionaria)\s*\n([^\n]+)", text)
        if m:
            return m.group(1).strip()
        return "(no visible)"
    except Exception:
        return "(no visible)"


def scrape_ranking(query: str, top_n: int = 20, deep: bool = False) -> list:
    url = search_to_url(query)
    print(f"\nBuscando: {url}")
    if deep:
        print("(Modo profundo: visita cada publicacion. Tarda mas.)")
    print()

    driver = get_driver()
    results = []

    try:
        driver.get(url)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        items = soup.select(".ui-search-layout__item")

        for idx, item in enumerate(items[:top_n], 1):
            title_el = item.select_one(".poly-component__title")
            title = title_el.get_text(strip=True) if title_el else ""

            price_el = item.select_one(".andes-money-amount__fraction")
            price = "$" + price_el.get_text(strip=True) if price_el else ""

            location_el = item.select_one(".poly-component__location")
            location = location_el.get_text(strip=True) if location_el else ""

            attrs = [el.get_text(strip=True) for el in item.select(".poly-attributes_list__item")]
            attr_str = " | ".join(attrs)
            # 0km exacto: algun atributo es exactamente "0 km"
            is_0km = any(a.strip().lower() == "0 km" for a in attrs)

            link_el = item.select_one("a.poly-component__title, a[href*='MLA']")
            link = link_el["href"] if link_el else ""

            # Vendedor: 1) tienda oficial en listado
            seller_el = item.select_one(".poly-component__seller")
            seller = seller_el.get_text(strip=True) if seller_el else ""

            # 2) deducir del titulo
            if not seller:
                seller = guess_seller_from_title(title)

            is_ad = "is_advertising=true" in link or bool(item.select_one('[class*="advertising"]'))

            pos_match = re.search(r"[?&]position=(\d+)", link)
            position = int(pos_match.group(1)) + 1 if pos_match else idx

            results.append({
                "is_0km": is_0km,
                "position": position,
                "title": title,
                "price": price,
                "location": location,
                "attrs": attr_str,
                "seller": seller or "(no visible)",
                "isAd": is_ad,
                "link": link.split("#")[0],
            })

        # Modo profundo: completar vendedores faltantes entrando a la pagina
        if deep:
            for i, r in enumerate(results, 1):
                if r["seller"] == "(no visible)" and r["link"]:
                    print(f"  Completando {i}/{len(results)}...", end="\r")
                    r["seller"] = get_seller_from_page(driver, r["link"])
            print(" " * 40, end="\r")

    finally:
        driver.quit()

    results.sort(key=lambda x: x["position"] if isinstance(x["position"], int) else 999)
    return results


def filter_0km(results: list) -> list:
    """Deja solo 0km reales (descarta usadas y planes de ahorro)."""
    out = []
    for r in results:
        if not r.get("is_0km"):
            continue
        out.append(r)
    return out


def print_ranking(results: list):
    sep = "=" * 130
    print(sep)
    print(f"{'#':>2} | {'POS ML':>6} | {'VENDEDOR':<22} | {'PRECIO':>13} | {'UBICACION':<28} | PUBLICACION")
    print(sep)

    for rank, r in enumerate(results, 1):
        num      = str(rank).rjust(2)
        pos      = str(r["position"]).rjust(6)
        seller   = (r["seller"] or "-")[:22].ljust(22)
        price    = (r["price"] or "-").rjust(13)
        location = (r["location"] or "-")[:28].ljust(28)
        title    = r["title"]  # nombre completo, sin cortar
        tag      = " [AD]" if r["isAd"] else ""
        print(f"{num} | {pos} | {seller} | {price} | {location} | {title}{tag}")

    print(sep)
    print(f"Total: {len(results)} publicaciones")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("--deep", "--all")]
    deep = "--deep" in sys.argv
    show_all = "--all" in sys.argv  # por defecto filtra solo 0km
    query = " ".join(args) if args else "yamaha mt 03"
    try:
        results = scrape_ranking(query, 20, deep=deep)
        if not show_all:
            results = filter_0km(results)
            print(f"(Filtrado: solo 0km, {len(results)} publicaciones)\n")
        print_ranking(results)
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
