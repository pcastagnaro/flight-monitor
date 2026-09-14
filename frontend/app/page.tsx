"use client";
import { useEffect, useState } from "react";
import { read } from "./api";
import SearchForm from "./search-form";
const defaultFilters = {
  min_price: "",
  max_price: "",
  max_stops: "",
  max_duration: "",
  provider: "",
  airline: "",
  destination: "",
  sort: "price",
  direction: "asc",
  fresh_only: false,
};
const sortOptions = [
  ["price", "Precio"],
  ["destination", "Destino"],
  ["departure", "Salida"],
  ["return", "Regreso"],
  ["duration", "Duración"],
  ["stops", "Escalas"],
  ["airline", "Aerolíneas"],
  ["recent", "Consultado"],
];
const stamp = (s: string) => new Date(s).toLocaleString("es-ES");
const statuses: Record<string, string> = {
  ok: "Completada",
  partial: "Cobertura parcial",
  empty: "Sin resultados",
  failed: "Fallida",
  running: "En curso",
};
const events: Record<string, string> = {
  ok: "Ofertas recibidas",
  empty: "Sin datos",
  error: "Error",
  cache_hit: "Caché",
  filtered: "No cumplen filtros",
  unsupported: "Consulta no soportada",
  budget_exhausted: "Límite alcanzado",
  circuit_open: "Pausa por fallos",
  deadline: "Tiempo agotado",
};
function HistoryIndicator({ offer }: { offer: any }) {
  const h = offer.history_indicator;
  const levels: Record<string, string> = { low: "Buen precio", typical: "Precio habitual", high: "Precio alto", insufficient: "Histórico insuficiente" };
  const trends: Record<string, string> = { up: "↑ En alza", down: "↓ En baja", stable: "→ Estable" };
  return <div className="history-indicator">
    <span className={`status-badge ${h?.level === "low" ? "good" : h?.level === "high" ? "warning" : "neutral"}`}>
      {levels[h?.level] || levels.insufficient}
    </span>
    {h?.median_price != null ? <small className="muted">
      {h.vs_median_percent > 0 ? "+" : ""}{h.vs_median_percent.toLocaleString("es-ES")}% frente a la mediana ({h.median_price.toLocaleString("es-ES")} {offer.currency}) · {h.days} días
    </small> : <small className="muted">Se necesitan 3 días previos · {h?.days ?? 0} disponibles</small>}
    {h && h.trend !== "insufficient" ? <small>
      {trends[h.trend]} · {h.change_percent > 0 ? "+" : ""}{h.change_percent.toLocaleString("es-ES")}% desde {h.previous_date}
    </small> : <small className="muted">Sin tendencia todavía</small>}
  </div>;
}
export default function Home() {
  const [searches, setSearches] = useState<any[]>([]),
    [selected, setSelected] = useState<number | null>(null),
    [results, setResults] = useState<any[]>([]),
    [runs, setRuns] = useState<any[]>([]),
    [providers, setProviders] = useState<any[]>([]);
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [source, setSource] = useState("real"),
    [refresh, setRefresh] = useState(0),
    [page, setPage] = useState(0);
  const [filters, setFilters] = useState(defaultFilters);
  const [palette, setPalette] = useState("indigo");
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("flight-appearance");
      if (saved) {
        const value = JSON.parse(saved);
        if (["indigo", "ocean", "plum"].includes(value.palette))
          setPalette(value.palette);
        setCompact(value.compact === true);
      }
    } catch {}
  }, []);
  function appearance(nextPalette: string, nextCompact: boolean) {
    setPalette(nextPalette);
    setCompact(nextCompact);
    try {
      localStorage.setItem(
        "flight-appearance",
        JSON.stringify({ palette: nextPalette, compact: nextCompact }),
      );
    } catch {}
  }
  const activeFilters = Object.entries(filters).filter(
    ([k, v]) => !["sort", "direction"].includes(k) && v !== "" && v !== false,
  );
  function sortColumn(key: string) {
    setFilters((f) => ({
      ...f,
      sort: key,
      direction: f.sort === key && f.direction === "asc" ? "desc" : "asc",
    }));
    setPage(0);
  }
  function heading(key: string, label: string) {
    return (
      <th
        aria-sort={
          filters.sort === key
            ? filters.direction === "asc"
              ? "ascending"
              : "descending"
            : "none"
        }
      >
        <button className="sort-button" onClick={() => sortColumn(key)}>
          {label}{" "}
          <span aria-hidden="true">
            {filters.sort === key
              ? filters.direction === "asc"
                ? "↑"
                : "↓"
              : "↕"}
          </span>
        </button>
      </th>
    );
  }
  const [history, setHistory] = useState<any[] | null>(null),
    [historyTitle, setHistoryTitle] = useState("");
  const current = searches.find((s) => s.id === selected),
    latest = runs[0];
  async function loadSearches(id?: number) {
    const s = await read("/searches");
    setSearches(s);
    if (id) setSelected(id);
    else setSelected((prev) => prev ?? s[0]?.id ?? null);
  }
  useEffect(() => {
    Promise.all([loadSearches(), read("/providers").then(setProviders)]).catch(
      (e) => setError(e.message),
    );
  }, []);
  useEffect(() => {
    let active = true;
    if (!selected) return;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      source,
      offset: String(page * 100),
      limit: "100",
      sort: filters.sort,
    });
    Object.entries(filters).forEach(([k, v]) => {
      if (v !== "" && v !== false) params.set(k, String(v));
    });
    Promise.all([
      read(`/searches/${selected}/results?${params}`),
      read(`/searches/${selected}/runs`),
      read("/providers"),
    ])
      .then(([r, h, p]) => {
        if (active) {
          setResults(r);
          setRuns(h);
          setProviders(p);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selected, source, filters, page, refresh]);
  useEffect(() => {
    if (!busy || !selected) return;
    let active = true;
    const timer = setInterval(
      () =>
        read(`/searches/${selected}/runs`)
          .then((h) => {
            if (active) setRuns(h);
          })
          .catch(() => {}),
      2500,
    );
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [busy, selected]);
  function filter(k: string, v: any) {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(0);
  }
  async function run() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await read(`/searches/${selected}/run`, { method: "POST" });
      setPage(0);
      setRefresh((x) => x + 1);
    } catch (e: any) {
      setError(e.message);
      setRefresh((x) => x + 1);
    } finally {
      setBusy(false);
    }
  }
  async function showHistory(r: any) {
    setHistory(null);
    setHistoryTitle(`${r.origin} → ${r.destination} · ${r.departure_date}`);
    try {
      setHistory(await read(`/offers/${r.id}/history`));
    } catch (e: any) {
      setError(e.message);
      setHistoryTitle("");
    }
  }
  async function toggle() {
    if (!current) return;
    try {
      await read(`/searches/${selected}/active?active=${!current.active}`, {
        method: "PATCH",
      });
      await loadSearches();
    } catch (e: any) {
      setError(e.message);
    }
  }
  const best =
    !loading &&
    filters.sort === "price" &&
    filters.direction === "asc" &&
    page === 0
      ? results[0]
      : null;
  return (
    <main data-palette={palette} className={compact ? "density-compact" : ""}>
      <header>
        <div>
          <div className="eyebrow">EXPLORA · COMPARA · SIGUE</div>
          <h1>
            Flight Monitor <span>↗</span>
          </h1>
          <p className="muted">
            Encuentra tu viaje, con visibilidad de cada fuente.
          </p>
        </div>
        <div className="appearance">
          <label>
            Paleta de colores
            <select
              aria-label="Paleta de colores"
              value={palette}
              onChange={(e) => appearance(e.target.value, compact)}
            >
              <option value="indigo">Índigo</option>
              <option value="ocean">Océano</option>
              <option value="plum">Ciruela</option>
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={compact}
              onChange={(e) => appearance(palette, e.target.checked)}
            />
            Vista compacta
          </label>
        </div>
      </header>
      <SearchForm
        providers={providers}
        onCreated={(id) => {
          loadSearches(id).catch((e) => setError(e.message));
          setPage(0);
        }}
      />
      <section className="card hero">
        <div className="controls">
          <label className="grow">
            Búsquedas guardadas
            <select
              disabled={busy}
              value={selected ?? ""}
              onChange={(e) => {
                setSelected(Number(e.target.value) || null);
                setPage(0);
                setResults([]);
                setRuns([]);
              }}
            >
              <option value="">Selecciona una búsqueda</option>
              {searches.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button onClick={run} disabled={busy || loading || !selected}>
            {busy ? "Buscando…" : "Buscar ahora →"}
          </button>
          {current && (
            <button className="secondary" disabled={busy} onClick={toggle}>
              {current.active ? "Pausar seguimiento" : "Activar seguimiento"}
            </button>
          )}
        </div>
        {current && (
          <p className="muted">
            {current.origin} → {current.destinations.join(" / ")} ·{" "}
            {current.adults} adulto(s) · {current.cabin} · {current.currency} ·{" "}
            {current.strategy === "waterfall" ? "Escalonada" : "Exhaustiva"} ·{" "}
            {current.active
              ? "Seguimiento diario habilitado"
              : "Solo búsquedas manuales"}
          </p>
        )}
        {busy && (
          <p role="status">
            Consultando fuentes…{" "}
            {latest?.status === "running" &&
              `${latest.details?.progress ?? 0} / ${latest.details?.planned ?? "…"} combinaciones`}
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </section>
      <details
        className="card diagnostics"
        open={!providers.some((p) => p.enabled)}
      >
        <summary>
          Fuentes y disponibilidad{" "}
          <span className="muted">
            {providers.filter((p) => p.enabled).length} habilitadas /{" "}
            {providers.length}
          </span>
        </summary>
        <div className="provider-grid">
          {providers.map((p) => (
            <article key={p.name} className="provider">
              <strong>{p.name}</strong>
              <span
                className={`dot ${p.enabled && !p.blocked_until ? "on" : ""}`}
              />
              <p>
                {p.blocked_until
                  ? `Pausado hasta ${stamp(p.blocked_until)}`
                  : p.enabled
                    ? "Habilitado"
                    : "Sin configurar / desactivado"}
              </p>
              <p className="muted">
                {p.family} {p.experimental ? "· Experimental" : ""}
                <br />
                {p.notes}
              </p>
              <small>
                {p.monthly_calls} / {p.monthly_limit} llamadas este mes
              </small>
            </article>
          ))}
        </div>
        <p className="muted">
          Habilitado indica configuración, no credenciales validadas. Distintos
          extractores de Google Flights comparten la misma fuente.
        </p>
      </details>
      {!providers.some((p) => p.enabled) && (
        <p className="notice">
          Sin proveedores externos habilitados, las búsquedas generan datos
          simulados en Demostración.
        </p>
      )}
      {latest && (
        <section className="card run-summary">
          <div className="controls">
            <strong>{statuses[latest.status] || latest.status}</strong>
            <span className="muted">{stamp(latest.started_at)}</span>
            <span>{latest.result_count} resultados</span>
          </div>
          <p className="muted">
            {latest.details?.completed_combinations ??
              latest.details?.combinations ??
              0}{" "}
            combinaciones consultadas de{" "}
            {latest.details?.total_combinations ??
              latest.details?.combinations ??
              0}{" "}
            · {latest.details?.provider_calls ?? "—"} llamadas a adaptadores
          </p>
          {latest.details?.omitted_combinations > 0 && (
            <p className="notice">
              {latest.details.omitted_combinations} combinaciones sin explorar.
              Amplía los límites o reduce los rangos para cubrirlas.
            </p>
          )}
          {latest.status !== "running" && latest.result_count === 0 && (
            <p className="notice">
              Esta ejecución no obtuvo ofertas. Las ofertas guardadas pueden
              pertenecer a búsquedas anteriores.
            </p>
          )}
          {latest.details?.error && (
            <p className="error">
              Ejecución interrumpida: {latest.details.error}
            </p>
          )}
          {Object.entries(latest.details?.providers || {})
            .filter(([, p]: [string, any]) => p.enabled && p.selected === false)
            .map(([name, p]: [string, any]) => (
              <p className="muted" key={name}>
                {name}:{" "}
                {p.reason === "experimental_disabled"
                  ? "no se permitieron fuentes experimentales en esta búsqueda"
                  : "excluido de la selección de fuentes"}
                .
              </p>
            ))}
          <details>
            <summary>Ver recorrido de la búsqueda</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Fuente</th>
                    <th>Destino / fechas</th>
                    <th>Resultado</th>
                    <th>Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {(latest.details?.trace || []).map((e: any, i: number) => (
                    <tr key={i}>
                      <td>{e.provider}</td>
                      <td>
                        {e.destination} · {e.departure} / {e.return_date}
                      </td>
                      <td>{events[e.status] || e.status}</td>
                      <td>
                        {e.error || e.results || "—"}
                        {e.until ? ` · hasta ${stamp(e.until)}` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
      <div className="controls tabs">
        <button
          aria-pressed={source === "real"}
          onClick={() => {
            setSource("real");
            setPage(0);
          }}
        >
          Datos reales
        </button>
        <button
          aria-pressed={source === "demo"}
          onClick={() => {
            setSource("demo");
            setPage(0);
          }}
        >
          Demostración
        </button>
      </div>
      <p className={source === "demo" ? "notice" : "muted"}>
        {source === "demo"
          ? "DEMO · Datos simulados o entorno de prueba de Amadeus. No representan disponibilidad real."
          : "Precios totales para los pasajeros indicados. Las tarifas orientativas y los regresos sin verificar requieren confirmación con el proveedor."}
      </p>
      <section className="card filters">
        <div className="filter-title">
          <div>
            <h2>Filtrar ofertas guardadas</h2>
            <p className="muted">
              Se aplican a todas las ofertas guardadas, antes de paginar.
            </p>
          </div>
          <button
            className="secondary"
            disabled={!activeFilters.length}
            onClick={() => {
              setFilters({
                ...defaultFilters,
                sort: filters.sort,
                direction: filters.direction,
              });
              setPage(0);
            }}
          >
            Limpiar filtros
            {activeFilters.length ? ` (${activeFilters.length})` : ""}
          </button>
        </div>
        <div className="form-grid">
          <label>
            Precio mínimo
            <input
              type="number"
              min="0"
              placeholder="Sin mínimo"
              value={filters.min_price}
              onChange={(e) => filter("min_price", e.target.value)}
            />
          </label>
          <label>
            Precio máximo
            <input
              type="number"
              min="1"
              placeholder="Sin límite"
              value={filters.max_price}
              onChange={(e) => filter("max_price", e.target.value)}
            />
          </label>
          <label>
            Escalas
            <select
              aria-label="Escalas"
              value={filters.max_stops}
              onChange={(e) => filter("max_stops", e.target.value)}
            >
              <option value="">Todas</option>
              <option value="0">Directo</option>
              <option value="1">Hasta 1</option>
              <option value="2">Hasta 2</option>
            </select>
          </label>
          <label>
            Aerolínea
            <input
              placeholder="Nombre o código"
              value={filters.airline}
              onChange={(e) => filter("airline", e.target.value)}
            />
          </label>
          <label>
            Destino
            <select
              aria-label="Destino"
              value={filters.destination}
              onChange={(e) => filter("destination", e.target.value)}
            >
              <option value="">Todos</option>
              {current?.destinations.map((d: string) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </label>
          <label>
            Ordenar
            <select
              aria-label="Ordenar"
              value={filters.sort}
              onChange={(e) => filter("sort", e.target.value)}
            >
              {sortOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="form-grid extra-filters">
          <label>
            Sentido
            <select
              aria-label="Sentido"
              value={filters.direction}
              onChange={(e) => filter("direction", e.target.value)}
            >
              <option value="asc">Ascendente ↑</option>
              <option value="desc">Descendente ↓</option>
            </select>
          </label>
          <label>
            Duración máxima (min)
            <input
              type="number"
              min="1"
              placeholder="Sin límite"
              value={filters.max_duration}
              onChange={(e) => filter("max_duration", e.target.value)}
            />
          </label>
          <label>
            Proveedor
            <select
              aria-label="Proveedor"
              value={filters.provider}
              onChange={(e) => filter("provider", e.target.value)}
            >
              <option value="">Todos</option>
              {[...providers.map((p) => p.name), "mock"].map((name) => (
                <option key={name} value={name}>
                  {name === "mock" ? "Simulado" : name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.fresh_only}
            onChange={(e) => filter("fresh_only", e.target.checked)}
          />
          Solo observaciones de las últimas 6 horas
        </label>
      </section>
      {best && (
        <section className="best">
          <div>
            <div className="eyebrow">
              MENOR PRECIO DE LOS RESULTADOS FILTRADOS
            </div>
            <strong className="price">
              {best.price.toLocaleString("es-ES")}{" "}
              <small>{best.currency}</small>
            </strong>
          </div>
          <div>
            {best.origin} → {best.destination}
            <p className="muted">
              {best.departure_date} / {best.return_date}
            </p>
          </div>
          <HistoryIndicator offer={best} />
          <span className="pill">
            {best.stale ? "Consulta antigua" : "Observación reciente"}
          </span>
        </section>
      )}
      <section aria-busy={loading} className="card results">
        <p className="muted table-help">
          Pulsa una columna para ordenar; vuelve a pulsar para invertir el
          orden. Los valores sin verificar aparecen al final. El histórico compara mínimos diarios de la misma oferta y moneda: buen precio si baja al menos un 10% frente a la mediana; alto si sube un 10%. La tendencia compara con el último día registrado (estable si varía menos del 2%).
        </p>
        <h2 aria-live="polite">
          {loading
            ? "Cargando ofertas…"
            : `${results.length} ofertas · página ${page + 1}`}
        </h2>
        {!loading && !results.length ? (
          <p className="muted">
            No hay ofertas para esta selección. Revisa los filtros y el
            diagnóstico de la última búsqueda.
          </p>
        ) : (
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label="Ofertas ordenables"
          >
            <table className="offers-table">
              <thead>
                <tr>
                  {heading("destination", "Viaje")}
                  {heading("departure", "Salida")}
                  {heading("return", "Regreso")}
                  {heading("price", "Precio")}
                  {heading("airline", "Aerolíneas")}
                  {heading("stops", "Escalas")}
                  {heading("duration", "Duración")}
                  <th>Fuente</th>
                  {heading("recent", "Consultado")}
                  <th>Histórico · 30 días</th>
                  <th>Detalles</th>
                </tr>
              </thead>
              <tbody>
                {!loading &&
                  results.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.origin} → {r.destination}
                      </td>
                      <td>{r.departure_date}</td>
                      <td>{r.return_date}</td>
                      <td className="fare">
                        {r.price.toLocaleString("es-ES", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}{" "}
                        {r.currency}
                        {current?.target_price &&
                        r.price <= current.target_price &&
                        r.currency === current.currency ? (
                          <div className="status-badge good">
                            Dentro del objetivo
                          </div>
                        ) : null}
                      </td>
                      <td>{r.airlines.join(", ") || "Desconocida"}</td>
                      <td>
                        <span
                          className={`status-badge ${r.stops === 0 ? "good" : "neutral"}`}
                        >
                          {r.stops === 0
                            ? "Directo"
                            : r.stops == null
                              ? "Sin verificar"
                              : `${r.stops} escala(s)`}
                        </span>
                      </td>
                      <td>
                        {r.duration_minutes == null
                          ? "Sin verificar"
                          : `${Math.floor(r.duration_minutes / 60)} h ${r.duration_minutes % 60} min`}
                      </td>
                      <td>
                        {r.provider_names?.join(", ")}
                        <br />
                        <small className="muted">
                          {source === "demo"
                            ? r.environment === "test"
                              ? "Prueba Amadeus"
                              : "Simulado"
                            : r.quality === "separate_tickets"
                              ? "Billetes separados"
                              : r.quality === "reference"
                                ? "Referencia cacheada"
                                : r.complete_trip
                                  ? "Ida y vuelta detalladas"
                                  : "Regreso sin verificar"}
                        </small>
                      </td>
                      <td>
                        {stamp(r.last_seen_at)}
                        <div
                          className={`status-badge ${r.stale ? "warning" : "good"}`}
                        >
                          {r.stale ? "Más de 6 horas" : "Reciente"}
                        </div>
                      </td>
                      <td><HistoryIndicator offer={r} /></td>
                      <td>
                        <button
                          className="secondary compact"
                          onClick={() => showHistory(r)}
                        >
                          Histórico
                        </button>
                        {r.booking_url && (
                          <a
                            className="booking"
                            href={r.booking_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Ver proveedor ↗
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="controls actions">
          <button
            className="secondary"
            disabled={page === 0 || loading}
            onClick={() => setPage((p) => p - 1)}
          >
            Anterior
          </button>
          <button
            className="secondary"
            disabled={results.length < 100 || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Siguiente
          </button>
        </div>
      </section>
      {historyTitle && (
        <section
          className="card history"
          role="region"
          aria-label="Histórico de precios"
        >
          <div className="controls">
            <h2>{historyTitle}</h2>
            <button className="secondary" onClick={() => setHistoryTitle("")}>
              Cerrar
            </button>
          </div>
          {history === null ? (
            <p>Cargando histórico…</p>
          ) : (
            <>
              <p className="muted">
                Observaciones del proveedor; reutilizar la caché no crea nuevos
                puntos.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Fuente</th>
                      <th>Precio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h, i) => (
                      <tr key={i}>
                        <td>{stamp(h.checked_at)}</td>
                        <td>{h.provider}</td>
                        <td>
                          {h.price} {h.currency}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}
      <footer>
        Flight Monitor · La cobertura depende de las fuentes habilitadas y de
        los límites de búsqueda.
      </footer>
    </main>
  );
}
