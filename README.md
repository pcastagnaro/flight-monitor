# Flight Monitor — Multi-Provider

MVP Dockerizado para buscar vuelos ocasionalmente en **varios proveedores en paralelo**, guardar histórico y producir `BUY / WATCH / WAIT` con una señal explícita de consenso.

## Fuentes

- **FlightPowers**: live Google Flights, round-trip emparejado.
- **SerpApi / Google Flights**: live discovery + `price_insights`.
- **Travelpayouts Data API**: señal cacheada de mercado; nunca autoriza `BUY` por sí sola.
- **Mock**: fallback automático cuando no hay keys.

## Arquitectura

```text
Next.js
   |
FastAPI
   |
Multi-provider Orchestrator
   |---- FlightPowers ─┐
   |---- SerpApi ──────┼─ concurrente
   |---- Travelpayouts ┘
   |
Dedup + consensus + BUY/WATCH/WAIT
   |
PostgreSQL ---- APScheduler
```

Para cada combinación de fechas y aeropuerto se lanzan **todos los providers habilitados simultáneamente** mediante `asyncio.gather`. Las combinaciones se procesan también en paralelo con un semáforo global de 8 para limitar ráfagas.

## Arranque

```bash
cp .env.example .env
# rellena las keys que tengas
docker compose up --build
```

- Dashboard: http://localhost:3000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/api/health

Si la base está vacía, pulsa **Crear búsqueda BCN–Buenos Aires** y después **Buscar ahora**.

## .env

```env
FLIGHTPOWERS_API_KEY=
SERPAPI_API_KEY=
TRAVELPAYOUTS_API_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Solo contiene credenciales externas.

## Consenso

Los resultados se normalizan y agrupan por una huella compuesta de origen, destino, fechas, aerolíneas normalizadas y escalas. Para cada grupo se calcula:

- mejor precio observado;
- mediana de precios entre fuentes;
- dispersión de precios;
- cantidad de proveedores coincidentes;
- `consensus_score`;
- histórico propio de PostgreSQL;
- `price_level` cuando el proveedor lo expone.

Un `BUY` exige **al menos una fuente live**, score ≥ 82 y confianza ≥ 60. Travelpayouts y Mock están marcados como `live=False`.

## Algoritmo

Peso actual:

- 30% precio vs objetivo
- 25% histórico propio
- 20% nivel de precio externo
- 10% calidad del itinerario
- 15% consenso entre proveedores

Reglas:

- `BUY`: score ≥ 82 + confianza ≥ 60 + al menos una fuente live
- `WATCH`: score ≥ 65
- `WAIT`: resto

Código: `backend/app/services/scoring.py`.

## Scheduler

El uso principal es manual. El worker deja además un barrido diario a las **06:00 Europe/Madrid**. Si quieres funcionamiento estrictamente ocasional/manual, elimina la línea `scheduler.add_job(...)` de `backend/app/worker.py` o no levantes el servicio `worker`.

## Notas sobre consistencia

FlightPowers y SerpApi consultan en última instancia Google Flights, por lo que no constituyen dos mercados verdaderamente independientes. El consenso sirve para detectar diferencias de extracción/caché y robustecer resultados, no como prueba de dos sistemas de inventario independientes. Travelpayouts añade una referencia distinta pero cacheada.

SerpApi devuelve resultados round-trip de discovery, pero para seleccionar explícitamente ciertos retornos/opciones de booking puede requerir llamadas adicionales con `departure_token`. Este MVP evita gastar esas llamadas en todo el universo de fechas; conviene hacer esa segunda etapa solo para los candidatos Top-N antes de una alerta `BUY`.
