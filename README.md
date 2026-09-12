# Flight Monitor — Multi-Provider

Aplicación para comparar precios de vuelos de ida y vuelta, guardar las consultas en una base de datos y seguir su evolución. Consulta varios proveedores en paralelo y calcula una recomendación orientativa: **BUY**, **WATCH** o **WAIT**.

Está pensada como un **MVP de uso personal**, principalmente para búsquedas manuales ocasionales. Incluye un proceso opcional que repite las búsquedas diariamente. Se ejecuta con Docker Compose y puede probarse sin contratar ninguna API mediante datos simulados.

> El sistema no compra billetes. Una recomendación BUY es una señal calculada, no una garantía de disponibilidad ni de que el precio final de reserva coincida. Los resultados guardados pueden ser anteriores a la última búsqueda.

## Índice

- [Qué hace y qué no hace](#qué-hace-y-qué-no-hace)
- [Arquitectura](#arquitectura)
- [Proveedores y tipos de datos](#proveedores-y-tipos-de-datos)
- [Requisitos](#requisitos)
- [Arranque paso a paso](#arranque-paso-a-paso)
- [Configurar las credenciales](#configurar-las-credenciales)
- [Uso del dashboard](#uso-del-dashboard)
- [Datos demo y reales: separación y diagnóstico](#datos-demo-y-reales-separación-y-diagnóstico)
- [Crear una búsqueda personalizada](#crear-una-búsqueda-personalizada)
- [Cuotas y búsquedas programadas](#cuotas-y-búsquedas-programadas)
- [Cómo se calculan las recomendaciones](#cómo-se-calculan-las-recomendaciones)
- [API del proyecto](#api-del-proyecto)
- [Operación, actualizaciones y copias](#operación-actualizaciones-y-copias)
- [Despliegue en un servidor](#despliegue-en-un-servidor)
- [Resolución de problemas](#resolución-de-problemas)
- [Desarrollo y pruebas](#desarrollo-y-pruebas)
- [Limitaciones y mejoras pendientes](#limitaciones-y-mejoras-pendientes)

## Qué hace y qué no hace

Actualmente permite:

- Definir un aeropuerto de origen, varios destinos y rangos de fechas de salida y regreso.
- Consultar los proveedores habilitados para cada combinación de fechas y destino.
- Normalizar las ofertas y agrupar resultados parecidos.
- Guardar precios por proveedor, respuestas originales y recomendaciones en PostgreSQL.
- Mostrar las ofertas guardadas ordenadas por precio, su última consulta y el estado de los proveedores.
- Separar los resultados externos de los datos de demostración.
- Enviar una notificación opcional de Telegram cuando una oferta pasa a BUY.

Todavía no incluye un flujo completo de reserva, autenticación, administración de usuarios, edición de búsquedas desde el dashboard, control mensual global de cuotas ni selección automática de las fechas más baratas mediante calendarios.

## Arquitectura

```text
Navegador → Next.js (:3000)
     │
     └────→ FastAPI (:8000)
                  │
                  ├─ Orquestador → FlightPowers
                  │              → SerpApi
                  │              → Travelpayouts
                  │              → DataCrawler
                  │              → Mock, si no hay proveedores habilitados
                  │
                  ├─ PostgreSQL: búsquedas, ofertas e histórico
                  └─ Telegram: aviso opcional al pasar a BUY

Worker opcional → APScheduler → mismo orquestador → misma base de datos
```

| Servicio de Compose | Función | Tecnología |
| --- | --- | --- |
| `frontend` | Dashboard web | Next.js 15, React 19, TypeScript; Node.js 22 en Docker |
| `backend` | API, búsquedas y recomendaciones | Python 3.12, FastAPI, SQLAlchemy, HTTPX |
| `postgres` | Almacenamiento persistente | PostgreSQL 17 |
| `worker` | Ejecución diaria opcional | Python y APScheduler |

El backend espera a que PostgreSQL esté saludable y ejecuta `alembic upgrade head` antes de iniciar Uvicorn. El worker espera a PostgreSQL, pero no depende de que hayan terminado las migraciones del backend; conviene iniciarlo después del primer arranque correcto.

## Proveedores y tipos de datos

| Proveedor | Servicio integrado | Uso actual | `live` en el código |
| --- | --- | --- | --- |
| FlightPowers | Google Flights Live API, ida y vuelta | Itinerarios emparejados con precio conjunto según el proveedor | `True` |
| SerpApi | Google Flights | Descubrimiento de ofertas y `price_insights` | `True` |
| Travelpayouts | Aviasales Flight Data API | Referencia de precios de búsquedas anteriores, cacheada | `False` |
| DataCrawler | Google Flights en RapidAPI (`google-flights2`) | Descubrimiento limitado a unas pocas combinaciones | `False`, por precaución sobre el itinerario completo |
| Mock | Generador local determinista | Pruebas sin credenciales ni consultas externas | `False` |

**Datos reales**, en el dashboard, significa datos procedentes de proveedores externos. No significa necesariamente precio en vivo, tarifa confirmada o disponibilidad actual. Travelpayouts y DataCrawler aparecen en esta categoría aunque su marca interna `live` sea falsa.

La marca `live` interviene en la elegibilidad para BUY. En DataCrawler se mantiene falsa hasta verificar con respuestas reales la selección del regreso y el precio completo reservable; no es una afirmación de que DataCrawler sirva datos cacheados.

FlightPowers, SerpApi y DataCrawler acceden a Google Flights. Su coincidencia permite comparar extracciones, pero **no representa tres mercados independientes**. Travelpayouts aporta una referencia diferente, basada en caché.

### Cómo se habilitan

Cada proveedor se habilita cuando su variable de credencial tiene contenido. DataCrawler requiere además un límite por ejecución mayor que cero. Que aparezca habilitado **no valida la clave, la suscripción ni el saldo**.

Si no hay ninguno habilitado, se utiliza Mock. Si hay proveedores habilitados pero fallan todos, no se sustituyen sus errores por datos simulados: la ejecución puede acabar vacía y registrar los errores.

## Requisitos

Para la vía recomendada con Docker:

- Docker Desktop funcionando en macOS/Windows, o Docker Engine con el complemento Compose en Linux.
- Una copia de este repositorio.
- Conexión a Internet para descargar imágenes y dependencias y, con claves configuradas, consultar proveedores.
- Los puertos locales 3000 y 8000 disponibles.

Comprueba las herramientas:

```bash
docker --version
docker compose version
docker info
```

No necesitas instalar Node.js, Python o PostgreSQL en tu equipo para ejecutar la aplicación con Docker. Las credenciales externas son opcionales para probarla en modo demo.

## Arranque paso a paso

### 1. Entra en la carpeta

Abre una terminal en la raíz del repositorio, donde está `docker-compose.yml`:

```bash
cd /ruta/a/flight-monitor-multi-provider
```

Sustituye la ruta por la ubicación de tu copia.

### 2. Prepara `.env`

Si es la primera ejecución y **no existe** `.env`:

```bash
cp .env.example .env
```

Si ya existe, edítalo sin sobrescribirlo. Para una demostración, deja vacías las claves de todos los proveedores. No pegues credenciales en el código, capturas ni documentación. `.env` está excluido de Git; si has compartido una clave, sustitúyela por una nueva.

### 3. Arranca en modo manual

```bash
docker compose up -d --build postgres backend frontend
```

`--build` construye las imágenes y `-d` deja los servicios en segundo plano. El primer arranque tarda más porque descarga dependencias.

Si el worker ya estaba funcionando por una ejecución anterior, el comando anterior no lo detiene. Para asegurar el modo manual:

```bash
docker compose stop worker
```

### 4. Verifica el arranque

```bash
docker compose ps
docker compose logs --tail=100 backend frontend
curl http://localhost:8000/api/health
```

Health devuelve `{"ok":true}` cuando la API responde. Este endpoint no comprueba las credenciales externas ni hace una prueba exhaustiva de la base de datos.

Abre:

- [Dashboard](http://localhost:3000)
- [Swagger: documentación interactiva](http://localhost:8000/docs)
- [Estado de los proveedores](http://localhost:8000/api/providers)

### 5. Prueba la aplicación

Si no hay búsquedas, pulsa **Crear búsqueda BCN–Buenos Aires** y después **Buscar ahora**. Sin claves, abre la pestaña **Demostración** para ver los datos simulados. La pestaña de datos reales quedará vacía.

Con claves activas, revisa primero el tamaño de la búsqueda: el ejemplo es amplio y consume múltiples peticiones. Para una prueba de bajo consumo, utiliza la búsqueda de un único par de fechas descrita más adelante.

## Configurar las credenciales

Variables de `.env`:

| Variable | Necesaria | Efecto |
| --- | --- | --- |
| `FLIGHTPOWERS_API_KEY` | Solo para FlightPowers | Clave con suscripción a Google Flights Live API |
| `SERPAPI_API_KEY` | Solo para SerpApi | Clave de SerpApi |
| `TRAVELPAYOUTS_API_TOKEN` | Solo para Travelpayouts | Token de Aviasales Data API |
| `DATACRAWLER_API_KEY` | Solo para DataCrawler | Clave con suscripción a Google Flights de DataCrawler |
| `DATACRAWLER_MAX_REQUESTS_PER_RUN` | Opcional; defecto `5` | Máximo de intentos por ejecución; entero, `0` desactiva DataCrawler |
| `TELEGRAM_BOT_TOKEN` | Solo para alertas | Token del bot |
| `TELEGRAM_CHAT_ID` | Solo para alertas | Chat destinatario |

Las claves de los distintos proveedores son independientes en la configuración. No se copia automáticamente la clave de FlightPowers a DataCrawler, aunque una cuenta de RapidAPI pueda utilizar la misma clave para ambas suscripciones.

`DATABASE_URL` está configurada directamente en Compose para backend y worker. Las credenciales de PostgreSQL también están fijadas allí; añadir otra contraseña a `.env` no las cambia por sí solo.

Después de modificar `.env`, recrea los servicios afectados:

```bash
# Uso manual
docker compose up -d backend

# Si utilizas también las búsquedas diarias
docker compose up -d backend worker
```

Un simple `docker compose restart` no aplica cambios a las variables del contenedor existente. Si también cambió el código, añade `--build`.

### FlightPowers / Google Flights Live API

1. Accede a [la API de FlightPowers en RapidAPI](https://rapidapi.com/mtnrabi/api/google-flights-live-api).
2. Suscríbete al plan adecuado y obtén tu clave.
3. Guárdala como `FLIGHTPOWERS_API_KEY`.

El proyecto llama a:

```text
POST https://api.flightpowers.com/v1/flights/roundtrip
Cabecera: x-api-key
```

Según [la documentación de FlightPowers](https://flightpowers.com/integrations/api), ese dominio acepta la misma clave de RapidAPI y utiliza la misma suscripción. Su equivalente en RapidAPI es `/api/google_flights/roundtrip/v1` sobre `google-flights-live-api.p.rapidapi.com`, con cabeceras `x-rapidapi-host` y `x-rapidapi-key`.

`oneway` busca solo ida. Este proyecto utiliza `roundtrip`, enviando ambas fechas. La integración actual envía origen, destino, fechas, moneda, límite y escalas; todavía no transmite adultos ni clase a FlightPowers.

### SerpApi / Google Flights

Obtén tu clave en [SerpApi](https://serpapi.com/) y configura `SERPAPI_API_KEY`. Consulta su [documentación de Google Flights](https://serpapi.com/google-flights-api) y las condiciones de tu plan.

El proveedor utiliza `https://serpapi.com/search.json` con `engine=google_flights`, ida y vuelta (`type=1`), fechas, pasajeros, clase, moneda y `deep_search=true`. Recoge `best_flights`, `other_flights` y el nivel de precio de `price_insights`.

La selección explícita del regreso o ciertos detalles de reserva pueden requerir otra consulta con `departure_token`. Ese segundo paso no está implementado. Tampoco se transmite actualmente el filtro de escalas a SerpApi.

### Travelpayouts / Aviasales Flight Data API

1. Regístrate en [Travelpayouts](https://www.travelpayouts.com/).
2. Conecta tu cuenta al programa Aviasales.
3. En **Profile → API token**, copia tu token.
4. Configura `TRAVELPAYOUTS_API_TOKEN`.

Consulta los [requisitos de Data API](https://support.travelpayouts.com/hc/en-us/articles/203956083-Requirements-for-Aviasales-data-API-access) y su [documentación](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API).

El código usa `https://api.travelpayouts.com/aviasales/v3/prices_for_dates`, pide resultados por mes y después filtra las fechas exactas localmente. La respuesta se limita a 30 resultados; que no haya coincidencias no prueba que no existan vuelos para esas fechas.

**Esta API no lanza una búsqueda de precios en tiempo real.** Trabaja con precios almacenados de búsquedas anteriores; la documentación describe una caché de hasta siete días. No se debe confundir con Aviasales Flight Search API.

La Search API es otro producto: la documentación consultada durante esta integración exige 50.000 usuarios activos mensuales acreditados y reglas específicas sobre búsquedas iniciadas por usuarios, reservas y combinación con otros metabuscadores. No está integrada y sus condiciones no encajan directamente con este monitor automático multiproveedor. Revisa los [requisitos de acceso](https://support.travelpayouts.com/hc/en-us/articles/210995808-How-to-get-access-to-the-Aviasales-Search-API) y las [reglas de uso](https://support.travelpayouts.com/hc/en-us/articles/34788165535250-Search-API-usage-rules).

### DataCrawler / Google Flights en RapidAPI

1. Abre [Google Flights de DataCrawler](https://rapidapi.com/DataCrawler/api/google-flights2).
2. Suscríbete a esa API; tener una clave de RapidAPI sin la suscripción correspondiente no basta.
3. Configura:

```env
DATACRAWLER_API_KEY=tu_clave
DATACRAWLER_MAX_REQUESTS_PER_RUN=5
```

La [página de precios](https://rapidapi.com/DataCrawler/api/google-flights2/pricing), consultada el 12 de septiembre de 2026, mostraba Basic a $0 con 150 peticiones mensuales y límite estricto. Verifica siempre el plan vigente y los conceptos adicionales de plataforma antes de contratarlo.

La integración llama a `GET /api/v1/searchFlights` en `google-flights2.p.rapidapi.com`. Envía `departure_id`, `arrival_id`, `outbound_date`, `return_date`, adultos, clase y moneda. Usa `country_code=ES`, `language_code=en-US`, `search_type=best` y `show_hidden=0`.

Normaliza los grupos dentro de `data.itineraries`, acepta precios numéricos positivos y filtra escalas localmente. Si se ha pedido un máximo de escalas y una oferta no informa de ellas, se descarta. Los formatos inesperados se registran como errores; no se interpretan como resultados válidos.

Por ahora:

- Se consultan las primeras combinaciones del recorrido de fechas, no las más baratas.
- El límite incluye intentos fallidos y se reinicia para cada ejecución.
- Un HTTP 401, 403 o 429 bloquea nuevas llamadas de esa instancia; las ya iniciadas pueden terminar.
- No hay reintentos automáticos, paginación ni consultas de reserva.
- No se utiliza `getCalendarGrid`; emplearlo para preseleccionar fechas es una mejora pendiente.
- Las pruebas de integración usan respuestas simuladas. La selección completa de ida y vuelta no está validada con una respuesta real.

### Telegram opcional

Configura ambas variables de Telegram con el bot y chat que vayas a utilizar. Si falta cualquiera de las dos, no se envían mensajes.

El aviso se produce cuando una oferta no demo entra en BUY y su recomendación anterior no era BUY, o no existía. No se notifica cada repetición de BUY. Un error de Telegram puede interrumpir la finalización de una ejecución; no hay una cola de reintentos independiente.

## Uso del dashboard

1. Selecciona una búsqueda del desplegable.
2. Revisa **Estado de los proveedores**.
3. Pulsa **Buscar ahora** y espera; la petición permanece abierta hasta terminar el trabajo.
4. Consulta **Datos reales** o **Demostración**.

La interfaz muestra:

- Proveedores habilitados o sin configurar.
- Última ejecución, errores y, para DataCrawler, peticiones y combinaciones omitidas.
- Mejor precio externo guardado, recomendación y consenso.
- Fechas, destino, precio, aerolíneas, escalas y fecha de última consulta.

La lista muestra hasta 100 ofertas por categoría, ordenadas por precio. No se eliminan automáticamente las ofertas que no vuelven a aparecer: si la última ejecución está vacía, pueden seguir visibles resultados anteriores. La fecha **Consultado** ayuda a interpretar esa antigüedad.

El botón de crear el ejemplo solo aparece cuando no hay búsquedas. Para otros itinerarios utiliza Swagger o la API. Las fechas del ejemplo están fijadas en el código: actualízalas o crea otra búsqueda cuando dejen de ser futuras.

## Datos demo y reales: separación y diagnóstico

### Qué es Demo Air

**Demo Air es una aerolínea ficticia del generador local `MockProvider`.** Sus precios, escalas y duraciones son simulados. El generador utiliza una semilla derivada del origen, destino y fechas, por lo que repetir la misma combinación produce los mismos datos. No consulta una aerolínea ni un servicio externo y no consume cuota de proveedores.

El modo demo permite comprobar el recorrido completo dentro de la aplicación: crear una búsqueda, ejecutar el orquestador, guardar ofertas y snapshots en PostgreSQL y mostrar resultados en el navegador. **No comprueba que las claves externas funcionen ni que existan vuelos reservables.**

| Situación al ejecutar | Comportamiento | Dónde consultar el resultado |
| --- | --- | --- |
| Ningún proveedor externo habilitado | Se ejecuta Mock y se guardan ofertas simuladas | Demostración |
| Uno o más proveedores externos habilitados | Se consulta a esos proveedores; no se ejecuta Mock | Datos reales |
| Proveedores externos habilitados, todos sin resultados o con errores | La ejecución queda `empty`; no se genera demo como sustituto | Estado de los proveedores y últimas ejecuciones |
| Hay ofertas demo de una ejecución anterior y ahora se activan claves | Las ofertas demo se conservan separadas de las externas | Cada pestaña mantiene su categoría |
| Una ejecución nueva no vuelve a encontrar una oferta guardada | La oferta anterior permanece con su fecha de consulta | Revisar Consultado antes de interpretar el precio |

Cambiar de pestaña solo cambia qué resultados guardados se muestran. **No ejecuta otra búsqueda, no cambia las credenciales y no fuerza el modo demo.** Para generar demo nuevo deben estar deshabilitados todos los proveedores externos; si ya hay demo guardado, se puede consultar sin cambiar la configuración actual.

### Por qué antes solo se veía Demo Air

La consulta original ordenaba todas las ofertas guardadas por precio y devolvía las primeras 100 sin distinguir su procedencia. Los demo baratos podían ocupar toda esa lista y dejar fuera ofertas externas más caras. Además, una consulta real vacía no eliminaba los resultados demo anteriores. Ver únicamente Demo Air no demostraba que la última búsqueda no se hubiese ejecutado.

Durante el diagnóstico de esta instalación se observó una ejecución con 10 ofertas recibidas y errores HTTP 429 de FlightPowers. Después de separar los resultados, la API mostró 9 ofertas externas guardadas, incluidas de LEVEL. Es una observación de ese diagnóstico, **no un conjunto de resultados garantizado para una instalación nueva**, ni una confirmación actual de disponibilidad. El número de ofertas recibidas y el de filas guardadas puede diferir por la agrupación de itinerarios.

La corrección aplica el filtro de procedencia **antes** de ordenar y limitar a 100. Así, los demo no compiten con las ofertas externas por los puestos de la lista. No hace falta borrar los datos antiguos para beneficiarse del cambio.

### Qué muestra ahora cada pestaña

| Elemento | Datos reales | Demostración |
| --- | --- | --- |
| Procedencia | Etiqueta REAL; proveedores externos | Etiqueta DEMO; generador local |
| Precio | Precio externo guardado, pendiente de confirmar | Precio ficticio |
| Tarjetas de mejor precio, recomendación y consenso | Se calculan visualmente a partir de la primera oferta real guardada | No se muestran |
| Columna de proveedores | Número de proveedores del grupo | Simulador |
| Consenso | Valor calculado por el orquestador | No aplica |
| Estado | BUY, WATCH o WAIT, si existe recomendación | Simulado |
| Alertas de Telegram | Posibles al entrar en BUY | Excluidas explícitamente |

En la API, la clasificación se obtiene de los snapshots: una oferta con algún snapshot cuyo `provider` es `mock` pertenece a demo; las demás pertenecen a real. No se identifica por el texto «Demo Air» ni por `live=False`. Esto permite reconocer también el demo histórico sin una migración adicional. La respuesta demo devuelve `recommendation: null`, aunque puedan existir recomendaciones internas antiguas en la base. Sus campos numéricos de consenso se conservan en la respuesta por compatibilidad, pero el dashboard no los presenta como evidencia real.

### Cómo interpretar el diagnóstico

El panel **Estado de los proveedores** combina dos tipos de información:

- **Configuración actual:** `/api/providers` indica si cada proveedor está habilitado en el proceso del backend. No realiza llamadas de comprobación a las APIs externas.
- **Última ejecución guardada:** muestra cuándo se inició, cuántas ofertas recibió y los errores registrados. Una ejecución anterior puede corresponder a otras credenciales o a otra versión del código.

Un **HTTP 429** significa que el proveedor rechazó solicitudes por cuota o limitación de frecuencia. El código de estado por sí solo no permite distinguir cuál de las dos causas se produjo. Revisa el panel del proveedor y reduce fechas, destinos o frecuencia. Reiniciar Docker o separar demo y real no restablece una cuota externa.

Los errores nuevos se guardan como códigos HTTP o nombres de excepción, evitando incorporar la URL completa de una solicitud que podría incluir credenciales. Las ejecuciones históricas conservan el contenido con el que se guardaron; revisa y elimina datos sensibles antes de compartir respuestas de diagnóstico.

Las ejecuciones anteriores a esta mejora pueden no incluir `details.mode`, `details.providers` o `details.provider_usage`. La interfaz admite esa ausencia. No es necesario lanzar otra búsqueda de pago solo para consultar los resultados que ya están almacenados.

### Comprobar la separación sin consumir cuota

Sustituye `ID` por el identificador devuelto por `GET /api/searches`. Estos comandos son de lectura: no llaman a proveedores ni generan vuelos nuevos.

```bash
# Identificadores de las búsquedas guardadas
curl 'http://localhost:8000/api/searches'

# Estado de habilitación, sin mostrar las claves
curl 'http://localhost:8000/api/providers'

# Ofertas externas: categoría predeterminada
curl 'http://localhost:8000/api/searches/ID/results'

# Equivalente explícito
curl 'http://localhost:8000/api/searches/ID/results?source=real'

# Ofertas simuladas, con recommendation: null
curl 'http://localhost:8000/api/searches/ID/results?source=demo'

# Últimas ejecuciones y errores
curl 'http://localhost:8000/api/searches/ID/runs'
```

Si acabas de actualizar desde la pantalla antigua, reconstruye backend y frontend, y recarga el navegador:

```bash
docker compose up -d --build backend frontend
```

Si utilizas el worker, reconstruye también ese servicio para que use la misma versión del orquestador. Las imágenes incorporan el código durante la construcción; guardar un archivo en el repositorio no actualiza por sí solo un contenedor en ejecución.

## Crear una búsqueda personalizada

En [Swagger](http://localhost:8000/docs), abre `POST /api/searches`, pulsa **Try it out**, introduce los datos y ejecuta. También puedes usar:

```bash
curl --request POST 'http://localhost:8000/api/searches' \
  --header 'Content-Type: application/json' \
  --data '{
    "name": "BCN–EZE: prueba de un par de fechas",
    "origin": "BCN",
    "destinations": ["EZE"],
    "departure_from": "2026-11-25",
    "departure_to": "2026-11-25",
    "return_from": "2027-01-10",
    "return_to": "2027-01-10",
    "adults": 1,
    "cabin": "economy",
    "max_stops": 1,
    "ideal_price": 750,
    "target_price": 850,
    "max_price": 1100
  }'
```

Usa códigos IATA en mayúsculas y fechas futuras `YYYY-MM-DD`. Este ejemplo crea una sola combinación por ejecución. Crear la búsqueda no consulta proveedores; ejecutarla sí. Se crea activa para el worker.

Copia el `id` de la respuesta. Para ejecutarla, sustituye `ID`:

```bash
curl --request POST 'http://localhost:8000/api/searches/ID/run'
```

| Campo | Significado |
| --- | --- |
| `origin` / `destinations` | Origen único y lista de destinos |
| `departure_from` / `departure_to` | Intervalo inclusivo de salidas |
| `return_from` / `return_to` | Intervalo inclusivo de regresos |
| `adults` | Entre 1 y 9; el soporte varía por proveedor |
| `cabin` | Habitualmente `economy`, `premium_economy`, `business` o `first`; el esquema no limita los valores |
| `max_stops` | De 0 a 3, o `null`; el soporte varía por proveedor |
| `ideal_price` / `target_price` / `max_price` | Referencias para la puntuación, no filtros que eliminen ofertas |

La moneda de las búsquedas lanzadas por el orquestador es EUR. Actualmente no hay un campo de moneda en la API de creación. El esquema no valida completamente el orden de los rangos ni que el regreso sea posterior a la salida: introduce intervalos coherentes.

## Cuotas y búsquedas programadas

### Una ejecución puede consumir muchas peticiones

```text
Combinaciones = días de salida × días de regreso × número de destinos
```

Los intervalos incluyen ambos extremos. El ejemplo del dashboard tiene:

- 25 de noviembre a 9 de diciembre de 2026: 15 días.
- 2 a 10 de enero de 2027: 9 días.
- EZE y AEP: 2 destinos.

**15 × 9 × 2 = 270 combinaciones**, por proveedor sin límite local.

DataCrawler intenta como máximo cinco por defecto. Los otros proveedores no tienen un presupuesto local equivalente. Configurar varias claves activa las consultas a todos ellos.

El semáforo permite ocho combinaciones en paralelo y, dentro de cada una, consulta simultáneamente los proveedores. Eso no significa un máximo global de ocho peticiones HTTP. Tampoco es un limitador de solicitudes por minuto.

### El límite de DataCrawler no es mensual

Con cinco peticiones por ejecución, treinta ejecuciones pueden gastar 150 intentos. Una búsqueda diaria durante un mes de 31 días puede superar esa cifra. Varias búsquedas, llamadas manuales, procesos o usos de la clave fuera del proyecto suman consumo.

No hay contador mensual persistente compartido. El dashboard muestra consumo de la ejecución, no saldo de RapidAPI. Consulta el panel del proveedor para conocer el consumo real.

### Activar o desactivar el worker

Una vez que el backend ha arrancado y migrado la base:

```bash
docker compose up -d worker
```

El worker recorre las búsquedas activas cada día a las **06:00 Europe/Madrid**. El horario sigue esa zona, con sus cambios estacionales. No ejecuta un barrido inmediato al iniciarse. Necesita que el equipo, Docker y el proceso estén funcionando; no despierta un portátil suspendido.

Para detenerlo:

```bash
docker compose stop worker
```

`docker compose up -d --build` sin nombres de servicios también inicia el worker. Para conservar el modo manual, indica `postgres backend frontend` y detén cualquier worker previamente iniciado.

No hay endpoints para cambiar `active`, editar o borrar búsquedas. Por ahora, detener el worker es la forma más sencilla de evitar los barridos automáticos. Evita lanzar a la vez varias ejecuciones de la misma búsqueda: no hay bloqueo global entre API y worker.

## Cómo se calculan las recomendaciones

### Agrupación y consenso

Se agrupan ofertas por origen, destino, fechas, aerolíneas normalizadas y escalas. No se comparan números de vuelo ni todos los tramos; ofertas similares pueden pertenecer a itinerarios diferentes.

Para cada grupo se calcula el menor precio de la ejecución, mediana, dispersión y número de proveedores distintos. La dispersión es `(máximo - mínimo) / mediana`.

```text
acuerdo = 1 - min(dispersión, 0.30) / 0.30
consenso = 100 × (0.55 × min(1, proveedores / 2) + 0.45 × acuerdo)
```

La fórmula puede dar 72,5 de consenso a un único proveedor sin dispersión. No debe interpretarse como probabilidad estadística ni como prueba de confirmación entre fuentes independientes.

### Puntuación

| Componente | Peso |
| --- | --- |
| Precio frente a ideal, objetivo y máximo | 30 % |
| Histórico propio | 25 % |
| Nivel externo `low`, `typical` o `high` | 20 % |
| Escalas y duración | 10 % |
| Consenso | 15 % |

Con menos de cinco observaciones, el componente histórico recibe un valor neutral de 50. A partir de cinco, utiliza el porcentaje de observaciones con precio menor o igual al actual. Las observaciones son snapshots por proveedor; cinco snapshots no equivalen necesariamente a cinco días distintos.

La confianza se calcula como `min(100, 20 + consenso × 0.55 + fuentes_live × 20)`.

| Estado | Regla |
| --- | --- |
| `BUY` | Puntuación ≥ 82, confianza ≥ 60 y al menos una fuente marcada `live=True` |
| `WATCH` | Puntuación ≥ 65 si no cumple BUY |
| `WAIT` | Resto |

Travelpayouts, DataCrawler y Mock no habilitan BUY por sí solos. Sin embargo, en un grupo mixto el precio mínimo puede proceder de una fuente no live y otra fuente aportar la condición live. **No hay una verificación final independiente del precio mínimo**. Confirma la oferta antes de actuar.

Implementación: `backend/app/services/scoring.py` y `backend/app/services/orchestrator.py`.

## API del proyecto

Base local: `http://localhost:8000/api`. Los endpoints no tienen autenticación.

| Método | Ruta | Función |
| --- | --- | --- |
| GET | `/health` | Respuesta básica de disponibilidad de la API |
| GET | `/providers` | Proveedores y habilitación por configuración |
| GET | `/searches` | Listar búsquedas |
| POST | `/searches` | Crear una búsqueda |
| POST | `/searches/{id}/run` | Ejecutarla y esperar el resultado |
| GET | `/searches/{id}/results` | Hasta 100 ofertas externas guardadas |
| GET | `/searches/{id}/results?source=demo` | Hasta 100 ofertas de demostración |
| GET | `/searches/{id}/runs` | Últimas 20 ejecuciones |

El endpoint de ejecución devuelve `run_id`, `status`, `results` y `details`; `results` corresponde al contador `result_count` del registro. El listado de ejecuciones devuelve los registros con `result_count`, `started_at` y `finished_at`.

Las ejecuciones nuevas incluyen en `details`: modo real/demo, combinaciones, resultados y errores por proveedor y consumo de DataCrawler. `result_count` cuenta ofertas recibidas antes de agrupar; no tiene por qué coincidir con las filas del dashboard.

Los resultados incluyen `source` (`real` o `demo`) y `last_seen_at` (última vez que se guardó esa oferta). `source` solo acepta esos dos valores; cualquier otro devuelve HTTP 400. No existe paginación ni una categoría combinada `all`.

`ok` significa que se recibieron resultados; puede haber errores parciales. `empty` significa que no se recibieron ofertas, tanto por ausencia de resultados como por errores o filtros. Consulta siempre `provider_errors`. Un fallo no gestionado durante el guardado o Telegram puede dejar una ejecución marcada como `running`.

## Operación, actualizaciones y copias

### Comandos habituales

```bash
# Estado
docker compose ps

# Logs recientes
docker compose logs --tail=100 backend frontend worker

# Seguir logs del backend; Ctrl+C termina el seguimiento
docker compose logs -f backend

# Actualizar las imágenes tras cambios de código, en modo manual
docker compose up -d --build postgres backend frontend

# Detener y retirar los contenedores conservando datos
docker compose down
```

Los contenedores usan `restart: unless-stopped`. La persistencia depende del volumen `postgres_data`, cuyo nombre efectivo suele llevar el prefijo del proyecto Compose.

**No ejecutes `docker compose down -v` si quieres conservar el histórico:** elimina también los volúmenes del proyecto. No hace falta borrar la base para aplicar las migraciones normales.

### Copia de seguridad

Con PostgreSQL funcionando, guarda un archivo de nombre nuevo:

```bash
docker compose exec -T postgres pg_dump -U flight -d flights -Fc > flights-backup.dump
```

La redirección sobrescribe un archivo con el mismo nombre. Guarda las copias fuera del repositorio y verifica periódicamente que puedes restaurarlas. Contienen búsquedas y respuestas de proveedores.

Para comprobar una copia en una **base nueva y vacía** dentro del mismo PostgreSQL:

```bash
docker compose exec -T postgres createdb -U flight flights_restore_check
docker compose exec -T postgres pg_restore -U flight -d flights_restore_check < flights-backup.dump
docker compose exec -T postgres psql -U flight -d flights_restore_check -c 'SELECT count(*) FROM searches;'
```

Este ejemplo no cambia la base `flights` que usa la aplicación. Usa otro nombre si la base de comprobación ya existe. Una recuperación de producción requiere planificar la sustitución y detener escrituras.

## Despliegue en un servidor

El Compose incluido funciona con acceso desde `localhost`. No es una configuración terminada para publicar con dominio y HTTPS.

Antes de exponerlo:

1. Configura el dominio y un proxy con HTTPS que dirija tráfico al frontend y a la API.
2. Cambia la URL del frontend a la API accesible desde el navegador. `localhost` en el navegador remoto apunta al equipo del visitante.
3. Pasa `NEXT_PUBLIC_API_BASE_URL` durante la **construcción** del frontend y reconstruye la imagen. Actualmente Compose solo la declara en tiempo de ejecución y el Dockerfile no tiene un argumento de build para ella. Cambiar esa variable únicamente en Compose no resuelve el despliegue remoto.
4. Ajusta CORS en `backend/app/main.py`, que solo permite `http://localhost:3000`.
5. Añade control de acceso: las rutas permiten crear búsquedas y consumir cuotas sin autenticación. CORS no sustituye la autenticación.
6. Sustituye las credenciales de PostgreSQL fijadas en Compose y actualiza de forma coherente las conexiones. Si el volumen ya existe, cambiar `POSTGRES_PASSWORD` no cambia por sí solo la contraseña del usuario almacenado en la base.
7. Configura copias, almacenamiento persistente y acceso a puertos. PostgreSQL no publica un puerto al host en el Compose actual; frontend y backend sí.
8. Decide si debe ejecutarse el worker y comprueba el consumo esperado antes de iniciarlo.

La configuración de variables públicas de Next.js se explica en [su documentación](https://nextjs.org/docs/pages/guides/environment-variables). Docker describe el despliegue de Compose en [su guía de producción](https://docs.docker.com/compose/how-tos/production/).

No hay scripts de despliegue remoto, proxy HTTPS ni autenticación implementados en este repositorio.

## Resolución de problemas

| Síntoma | Qué comprobar |
| --- | --- |
| Docker no conecta al daemon | Abre Docker Desktop o inicia Docker Engine; prueba `docker info` |
| Puerto 3000 u 8000 ocupado | Detén el otro servicio o adapta los puertos; si cambias el de la API, revisa también URL de frontend y CORS |
| El backend no arranca | Revisa logs de `postgres` y `backend`, salud de PostgreSQL y errores de Alembic |
| `ModuleNotFoundError: app` durante migraciones | Comprueba que `backend/alembic.ini` conserva `prepend_sys_path = %(here)s` y reconstruye backend |
| Clave añadida pero proveedor desactivado | Recrea backend y, si lo usas, worker; no basta con reiniciar |
| DataCrawler desactivado con clave | Comprueba que el límite es un entero mayor que cero |
| HTTP 401 o 403 | Clave, suscripción específica y permisos de la API |
| HTTP 429 | Cuota o límite temporal; revisa el panel del proveedor y reduce rangos/frecuencia |
| Solo aparecen datos demo | No había proveedores externos habilitados al ejecutar; revisa `.env` y `/api/providers` |
| Datos reales vacíos con proveedor habilitado | Comprueba errores, fechas, filtros y formato; habilitado no significa credencial validada |
| DataCrawler omite combinaciones | Revisa su límite y si hubo 401/403/429; las omisiones se muestran en el dashboard |
| Travelpayouts devuelve vacío | Puede no tener datos cacheados de esas fechas o no incluirlas entre los 30 resultados mensuales |
| Fallo de conexión del dashboard | Comprueba API, URL incorporada al build y CORS |
| Resultados antiguos tras una búsqueda vacía | Es el comportamiento actual: se mantienen ofertas guardadas; revisa la fecha de consulta |
| No llega Telegram | Deben existir token y chat; tiene que haber una transición a BUY; revisa logs |
| El worker no ejecuta | Debe estar activo a las 06:00 Europe/Madrid y haber búsquedas activas; no hace un barrido al arrancar |

No publiques `.env` ni la salida completa de `docker compose config`: puede contener claves resueltas. Para validar la configuración sin mostrarlas utiliza:

```bash
docker compose config --quiet
```

## Desarrollo y pruebas

### Organización del código

```text
backend/
  app/
    api/routes.py             Endpoints y separación real/demo
    providers/base.py         Query y ProviderOffer
    providers/flightpowers.py Adaptador de FlightPowers
    providers/serpapi.py       Adaptador de SerpApi
    providers/travelpayouts.py Adaptador de Aviasales Data API
    providers/datacrawler.py  Adaptador de DataCrawler y límite por ejecución
    providers/mock.py         Datos simulados
    services/orchestrator.py  Paralelismo, agrupación, guardado y avisos
    services/scoring.py       Puntuación y recomendaciones
    services/telegram.py      Envío de avisos
    models.py                 Tablas de SQLAlchemy
    schemas.py                Esquemas de entrada/salida
    worker.py                 Programación diaria
  alembic/                    Migraciones
  tests/                      Pruebas automatizadas
frontend/
  app/page.tsx                Dashboard
  app/styles.css              Estilos
.env.example                  Plantilla sin credenciales
docker-compose.yml            Servicios y configuración
```

Tablas principales: `searches`, `search_runs`, `offers`, `price_snapshots` y `recommendations`. Los snapshots conservan el proveedor y su respuesta original. No hay política automática de retención: el histórico crece con el uso.

### Ejecutar las pruebas del backend

Con las imágenes construidas, sin arrancar dependencias adicionales:

```bash
docker compose run --rm --no-deps backend python -m unittest discover -s tests -v
```

La prueba `test_demo_cannot_hide_real_results` crea 101 ofertas demo baratas y una externa más cara en una base SQLite temporal. Comprueba que la externa aparece en datos reales pese al límite de 100 y que la respuesta demo no expone recomendaciones. No modifica la base PostgreSQL del usuario.

Las pruebas de DataCrawler utilizan HTTP simulado para comprobar normalización, filtrado, errores, desactivación y límite concurrente. No consumen cuota. Esto no certifica compatibilidad con todas las respuestas reales futuras del proveedor.

También puedes utilizar un entorno Python 3.12 local:

```bash
python3.12 -m venv /tmp/flight-monitor-dev
source /tmp/flight-monitor-dev/bin/activate
pip install -r backend/requirements.txt
cd backend
python -m unittest discover -s tests -v
```

La API sigue necesitando PostgreSQL para funcionar normalmente; ejecutar pruebas no equivale a levantar la aplicación completa.

## Limitaciones y mejoras pendientes

- Validar con respuestas reales y completar la selección de regreso de DataCrawler antes de considerarlo elegible como fuente live para BUY.
- Preseleccionar fechas con calendarios; actualmente se enumeran combinaciones y DataCrawler solo cubre las primeras.
- Añadir presupuesto mensual persistente, caché de consultas, límites de frecuencia y bloqueo entre procesos.
- Unificar filtros de pasajeros, clase y escalas entre proveedores; hoy no todos los aplican.
- Mejorar la identidad de los itinerarios: la huella actual puede agrupar vuelos distintos con fechas, aerolíneas y escalas iguales.
- Evitar confundir coincidencia entre extractores de Google Flights con independencia de mercados.
- Separar explícitamente precio orientativo y tarifa completa verificada antes de emitir BUY.
- Añadir gestión de búsquedas, autenticación, caducidad visible de ofertas y retención del histórico.
- Mejorar la gestión de fallos al guardar datos y enviar Telegram; no existe un trabajo de recuperación automática.

Las tarifas, condiciones y formatos de las APIs externas pueden cambiar. Los enlaces de esta guía permiten revisar la documentación del proveedor; el código del repositorio describe lo que está implementado actualmente.
