# Revisión de fuentes e integración

Revisión iniciada el 12 y verificada el 14 de septiembre de 2026. Se inspeccionaron README, interfaces relevantes y código público. La integración conserva la arquitectura del proyecto; no instala agentes completos ni ejecuta sus instrucciones como parte de una búsqueda.

| Fuente | Hallazgo | Decisión aplicada |
| --- | --- | --- |
| [wolfiesch/flightfinder](https://github.com/wolfiesch/flightfinder) | Cliente Python asíncrono sobre Kiwi/Skypicker GraphQL, viajes de ida/vuelta, caché y reintentos. La revisión fija USD en el parser. La instalación anunciada desde PyPI no estaba disponible en la comprobación. | Adaptador opcional sobre un commit fijo de GitHub; solo USD. El transporte se controla desde nuestro motor para conservar estados HTTP, cuotas y reintentos. Se desactivan cambios de aeropuertos, hidden-city y self-transfer en esa consulta. |
| [fast-gateway-protocol/travel](https://github.com/fast-gateway-protocol/travel) | Daemon Rust, socket Unix, Kiwi/Skypicker y Xotelo; utilidades para rangos de fechas, lotes y caché. | Se aprovecha el enfoque de consultas acotadas y muestreo de fechas. No se añade otro daemon que duplicaría la fuente Kiwi ni las funciones de hoteles fuera de alcance. |
| [Anmoldureha/flights-skill](https://github.com/Anmoldureha/flights-skill) | Wrapper de fast-flights; su ejemplo usa una API anterior basada en `FlightData`. | Se integra directamente fast-flights 3.1.0 con `FlightQuery`, moneda explícita y HTTP cancelable. No se copia el wrapper antiguo. |
| [affromero/flight-finder](https://github.com/affromero/flight-finder) | Aplicación completa con cadena de fuentes, histórico y extracción de navegador/LLM. | Cadena ordenada, histórico, diagnóstico y navegador opcional. Se usa extracción determinista; no se incorporan su plataforma, VPN ni dependencias de modelos. |
| [kiinami/vfd](https://github.com/kiinami/vfd) | Usa fast-flights, Streamlit y notificaciones; reconoce limitaciones de moneda y eficiencia. | Rutas y fechas acotadas, control de frecuencia mediante caché y persistencia histórica. Una sola integración fast-flights representa esta fuente compartida. |
| [jackculpan/flightclaw](https://github.com/jackculpan/flightclaw) | MCP/skill, filtros, calendarios e histórico; usa `fli`/`flights`, distinto paquete de fast-flights. También ofrece servicios opcionales de perfiles/reservas. | Sus filtros y separación de funciones informan la UI. No se instala MCP ni se conectan perfiles, pagos o reservas; no se afirma integrar su motor `fli`. |
| [qwerty-loops/flight_price_tracker](https://github.com/qwerty-loops/flight_price_tracker) | Tracker sobre SerpApi/Google Flights. | Se conserva y endurece el adaptador SerpApi existente; no se duplica como una fuente independiente. |
| [restocktime/flight-deal-scraper](https://github.com/restocktime/flight-deal-scraper) | Consulta `/v2/search` de Kiwi Tequila para rutas, fechas, precios y enlaces. | Nuevo adaptador Kiwi con credencial, cabina/pasajeros explícitos y verificación de ambos trayectos. La disponibilidad de acceso gratuito anunciada en su README no se da por garantizada. |
| [2BAD/ryanair](https://github.com/2BAD/ryanair) | API pública de calendarios y API de reserva distinta. Sus round trips de calendario son sumas de tarifas individuales. | Adaptador HTTP propio sobre calendarios `farfnd/v4`; reutilización mensual por ejecución, moneda verificada y estado «billetes separados». Solo 1 adulto/economy; no simula una cotización conjunta. |
| [arghya-v/flyte](https://github.com/arghya-v/flyte) | Interfaz de búsqueda sobre Amadeus con opciones de presentación y exploración. | Nuevo adaptador Amadeus, estado de fuentes, filtros y diseño responsive. OAuth se mantiene en backend; el entorno test se separa de producción. |
| Spotter-Flight-Engine | No se identificó inequívocamente; el usuario no dispone del enlace. Existen varios proyectos de evaluación con nombres similares. | No se atribuye código ni se incorpora una dependencia de un repositorio distinto. Amadeus se integra sin depender de esa referencia. |

## Dependencias y propiedad del código

- Los adaptadores HTTP y el motor fueron implementados en este proyecto. No se incorporaron archivos de aplicación completos de los repositorios revisados.
- Dependencias opcionales: `fast-flights==3.1.0` y FlightFinder en commit [`1b912ed0decc93473e5e0914a03e16b1f09b0681`](https://github.com/wolfiesch/flightfinder/tree/1b912ed0decc93473e5e0914a03e16b1f09b0681). Ambos repositorios publican licencia MIT; sus distribuciones conservan sus avisos.
- Chromium utiliza `playwright==1.62.0` y se instala solo con `INSTALL_BROWSER=true`. [Documentación de instalación de navegadores](https://playwright.dev/python/docs/browsers).
- El contrato de consultas de Google se comprobó contra el [repositorio de fast-flights](https://github.com/AWeirdDev/flights), no contra ejemplos de la API antigua.
- El catálogo de [Amadeus](https://developers.amadeus.com/) describe sus APIs; las credenciales y el acceso a producción deben obtenerse del proveedor.

## Independencia y calidad

FlightPowers, SerpApi, DataCrawler, fast-flights y Chromium comparten Google Flights. Kiwi Tequila y FlightFinder comparten el ecosistema Kiwi. Tener varios extractores mejora recuperación, pero no prueba independencia de mercado.

Los resultados se conservan por proveedor e identidad de itinerario. Se utilizan segmentos cuando existen; cuando solo existe un identificador opaco, su estabilidad depende del proveedor. No se asegura continuidad histórica entre identificadores que cambien. Los registros de test y producción no comparten identidad.

Amadeus, Kiwi Tequila y FlightFinder comprueban los aeropuertos y las fechas de ambos trayectos antes de marcar «ida y vuelta detalladas». Esta marca no confirma disponibilidad final ni incluye una llamada de revalidación de precio. El resto de fuentes se presenta con limitaciones explícitas. Si el usuario exige ambos trayectos detallados, se descartan los descubrimientos incompletos y continúa el failover.

## Verificación pública acotada

Se consultó DUB–STN, salida a 45 días y regreso a 50 días, sin claves y sin reservas:

- Ryanair devolvió una combinación de dos tarifas de calendario.
- FlightFinder/Kiwi público devolvió 30 itinerarios en USD.
- Chromium inició una sesión anónima, pero Google abortó la navegación en esta prueba. Este último recurso queda **experimental y no validado de extremo a extremo** desde este entorno.
- fast-flights por HTTP se detuvo ante una redirección de consentimiento de Google. El error se conserva como diagnóstico y permite pasar al último recurso.

Estas observaciones describen esa ejecución desde este entorno. No garantizan cobertura universal, ausencia de bloqueos ni acceso permanente. Las APIs con credenciales se probaron mediante transporte simulado para no gastar las cuotas del usuario.

## Límites que permanecen

No hay autenticación multiusuario, compra automática, confirmación de equipaje, divisas convertidas, búsqueda multi-city ni garantía de mínimo global. No se ejecutan LLM sobre páginas para inferir tarifas. Chromium puede resolver diferencias de carga/renderizado, pero comparte parser con fast-flights: no constituye recuperación independiente ante cualquier cambio del formato de Google. Las páginas de desafío se tratan como fallo; no se resuelven CAPTCHA.

La cola de alertas no es durable: los fallos de Telegram quedan registrados, sin reenvío garantizado. Los presupuestos persistidos son de llamadas a adaptadores, no de facturación real del proveedor. La exclusión global prioriza evitar consumo duplicado en una aplicación personal; no es una arquitectura de búsquedas multiusuario concurrentes.
