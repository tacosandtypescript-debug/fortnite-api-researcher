# Investigador de la API de Fortnite

Proyecto base para consultar [Fortnite-API.com](https://fortnite-api.com/) y guardar cada resultado como JSON. Cuando se configuren las credenciales de Telegram, el resultado se entrega como **documento** mediante `sendDocument`, conservando el archivo original y evitando el flujo de foto comprimida.

Fortnite-API.com es una API comunitaria no oficial. La página pública documenta cosméticos, tienda, estadísticas, noticias, playlists, minimapa, banners, AES keys y códigos de creador. Las consultas generales pueden funcionar sin API key; el proyecto acepta `FORTNITE_API_KEY` opcional para rutas que la requieran.

## Puesta en marcha

Requiere Python 3.10 o posterior. En PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Edita `.env` y añade, cuando corresponda:

```text
FORTNITE_API_KEY=tu_key_de_fortnite_api
TELEGRAM_BOT_TOKEN=tu_token_del_bot
TELEGRAM_CHAT_ID=tu_chat_id
AUTO_SEND_TELEGRAM=true
```

No compartas ni subas `.env`. El `.gitignore` ya lo excluye.

## Consultas disponibles

Cada comando guarda un expediente JSON en `salidas/` con la ruta consultada, parámetros, fecha UTC y respuesta de la API.

```powershell
# Tienda actual en español
py -m fortnite_research shop --language es

# Noticias de Battle Royale en español
py -m fortnite_research news --kind br --language es

# Investigación de Salvar el Mundo: noticias, rutas candidatas y alertas de pavos
py -m fortnite_research stw --language es

# Búsqueda profunda: endpoint autenticado de Epic y rastreadores públicos de misiones
py -m fortnite_research stw-deep --language es

# Buscar todos los cosméticos de Battle Royale cuyo nombre contiene “Jonesy”
py -m fortnite_research cosmetic-search --name Jonesy --match-method contains --language es

# Consultar una ruta documentada directamente
py -m fortnite_research get /v1/playlists --param language=es

# Buscar rutas de servidores/regiones y medir NA-East, NA-Central y NA-West
py -m fortnite_research servers

# Investigar fechas de collabs y enviar informe + ZIP de imágenes CDN originales
py -m fortnite_research schedule-assets --language en --send

# Investigar una publicación sobre Loot Hacker Sprites y conservar su imagen
py -m fortnite_research sprites-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Investigar una Icon Cup, sus cosméticos API y sus recursos originales
py -m fortnite_research icon-cup-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Investigación profunda: tandas nuevas, skins, variantes, emotes y Festival
# Los recursos se mandan individualmente como documentos; no se manda el ZIP.
py -m fortnite_research deep-icon-cup-research --image "C:\ruta\a\Foto 1.jpg" --language en --send

# Revisar si ya hay datos oficiales del torneo y generar un guion para video
py -m fortnite_research video-brief --language en --send

# Crear un snapshot redactado de Fortnite-API, export beta y fuentes tempranas
# de contenido público de Epic (tournamentinformation, scoring, visuales, etc.)
python C:\Users\KTZ\.codex\skills\fortnite-api-research\scripts\fortnite_api_snapshot.py `
  --out "salidas\Fortnite API - base de conocimiento\snapshot-early.json" `
  --include-export --include-early --language en
```

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
py -m fortnite_research shop --language es --send
```

Con `AUTO_SEND_TELEGRAM=true`, los comandos que guarden un resultado intentarán enviarlo automáticamente. Si faltan `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID`, el proyecto falla de forma explícita y no simula un envío.

## Diseño de seguridad y calidad

- Las credenciales se leen desde variables de entorno y nunca se imprimen.
- `sendDocument` sube el JSON como archivo binario con `application/json`; no convierte a JPEG ni reduce dimensiones/calidad.
- Se valida la respuesta HTTP y el JSON devuelto antes de guardar o enviar.
- Las pruebas usan respuestas simuladas y no envían mensajes reales.
- El cliente permite conservar la respuesta completa de la API para futuras investigaciones y auditoría.

## Próxima ampliación

El skill reutilizable `fortnite-api-research` vive en `C:\Users\KTZ\.codex\skills\fortnite-api-research`. Además de las rutas documentadas de Fortnite-API.com, contiene el mapa de fuentes tempranas: páginas públicas de contenido de Epic, historial de datamining, wrappers, servicios de eventos protegidos y reglas para distinguir señal de API, contenido exportado y anuncio oficial.

Cuando me pases la API key, la incorporarás en `.env` (no en el chat ni en el código). Después se pueden añadir consultas específicas, por ejemplo estadísticas de jugador, código de creador, minimapa, AES keys o exportaciones con un formato editorial concreto. Si también quieres que yo haga los envíos reales, faltan el token del bot y el `chat_id`; no los invento ni los guardo por ti.
