#!/usr/bin/env python3
"""Comparador de publicaciones Ciclofox: Pacheco vs Pueyrredon.
Scrapea las dos tiendas, mapea cada publicacion a un modelo y genera
comparador.html (standalone). Correr con Chrome cerrado:
    python comparador.py
"""
import re, time, json
from datetime import datetime
from bs4 import BeautifulSoup
import ml_dashboard as M   # al importar ya reconfigura stdout a utf-8

TIENDAS = {
    "Pacheco":    "https://vehiculos.mercadolibre.com.ar/_CustId_2321428787",
    "Pueyrredon": "https://listado.mercadolibre.com.ar/tienda/ciclofox/motos/",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def title_mismatch(modelo, title):
    t = norm(title)
    rest = re.sub(r"full", " ", " ".join(modelo.split(" ")[1:]).lower())
    toks = re.findall(r"[a-z]+|[0-9]+", rest)
    if not toks:
        return True
    return re.search("[a-z0-9]{0,6}".join(toks), t) is None


def model_of(title):
    """Devuelve el MODELO mas especifico que matchea, o None.
    Usa solo las primeras 5 palabras para evitar falsos positivos por keywords spam."""
    short = " ".join(title.split()[:5])
    hits = [m for m in M.MODELOS if not title_mismatch(m, short)]
    return sorted(hits, key=len)[-1] if hits else None


def ws_model(m):
    out = []
    for w in m.split(" "):
        if re.fullmatch(r"[a-z0-9-]{1,4}", w) and not re.search(r"[aeiou]", w):
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def scrape(driver, url):
    """Devuelve lista de dicts: {title, price, link}."""
    rows = []
    driver.get(url)
    time.sleep(4)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    for it in soup.select(".ui-search-layout__item"):
        t = it.select_one(".poly-component__title")
        if not t:
            continue
        title = t.get_text(strip=True)
        pe = it.select_one(".andes-money-amount__fraction")
        price = int(re.sub(r"[^\d]", "", pe.get_text())) if pe else 0
        a = it.select_one("a[href*='MLA'], a.poly-component__title")
        link = a["href"].split("#")[0] if a and a.has_attr("href") else ""
        rows.append({"title": title, "price": price, "link": link})
    return rows


def main():
    print("Scrapeando tiendas Ciclofox (cerra Chrome)...")
    driver = M.get_driver(use_profile=True)
    data = {}
    try:
        for suc, url in TIENDAS.items():
            rows = scrape(driver, url)
            for r in rows:
                r["modelo"] = model_of(r["title"])
            data[suc] = rows
            print(f"  {suc}: {len(rows)} publicaciones")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    html = build_html(data)
    import os
    os.makedirs("public", exist_ok=True)
    for fname in ("comparador.html", os.path.join("public", "comparador.html")):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
    print("Generado comparador.html y public/comparador.html")


def build_html(data):
    # agrupar por modelo
    modelos = {}
    otros = {"Pacheco": [], "Pueyrredon": []}
    for suc, rows in data.items():
        for r in rows:
            m = r["modelo"]
            if not m:
                otros[suc].append(r)
                continue
            modelos.setdefault(m, {"Pacheco": [], "Pueyrredon": []})
            modelos[m][suc].append(r)

    def cell(lst):
        if not lst:
            return '<td class="no">—</td>'
        precios = sorted(set(r["price"] for r in lst if r["price"]))
        pr = "$" + f"{precios[0]:,}".replace(",", ".") if precios else "s/precio"
        link = lst[0]["link"]
        n = len(lst)
        extra = f' <span class="cnt">x{n}</span>' if n > 1 else ""
        return f'<td class="si"><a href="{link}" target="_blank">{pr}</a>{extra}</td>'

    filas = []
    for m in sorted(modelos.keys(), key=lambda x: ws_model(x)):
        p = modelos[m]["Pacheco"]
        q = modelos[m]["Pueyrredon"]
        if p and q:
            estado, cls = "Ambas", "ambas"
        elif p:
            estado, cls = "Solo Pacheco", "solo-p"
        else:
            estado, cls = "Solo Pueyrredón", "solo-q"
        filas.append(
            f'<tr class="{cls}"><td class="num" style="text-align:center;color:#86868b;font-size:11px"></td>'
            f'<td class="mod">{ws_model(m)}</td>'
            f'{cell(p)}{cell(q)}<td class="est">{estado}</td></tr>'
        )

    np_ = sum(len(r) for r in data.get("Pacheco", []) and [data["Pacheco"]] or [[]])
    tot_p = len(data.get("Pacheco", []))
    tot_q = len(data.get("Pueyrredon", []))
    mod_p = len(set(r["modelo"] for r in data.get("Pacheco", []) if r["modelo"]))
    mod_q = len(set(r["modelo"] for r in data.get("Pueyrredon", []) if r["modelo"]))
    solo_p = sum(1 for m in modelos if modelos[m]["Pacheco"] and not modelos[m]["Pueyrredon"])
    solo_q = sum(1 for m in modelos if modelos[m]["Pueyrredon"] and not modelos[m]["Pacheco"])
    ambas = sum(1 for m in modelos if modelos[m]["Pacheco"] and modelos[m]["Pueyrredon"])
    gen = datetime.now().strftime("%d/%m/%Y %H:%M")

    otros_html = ""
    for suc in ("Pacheco", "Pueyrredon"):
        if otros[suc]:
            items = "".join(f"<li><a href='{r['link']}' target='_blank'>{r['title']}</a></li>" for r in otros[suc])
            otros_html += f"<div class='otros'><b>Sin clasificar — {suc}:</b><ul>{items}</ul></div>"

    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Comparador Publicaciones Ciclofox</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f7; color: #1d1d1f; padding: 20px; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin-bottom: 4px; }}
  .sub {{ color: #86868b; font-size: 13px; margin-bottom: 16px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .card .n {{ font-size: 22px; font-weight: 700; }}
  .card .l {{ font-size: 12px; color: #86868b; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; }}
  th {{ text-align: left; padding: 8px 12px; background: #e0e0e0; font-size: 11px; text-transform: uppercase;
       letter-spacing: .03em; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ background: #d0d0d0; }}
  th .arr {{ margin-left: 4px; opacity: .4; }}
  th.asc .arr::after {{ content: '▲'; }}
  th.desc .arr::after {{ content: '▼'; }}
  th:not(.asc):not(.desc) .arr::after {{ content: '⇅'; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f2; }}
  td.mod {{ font-weight: 600; }}
  td.si a {{ color: #1d1d1f; text-decoration: none; font-weight: 600; }}
  td.si a:hover {{ text-decoration: underline; }}
  td.no {{ color: #c4c4c8; text-align: center; }}
  .cnt {{ font-size: 10px; color: #86868b; }}
  td.est {{ font-size: 11px; font-weight: 600; }}
  tr.solo-p {{ background: #fff8e1; }}
  tr.solo-q {{ background: #eef7ff; }}
  tr.solo-p td.est {{ color: #b8860b; }}
  tr.solo-q td.est {{ color: #0066cc; }}
  .otros {{ margin-top: 18px; font-size: 12px; color: #555; }}
  .otros ul {{ margin: 4px 0 0 18px; }}
</style></head><body><div class="wrap">
  <div class="sub">En el listado se pueden ver los modelos publicados y quién los tiene publicados (Pueyrredón, Pacheco o Ambos).</div>
  <div class="cards">
    <div class="card"><div class="n">{tot_p}</div><div class="l">Pubs Pacheco</div></div>
    <div class="card"><div class="n">{tot_q}</div><div class="l">Pubs Pueyrredón</div></div>
    <div class="card"><div class="n">{ambas}</div><div class="l">Modelos en ambas</div></div>
    <div class="card"><div class="n">{solo_p}</div><div class="l">Solo Pacheco</div></div>
    <div class="card"><div class="n">{solo_q}</div><div class="l">Solo Pueyrredón</div></div>
  </div>
  <table id="tbl">
    <thead><tr>
      <th style="width:36px;text-align:center">#</th>
      <th onclick="sortBy(1)">Modelo<span class="arr"></span></th>
      <th onclick="sortBy(2)">Pacheco<span class="arr"></span></th>
      <th onclick="sortBy(3)">Pueyrredón<span class="arr"></span></th>
      <th onclick="sortBy(4)">Estado<span class="arr"></span></th>
    </tr></thead>
    <tbody>{''.join(filas)}</tbody>
  </table>
  {otros_html}
<script>
var _col = -1, _asc = true;
function renumber() {{
  var rows = document.getElementById('tbl').tBodies[0].rows;
  for (var i = 0; i < rows.length; i++) rows[i].cells[0].textContent = i + 1;
}}
function sortBy(col) {{
  var tbl = document.getElementById('tbl');
  var ths = tbl.querySelectorAll('th');
  if (_col === col) _asc = !_asc; else {{ _col = col; _asc = true; }}
  ths.forEach(function(th, i) {{ th.classList.remove('asc','desc'); if (i===col) th.classList.add(_asc?'asc':'desc'); }});
  var tb = tbl.tBodies[0];
  var rows = Array.from(tb.rows);
  rows.sort(function(a, b) {{
    var va = a.cells[col].innerText.trim().toLowerCase();
    var vb = b.cells[col].innerText.trim().toLowerCase();
    var na = parseFloat(va.replace(/[^0-9.]/g,''));
    var nb = parseFloat(vb.replace(/[^0-9.]/g,''));
    var cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : va.localeCompare(vb, 'es');
    return _asc ? cmp : -cmp;
  }});
  rows.forEach(function(r) {{ tb.appendChild(r); }});
  renumber();
}}
renumber();
</script>
</div></body></html>"""


if __name__ == "__main__":
    main()
