# Handoff — Scraper Ranking MeLi (estado actual)

> Lee esto antes de tocar el scraper. Resume el diagnóstico y la nueva lógica
> de funcionamiento tras el bloqueo de MercadoLibre (junio 2026).

## Diagnóstico

MercadoLibre empezó a exigir **sesión iniciada** para ver `listado.mercadolibre.com.ar`.

- Si corrés `python ml_dashboard.py` **sin flags**, ML redirige a
  `https://www.mercadolibre.com.ar/gz/account-verification` y devuelve **0 resultados**
  en todos los modelos.
- Es un flag **anti-bot del lado de ML**, NO un rediseño de la web.
- Se confirmó cargando una sola búsqueda y viendo el `current_url` redirigido
  (ver `diag_scrape.py`).

## Solución (ya funcionando)

1. **Correr siempre con `--profile`.** Usa una sesión logueada guardada en la carpeta
   `chrome_profile` (perfil DEDICADO del scraper, NO el Chrome real del usuario).
   Con eso ML devuelve los resultados normalmente.

2. **Login (primera vez o sesión caducada):** usar `diag_login.py`.
   - Abre Chrome con el perfil dedicado.
   - Espera el login manual **sin navegar a la fuerza** (detecta por cookies de sesión).
   - Ventana de 30 min.
   - Cuando imprime `LOGIN OK ... resultados`, la sesión quedó guardada en `chrome_profile`.
   - ⚠️ La versión original `--login` del `ml_dashboard.py` usa `input()` (espera ENTER):
     NO funciona lanzada desde Claude (consola no interactiva). Usar `diag_login.py`
     o lanzar `--login` en una terminal real del usuario.

3. **User-agent:** actualizado de Chrome/124 a **Chrome/149** (versión real instalada).
   UA desfasado levanta sospecha del anti-bot. Si el usuario actualiza Chrome,
   actualizar el UA en `get_driver()` para que coincida.

## Comandos verificados

| Acción | Comando |
|---|---|
| Login una vez (manual) | `python diag_login.py` |
| Un modelo de prueba | `python ml_dashboard.py "yamaha mt 03" --profile` → `OK (17 0km, 2 visitas)` |
| Todos los modelos (31) | `python ml_dashboard.py --profile` |
| Sumar/refrescar un modelo | `python ml_dashboard.py "siam qu110 full" --profile` (mergea: reemplaza/agrega ese modelo y mantiene el resto) |
| Solo regenerar HTML | `python ml_dashboard.py --html-only` |

**Si tira `invalid session id` repetido:** cerrar todas las ventanas de Chrome y reintentar.
El script ya tiene retry de 2 intentos por modelo.

## Ranking de la APP (vista "📱 App")

El dashboard tiene dos fuentes de ranking: **App** (default) y **Web**. La web y la
app ordenan distinto (la app prioriza tiendas oficiales; ej. fz 4.0 Pacheco sale #3 en
app vs #11 en web). **No es geo** (probado: mismo zipcode CABA, distinto orden).

**Cómo funciona el modo App:**
- Usa el endpoint real de la app iOS: `GET https://frontend.mercadolibre.com/sites/MLA/search`
  con header clave `x-card-type: polycard` (sin él devuelve solo 1 resultado).
- Requiere un token Bearer de la app (`APP_USR-1505-...`) + headers, guardados en
  **`app_session.json`**. Es la cuenta PERSONAL de Mariano (no Ciclofox), para no
  arriesgar la cuenta del negocio ante un ban por uso de API.
- `scrape_modelo_app()` parsea los `polycard` (title/price/location/attributes/is_advertising).
- El vendedor no viene en la API → se **enriquece por MLA-id** cruzando con las filas web
  (`enrich_app_sellers`), que sí resuelven vendedor (incluso visitando la publicación).
- `python ml_dashboard.py --profile` hace primero el scrape web (Selenium) y después la
  pasada App (HTTP), guardando `rows` y `rows_app` por modelo en ml_data.json.

**Capturar / refrescar el token (cuando expire → 401 o pocos resultados):**
⚠️ IMPORTANTE: Mariano **eliminó el certificado mitmproxy del iPhone por seguridad**
(no deja la CA confiada cuando no se usa). Antes de capturar hay que **reinstalarlo**.
1. PC: `mitmdump -s _mitm_capture.py --listen-port 8080` (IP PC: 192.168.1.3).
2. iPhone: Ajustes→Wi-Fi→(i)→Proxy Manual `192.168.1.3:8080`.
3. iPhone: **reinstalar el cert** → Safari a http://mitm.it → bajar perfil iOS →
   Ajustes→General→VPN y administración de dispositivos→Instalar →
   Ajustes→General→Información→Ajustes de confianza del certificado→activar mitmproxy.
4. Abrir app ML, buscar cualquier modelo → `_mitm_capture.py` reescribe `app_session.json` solo.
5. **Limpiar por seguridad:** sacar el proxy del Wi-Fi y **eliminar el perfil del cert**
   (Ajustes→General→VPN y administración de dispositivos→mitmproxy→Eliminar perfil).

## Archivos de diagnóstico (creados esta sesión, borrables)

- `diag_scrape.py` — carga 1 búsqueda y guarda screenshot + conteo de items.
- `diag_login.py` — login manual con perfil dedicado, detecta por cookies.
- `diag.png` — screenshot del muro de verificación de ML.

## Pendiente

Automatización nocturna en servidor. **Ojo:** ahora que requiere login, GitHub Actions
y VPS se complican (necesitan el `chrome_profile` con sesión válida, y la sesión puede
caducar). Hay que rediseñar ese plan con esto en cuenta.
