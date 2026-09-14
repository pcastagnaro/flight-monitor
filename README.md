# Flight Monitor · búsquedas escalonadas

Aplicación personal para buscar vuelos de ida y vuelta, comparar fuentes y guardar su evolución. FastAPI + PostgreSQL + Next.js. Incluye una UI con búsquedas avanzadas, caché persistente, recuperación ante fallos y seguimiento diario opcional.

## Arranque

1. Instala Docker y abre Docker Desktop.
2. Si todavía no tienes `.env`, copia `.env.example` a `.env`. Conserva las credenciales que ya tengas.
3. Ejecuta:

```bash
docker compose up -d --build postgres backend frontend
```

Abre [la UI](http://localhost:3000). Crea una búsqueda, estima su cobertura y pulsa **Buscar ahora**. Sin fuentes configuradas se generan datos de demostración. Las credenciales no se editan ni se envían desde el navegador.

El backend aplica `alembic upgrade head` antes de arrancar. La migración conserva búsquedas, ofertas y precios anteriores; añade opciones y tablas de control. **No borres el volumen para actualizar.** La agrupación de ofertas nuevas es más conservadora que en v2: algunas ofertas antiguas permanecen como observaciones históricas separadas.

## Qué ofrece la UI

- Origen IATA, hasta 8 destinos y rangos de salida y regreso.
- Adultos, clase, moneda (EUR, USD o GBP), escalas, estancia mínima/máxima, precio objetivo/máximo, aerolíneas y duración.
- Opción **Exigir ida y vuelta detalladas**: excluye resultados cuyo regreso no esté demostrado por segmentos. No equivale a tarifa revalidada para reservar.
- Estrategia escalonada o exhaustiva, selección de proveedores y permiso para fuentes experimentales.
- Estimación sin peticiones externas: combinaciones posibles, planificadas y omitidas.
- Filtros sobre ofertas guardadas: precio mínimo/máximo, escalas, aerolínea, destino, duración máxima y proveedor.
- Ordenamiento ascendente o descendente por columnas, paginación e histórico por oferta.
- Tres paletas de colores y vista compacta, con preferencias guardadas en el navegador.
- Antigüedad visible, filtro de últimas 6 horas y separación entre datos externos y demo/test.
- Diagnóstico por consulta: caché, vacío, error, filtrado, incompatibilidad, cuota, pausa y tiempo agotado.
- Activación o pausa de cada búsqueda para el worker diario.

El formulario crea búsquedas manuales por defecto. Una búsqueda ya guardada conserva sus parámetros; crea otra para comparar una configuración diferente. Los filtros de la tabla no consumen APIs.

## Explorar los resultados

### Filtros y ordenamiento

En **Filtrar ofertas guardadas**, combina los filtros para acotar las ofertas existentes. La duración máxima se introduce en **minutos**. El filtro de proveedor permite seleccionar también **Simulado** para las ofertas de demostración. Activa **Solo observaciones de las últimas 6 horas** para excluir precios antiguos.

**Limpiar filtros** muestra cuántos filtros están activos y los restablece, conservando el orden elegido. Cambiar un filtro o el orden vuelve a la primera página. Estas acciones consultan los datos guardados y no realizan nuevas búsquedas en proveedores.

Pulsa el encabezado de una columna para ordenar; pulsa otra vez para invertir el sentido. También puedes usar los selectores **Ordenar** y **Sentido**, especialmente en móvil.

| Columna | Criterio |
| --- | --- |
| Viaje | Destino |
| Salida / Regreso | Fecha de cada trayecto |
| Precio | Importe numérico |
| Aerolíneas | Lista de aerolíneas registrada |
| Escalas | Número de escalas |
| Duración | Duración en minutos |
| Consultado | Fecha de la última observación |

Los filtros y el ordenamiento se aplican **en el servidor, antes de paginar**, a todas las ofertas de la selección. La UI muestra hasta 100 ofertas por página. Los valores desconocidos aparecen al final en ambos sentidos; los filtros de duración o escalas excluyen ofertas sin ese dato verificado. Ordenar precios no convierte monedas.

El destacado **Menor precio de los resultados filtrados** aparece en la primera página al ordenar por precio ascendente. Si no hay coincidencias, revisa los filtros o la pestaña **Datos reales / Demostración** antes de ejecutar otra búsqueda.

### Apariencia y lectura de la tabla

En la cabecera puedes elegir **Índigo**, **Océano** o **Ciruela**, y activar **Vista compacta** para reducir el espacio entre filas. Ambas preferencias se guardan en el almacenamiento local de ese navegador y se recuperan al recargar; no se sincronizan entre dispositivos. Los filtros y el ordenamiento se restablecen al recargar.

Los indicadores combinan color y texto:

- **Verde:** vuelo directo, observación reciente o precio dentro del objetivo configurado. El objetivo solo se compara cuando coincide la moneda.
- **Ámbar:** observación de más de 6 horas.
- **Neutro:** número de escalas o dato sin verificar.

Estos colores facilitan la lectura; no certifican disponibilidad ni sustituyen la recomendación de compra. La tabla mantiene los encabezados visibles al desplazarse verticalmente, resalta la fila bajo el cursor o el foco y permite desplazamiento horizontal en pantallas pequeñas. Los encabezados ordenables son botones accesibles por teclado e indican su sentido de ordenación a los lectores de pantalla.

## Cómo funciona el escalonado

Para cada combinación seleccionada:

1. Se comprueba la compatibilidad de cada proveedor con pasajeros, clase y moneda.
2. Se revisan **todas las cachés compatibles** antes de realizar llamadas nuevas.
3. Sin una oferta útil en caché, se recorre la cadena:

```text
Travelpayouts → Ryanair* → FlightFinder* → Amadeus → Kiwi Tequila
             → FlightPowers → SerpApi → DataCrawler → fast-flights* → Chromium*
```

`*` requiere activación explícita como fuente experimental. FlightFinder y fast-flights necesitan dependencias opcionales; Chromium necesita además un navegador instalado.

En **escalonada**, una oferta que cumple los filtros detiene la cadena de esa combinación. Travelpayouts, las sumas de tarifas separadas de Ryanair y el entorno test de Amadeus aportan referencias, pero no detienen la cadena. Si todos los resultados de una fuente son descartados por los filtros, se prueba la siguiente.

En **exhaustiva**, se consultan todas las fuentes seleccionadas dentro de los presupuestos. No garantiza cubrir todo un rango si excede los límites.

El planificador distribuye muestras por los rangos de fechas y alterna destinos; evita consultar exclusivamente los primeros días. Omite salidas pasadas y combinaciones incompatibles con la estancia. Este muestreo **no garantiza encontrar el mínimo de todo el calendario**. Cada rango puede cubrir hasta 91 días; cada búsqueda ejecuta como máximo 120 combinaciones y 300 llamadas a adaptadores.

## Protección ante fallos y consumo

| Control | Comportamiento predeterminado |
| --- | --- |
| Caché positiva | 15 minutos, persistida en PostgreSQL |
| Caché de vacío | 60 segundos; los errores no se cachean como vacío |
| Reintentos | Un reintento para errores de transporte, timeout o HTTP 5xx, con espera variable |
| HTTP 401/403 | Sin reintento inmediato; pausa de 1 hora |
| HTTP 429 | Sin reintento inmediato; pausa de al menos 5 minutos y respeto de `Retry-After` hasta 24 horas |
| Fallos consecutivos | 3 fallos abren una pausa de al menos 5 minutos |
| Tiempo | 25 segundos por llamada; 120 segundos para la fase de consulta |
| Presupuesto por proveedor | 10 llamadas por ejecución y 500 por mes UTC; Chromium: 2 por ejecución |
| Presupuesto por búsqueda | 30 llamadas y 12 combinaciones por defecto |
| Concurrencia | Una ejecución global entre backend y worker, mediante advisory lock de PostgreSQL |

Las reservas de consumo se guardan **antes** de consultar: un fallo del proceso no devuelve artificialmente la cuota. El contador mide llamadas a adaptadores, **no unidades de facturación**. Amadeus puede pedir un token y consultar vuelos; Ryanair obtiene dos calendarios. Ambos casos pueden implicar dos HTTP por llamada. Ryanair y Travelpayouts reutilizan calendarios mensuales dentro de la ejecución. Comprueba el consumo real en el panel de cada API.

Los límites y pausas persisten tras reinicios. Una ejecución concurrente recibe HTTP 409. Una ejecución interrumpida se marca fallida al tomar el siguiente bloqueo. Los datos obtenidos se guardan antes de intentar enviar Telegram; un fallo de notificación no revierte resultados. No hay una cola durable de reenvío de alertas.

Una respuesta vacía o fallida no borra ofertas anteriores. Su fecha de observación permanece visible. Reutilizar caché no actualiza esa fecha ni añade puntos duplicados al histórico. La caché caducada hace más de un día se elimina al iniciar una búsqueda.

## Fuentes integradas

| Adaptador | Configuración | Alcance y calidad |
| --- | --- | --- |
| FlightPowers | `FLIGHTPOWERS_API_KEY` | Adaptador existente; solo 1 adulto/economy porque no transmite otros parámetros |
| SerpApi | `SERPAPI_API_KEY` | Google Flights; descubrimiento con regreso no revalidado |
| Travelpayouts | `TRAVELPAYOUTS_API_TOKEN` | Referencia cacheada; solo 1 adulto/economy |
| DataCrawler | `DATACRAWLER_API_KEY` | Google Flights; descubrimiento; mantiene su límite específico de peticiones |
| Amadeus | `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` | OAuth, itinerarios de ida y vuelta; test separado de producción |
| Kiwi Tequila | `KIWI_API_KEY` | Requiere acceso a Tequila; verifica ruta y fechas de ambos trayectos |
| Ryanair | `RYANAIR_ENABLED=true` | Calendarios públicos; 1 adulto/economy; suma orientativa de dos tarifas separadas |
| FlightFinder | `FLIGHTFINDER_ENABLED=true` | Kiwi/Skypicker público; **solo USD**, debido a una limitación del parser fijado |
| fast-flights | `FAST_FLIGHTS_ENABLED=true` | Google Flights por HTTP con consultas Protobuf; experimental |
| Chromium | `GOOGLE_BROWSER_ENABLED=true` | Último recurso con navegador local y parser determinista; experimental |

Los datos test de Amadeus aparecen en **Demostración**. Para producción, configura credenciales válidas de ese entorno y `AMADEUS_PRODUCTION=true`. La aplicación no crea cuentas, suscripciones ni autoriza pagos.

Una fuente habilitada solo acredita configuración local, no validez de claves ni disponibilidad. Las fuentes de Google comparten origen: su coincidencia no cuenta como mercados independientes. No se fusionan extractores distintos sin identidad comparable de sus segmentos. Los precios orientativos, test y cacheados no habilitan BUY. Se mantiene el scoring histórico conservador; con una sola fuente sin corroboración, puede no alcanzar confianza para BUY. No hay compra automática.

[Análisis de todos los repositorios y decisiones de integración](docs/SOURCES.md).

## Activar fuentes sin clave

Ryanair funciona con la imagen básica. En `.env`:

```dotenv
RYANAIR_ENABLED=true
```

Para FlightFinder y fast-flights:

```dotenv
INSTALL_EXPERIMENTAL=true
FLIGHTFINDER_ENABLED=true
FAST_FLIGHTS_ENABLED=true
```

Para añadir el último recurso de navegador:

```dotenv
INSTALL_BROWSER=true
GOOGLE_BROWSER_ENABLED=true
```

Después reconstruye backend y, si lo utilizas, worker:

```bash
docker compose up -d --build backend
# Solo si quieres seguimiento programado:
docker compose up -d --build worker
```

Marca también **Permitir fuentes experimentales** en la búsqueda. FlightFinder requiere seleccionar USD. La imagen con Chromium es más grande. Las fuentes públicas pueden cambiar de formato o bloquear solicitudes; el sistema muestra esos fallos y continúa con las alternativas permitidas. No utiliza resolución de CAPTCHA, proxies residenciales, perfiles personales ni LLM para inventar precios.

## Variables operativas

Consulta [.env.example](.env.example). Backend y worker comparten configuración mediante Compose.

- `PROVIDER_MAX_CALLS_PER_RUN`, `PROVIDER_MONTHLY_CALL_LIMIT`: límites comunes por proveedor.
- `DATACRAWLER_MAX_REQUESTS_PER_RUN`: límite adicional, `0` desactiva DataCrawler.
- `GOOGLE_BROWSER_MAX_CALLS_PER_RUN`: límite específico del navegador.
- `PROVIDER_TIMEOUT_SECONDS`, `SEARCH_TIMEOUT_SECONDS`, `CACHE_TTL_SECONDS`: tiempos en segundos.
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR o CRITICAL; acepta minúsculas. Un valor inválido impide el arranque.
- `NEXT_PUBLIC_API_BASE_URL`: URL accesible por el navegador, aplicada **durante el build**.
- `CORS_ORIGINS`: orígenes permitidos, separados por coma.

El motor admite además `<PROVEEDOR>_MAX_CALLS_PER_RUN` y `<PROVEEDOR>_MONTHLY_CALL_LIMIT` (por ejemplo `SERPAPI_MONTHLY_CALL_LIMIT`). Si usas Compose, añade esas variables a `x-provider-env`; escribir una variable no declarada únicamente en `.env` no la introduce en el contenedor.

Las claves no se cargan desde `.env` cuando ejecutas Python directamente; usa variables del proceso. Alembic respeta `DATABASE_URL`, igual que la API.

## Seguimiento y operaciones

```bash
# Iniciar seguimiento diario: 06:00 Europe/Madrid; no consulta al arrancar
docker compose up -d worker
# Detener seguimiento
docker compose stop worker
# Estado y diagnóstico
docker compose ps
docker compose logs --tail=100 backend worker
# Validar Compose sin imprimir credenciales
docker compose config --quiet
# Backup: elige un nombre nuevo antes de redirigir
docker compose exec -T postgres pg_dump -U flight -d flights -Fc > flights-backup.dump
```

El worker espera a que el backend haya terminado las migraciones. Si una búsqueda falla, continúa con las demás; si el bloqueo está ocupado, deja esa búsqueda para una ejecución posterior. La programación requiere además `active=true` en cada búsqueda.

La aplicación sigue orientada a uso personal y no incluye autenticación ni gestión de usuarios. Antes de publicar en Internet, configura control de acceso, HTTPS, credenciales de PostgreSQL propias y copias. CORS no es autenticación. No hay cambios de despliegue remoto incluidos.

## API

[Swagger](http://localhost:8000/docs) documenta los esquemas completos.

| Ruta | Uso |
| --- | --- |
| `GET /api/health` | Estado HTTP; no valida proveedores |
| `GET /api/providers` | Configuración, familias, consumo y pausas |
| `GET /api/searches` / `POST /api/searches` | Listar y crear búsquedas |
| `POST /api/searches/preview` | Estimar y listar combinaciones sin consultar proveedores |
| `POST /api/searches/{id}/run` | Ejecutar; devuelve resultado y diagnóstico |
| `PATCH /api/searches/{id}/active?active=false` | Pausar seguimiento |
| `GET /api/searches/{id}/results` | Filtros `source`, `min_price`, `max_price`, `max_stops`, `max_duration`, `provider`, `airline`, `destination`, `fresh_only`; orden `sort`, `direction`; paginación `limit`, `offset` |
| `GET /api/searches/{id}/runs` | Últimas 20 ejecuciones y progreso |
| `GET /api/offers/{id}/history` | Últimas 100 observaciones |

Para resultados, `sort` admite `price`, `destination`, `departure`, `return`, `airline`, `stops`, `duration` y `recent`. `direction` acepta `asc` o `desc`. Si se omite, `recent` ordena de más reciente a más antiguo y los demás criterios son ascendentes. `max_duration` se expresa en minutos; `provider` usa el nombre del adaptador, por ejemplo `amadeus` o `mock`. El precio mínimo no puede superar al máximo.

Ejemplo sobre una búsqueda existente, sustituyendo `1` por su identificador:

```bash
curl 'http://localhost:8000/api/searches/1/results?source=real&min_price=100&max_price=900&max_stops=1&sort=price&direction=asc&limit=100&offset=0'
```

## Desarrollo y pruebas

```bash
python3.12 -m venv /tmp/flight-monitor-dev
/tmp/flight-monitor-dev/bin/pip install -r backend/requirements.txt
cd backend
/tmp/flight-monitor-dev/bin/python -m unittest discover -s tests -v
```

Las pruebas no consumen APIs: cubren failover, caché, cuotas, 429, reintentos, timeout, exclusión concurrente, filtros y ordenamiento antes de paginar, valores desconocidos al final, separación demo/test, adaptadores y migración de una base anterior. Los contratos opcionales se prueban al instalar `requirements-experimental.txt` o `requirements-browser.txt`; de lo contrario se omiten esas pruebas concretas.

```bash
cd frontend
npm ci
npm run build
```

Para repetir el flujo de UI con una base temporal y todas las fuentes externas desactivadas:

```bash
# Desde la raíz, con dependencias del frontend ya instaladas:
/tmp/flight-monitor-dev/bin/pip install -r backend/requirements-browser.txt
/tmp/flight-monitor-dev/bin/playwright install chromium
/tmp/flight-monitor-dev/bin/python scripts/check_ui.py
```

El script comprueba creación, estimación, ejecución demo, histórico, caché, filtros de precio/destino/proveedor, ordenamiento por columna, limpieza de filtros y persistencia de la paleta y vista compacta. También verifica que no haya errores de JavaScript ni desbordamiento horizontal de la página en móvil. Inicia servidores en puertos libres, crea y elimina su base temporal, y conserva capturas en una carpeta temporal cuya ruta imprime. No utiliza credenciales ni envía alertas.

También se verificaron migraciones y bloqueo con PostgreSQL desechable, y el flujo de UI en Chromium de escritorio/móvil. Las verificaciones públicas y sus límites están en [SOURCES.md](docs/SOURCES.md). Los resultados de prueba no certifican que una tarifa continúe disponible.

Para consultar el comportamiento anterior, [documentación histórica v2](docs/legacy-v2.md); sus instrucciones no describen esta versión.
