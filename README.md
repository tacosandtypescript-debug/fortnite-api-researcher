# Investigador de la API de Fortnite

Proyecto base para consultar [Fortnite-API.com](https://fortnite-api.com/) y guardar cada resultado como JSON. Cuando se configuren las credenciales de Telegram, el resultado se entrega como **documento** mediante `sendDocument`, conservando el archivo original y evitando el flujo de foto comprimida.

Fortnite-API.com es una API comunitaria no oficial. La página pública documenta cosméticos, tienda, estadísticas, noticias, playlists, minimapa, banners, AES keys y códigos de creador. Las consultas generales pueden funcionar sin API key; el proyecto acepta `FORTNITE_API_KEY` opcional para rutas que la requieran.

## Puesta en marcha

Requiere Python 3.10 o posterior. En PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install -e .
```

Edita `.env` y añade, cuando corresponda:

```text
FORTNITE_API_KEY=tu_key_de_fortnite_api
FORTNITE_API_TRUSTED_HOSTS=fortnite-api.com,www.fortnite-api.com
FORTNITE_API_BASE_URL=https://fortnite-api.com
FORTNITE_API_TIMEOUT=30
FORTNITE_OUTPUT_DIR=salidas
TELEGRAM_BOT_TOKEN=tu_token_del_bot
TELEGRAM_CHAT_ID=tu_chat_id
AUTO_SEND_TELEGRAM=true
TELEGRAM_ALLOW_CHAT_DISCOVERY=false
PENNY_NEW_CONTENT_MAX_AGE_HOURS=24
```

No compartas ni subas `.env`. El `.gitignore` ya lo excluye. La API key solo se
envía al hostname configurado en `FORTNITE_API_TRUSTED_HOSTS`; si usas un
servidor compatible distinto, añádelo explícitamente. `TELEGRAM_CHAT_ID` es la
opción segura y recomendada. El descubrimiento automático de chats está
desactivado por defecto y solo se habilita con
`TELEGRAM_ALLOW_CHAT_DISCOVERY=true`.

## Consultas disponibles

Cada comando guarda un expediente JSON en `salidas/` con la ruta consultada, parámetros, fecha UTC y respuesta de la API.

```powershell
# Tienda actual en español
python -m fortnite_research shop --language es

# Noticias de Battle Royale en español
python -m fortnite_research news --kind br --language es

# Investigación de Salvar el Mundo: noticias, rutas candidatas y alertas de pavos
python -m fortnite_research stw --language es

# Búsqueda profunda: endpoint autenticado de Epic y rastreadores públicos de misiones
python -m fortnite_research stw-deep --language es

# Bot: pavos, llamas gratis y contenido nuevo detectado, en español
python -m fortnite_research bot

# Buscar todos los cosméticos de Battle Royale cuyo nombre contiene “Jonesy”
python -m fortnite_research cosmetic-search --name Jonesy --match-method contains --language es

# Consultar una ruta documentada directamente
python -m fortnite_research get /v1/playlists --param language=es

# Buscar rutas de servidores/regiones y medir NA-East, NA-Central y NA-West
python -m fortnite_research servers

# Investigar fechas de collabs y enviar informe + ZIP de imágenes CDN originales
python -m fortnite_research schedule-assets --language en --send

# Investigar una publicación sobre Loot Hacker Sprites y conservar su imagen
python -m fortnite_research sprites-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Investigar una Icon Cup, sus cosméticos API y sus recursos originales
python -m fortnite_research icon-cup-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Investigación profunda: tandas nuevas, skins, variantes, emotes y Festival
# Los recursos se mandan individualmente como documentos; no se manda el ZIP.
python -m fortnite_research deep-icon-cup-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Revisar si ya hay datos oficiales del torneo y generar un guion para video
python -m fortnite_research video-brief --language en --send

Los comandos anteriores son autosuficientes y no dependen de rutas absolutas
de otro equipo. Para herramientas externas, usa su ruta local explícita.

## Diagnóstico y optimización segura de red en Windows

El script [scripts/optimizar-senal-fortnite.ps1](scripts/optimizar-senal-fortnite.ps1) mide la señal Wi‑Fi disponible, el canal, la pérdida de paquetes y la latencia hacia los endpoints de diagnóstico de Epic. Por defecto solo audita y genera un JSON; con `-Apply` ejecuta únicamente la limpieza de caché DNS y devuelve el autoajuste TCP de Windows a `normal`. No modifica MTU, registro, DNS, controladores ni firewall.

```powershell
# Auditoría y envío automático del reporte por Telegram
powershell -ExecutionPolicy Bypass -File .\scripts\optimizar-senal-fortnite.ps1

# Auditoría más aplicación explícita de los ajustes conservadores
powershell -ExecutionPolicy Bypass -File .\scripts\optimizar-senal-fortnite.ps1 -Apply
```

El script no puede aumentar físicamente la señal de una antena ni garantizar menos ping: mide la ruta real desde este equipo y deja evidencia para decidir si conviene usar NA-East, NA-Central o NA-West.

Para enviar una consulta concreta por Telegram, usa `--send`:

```powershell
python -m fortnite_research shop --language es --send
```

Con `AUTO_SEND_TELEGRAM=true`, los comandos que guarden un resultado intentarán enviarlo automáticamente. Si faltan `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID`, el proyecto falla de forma explícita y no simula un envío.

El comando `bot` consulta Penny para las alertas de Salvar el Mundo, consulta
`/v2/cosmetics/new?language=es` para contenido añadido al catálogo y consulta
`/v2/news/br` y `/v2/news/stw` para anuncios de eventos, torneos y noticias.
Cada novedad que tenga imagen se envía como foto con un pie en español que
incluye fecha de incorporación, hora de comprobación y su identificación o
modo. Si el CDN no permite que Telegram descargue la imagen, se conserva el
aviso como texto. Solo se aceptan fechas ISO o Unix dentro de
`PENNY_NEW_CONTENT_MAX_AGE_HOURS` (24 horas por defecto); las entradas sin
fecha válida o antiguas se descartan. La primera ejecución registra el feed
existente como línea base y no reenvía datos históricos. El estado se conserva
en `salidas/penny-alert-state.json` y no contiene tokens.

La API no ofrece actualmente un feed separado de altas de banners. El parser
sí reconoce una entrada con categoría o tipo `banner` si aparece en
`cosmetics/new`, pero no inventa una fecha comparando un catálogo completo;
sin `added` no se notifica para evitar falsos “nuevos”.

## Diseño de seguridad y calidad

- Las credenciales se leen desde variables de entorno y nunca se imprimen.
- `sendDocument` sube el JSON como archivo binario con `application/json`; no convierte a JPEG ni reduce dimensiones/calidad.
- Las novedades con imagen usan `sendPhoto` con la URL del CDN autorizado y
  mantienen la descripción en español en el pie de foto.
- Se valida la respuesta HTTP y el JSON devuelto antes de guardar o enviar.
- Las pruebas usan respuestas simuladas y no envían mensajes reales.
- El cliente permite conservar la respuesta completa de la API para futuras investigaciones y auditoría.

## Pruebas

Con el entorno virtual activado, ejecuta:

```powershell
python -m unittest discover -v
python -m compileall -q fortnite_research tests
```

Cuando tengas una API key, incorpórala únicamente en `.env` (no en el chat ni
en el código). Si también quieres hacer envíos reales por Telegram, configura
el token y un `chat_id` explícito.
