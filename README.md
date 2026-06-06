# 🏍️ Ranking MELI

Herramienta para analizar el posicionamiento de publicaciones de motos 0km en MercadoLibre Argentina.

Scrapea los listados de búsqueda, arma el ranking por modelo y genera un **dashboard HTML interactivo** con dos vistas: por moto y por vendedor.

## Características

- 📊 **Ranking por modelo** — top 20 de cada búsqueda, solo 0km
- 🏪 **Detección de vendedor** — identifica tiendas oficiales/verificadas y deduce el resto del título (minimiza visitas a cada publicación)
- 🔍 **Dos vistas en el dashboard:**
  - **Por moto:** elegís modelo → ranking + link de búsqueda
  - **Por vendedor:** filtros encadenados por vendedor, marca y modelo
- 📢 **Columna de Ads** — marca las publicaciones patrocinadas (requiere modo `--profile`)
- 🎨 Resaltado de cuentas propias (Ciclofox Pacheco / Pueyrredon)

## Requisitos

```bash
pip install selenium webdriver-manager beautifulsoup4
```

Necesitás Google Chrome instalado.

## Uso

### Dashboard completo (recomendado)

```bash
python ml_dashboard.py
```

Scrapea todos los modelos configurados en la lista `MODELOS` y genera:
- `ml_data.json` — datos crudos
- `ml_ranking.html` — dashboard interactivo (abrilo en el navegador)

### Modelos puntuales

```bash
python ml_dashboard.py "yamaha mt 03" "yamaha nmax"
```

### Capturar publicidades (Ads)

Usa tu sesión real de Chrome para que ML sirva los anuncios patrocinados:

```bash
# Cerrá Chrome completamente antes de correr esto
python ml_dashboard.py --profile
```

### Regenerar solo el HTML

Reconstruye el dashboard desde `ml_data.json` sin volver a scrapear:

```bash
python ml_dashboard.py --html-only
```

### Ranking simple en consola

```bash
python ml_ranking.py "yamaha mt 03"          # solo 0km
python ml_ranking.py "yamaha mt 03" --deep   # completa vendedores faltantes
python ml_ranking.py "yamaha mt 03" --all    # incluye usadas
```

## Configuración

En `ml_dashboard.py` podés editar:

- `MODELOS` — la lista de búsquedas a trackear
- `MI_CUENTA` — el código interno de tu cuenta (para resaltarla)
- `normalize_seller()` — reglas para unificar nombres de vendedores

## Notas

- ML personaliza resultados según ubicación y sesión. El scraper anónimo ve el ranking nacional por defecto.
- Las publicidades (pads) solo se sirven a sesiones reales; por eso el modo `--profile`.
- El script corre 100% local, no usa ninguna API paga.
