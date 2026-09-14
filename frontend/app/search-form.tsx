"use client";
import { FormEvent, useState } from "react";
import { read } from "./api";
const day = (n: number) =>
  new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
export default function SearchForm({
  providers,
  onCreated,
}: {
  providers: any[];
  onCreated: (id: number) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [preview, setPreview] = useState<any>(null);
  const [form, setForm] = useState({
    name: "Mi próximo viaje",
    origin: "BCN",
    destinations: "EZE, AEP",
    departure_from: day(30),
    departure_to: day(33),
    return_from: day(44),
    return_to: day(47),
    adults: 1,
    cabin: "economy",
    currency: "EUR",
    max_stops: "1",
    min_nights: 7,
    max_nights: 21,
    max_price: "",
    target_price: "",
    max_duration_minutes: "",
    airlines: "",
    strategy: "waterfall",
    max_combinations: 12,
    max_provider_calls: 30,
    allow_experimental: false,
    require_complete_trip: false,
    provider_names: [] as string[],
    active: false,
  });
  function set(key: string, value: any) {
    setForm((f) => ({ ...f, [key]: value }));
    setPreview(null);
  }
  function body() {
    return {
      ...form,
      origin: form.origin.toUpperCase().trim(),
      destinations: form.destinations
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      airlines: form.airlines
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      max_stops: form.max_stops === "" ? null : Number(form.max_stops),
      max_price: form.max_price ? Number(form.max_price) : null,
      target_price: form.target_price ? Number(form.target_price) : null,
      max_duration_minutes: form.max_duration_minutes
        ? Number(form.max_duration_minutes)
        : null,
    };
  }
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await read("/searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body()),
      });
      onCreated(data.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function estimate() {
    setBusy(true);
    setError("");
    try {
      setPreview(
        await read("/searches/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body()),
        }),
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const field = (
    key: keyof typeof form,
    label: string,
    type = "text",
    props: any = {},
  ) => (
    <label>
      {label}
      <input
        type={type}
        value={String(form[key])}
        onChange={(e) =>
          set(
            key,
            type === "number" && typeof form[key] === "number"
              ? Number(e.target.value)
              : e.target.value,
          )
        }
        {...props}
      />
    </label>
  );
  return (
    <details className="card new-search">
      <summary>＋ Crear búsqueda avanzada</summary>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <div className="controls">
            <button type="button" className="secondary" onClick={() => {
              setForm(f => ({...f, provider_names: ["flightfinder", "fast_flights"], allow_experimental: true, currency: "USD", strategy: "exhaustive"}));
              setPreview(null);
            }}>Usar Kiwi + Google</button>
            <span className="muted">FlightFinder + flights-skill (fast-flights) · USD · requiere fuentes habilitadas</span>
          </div>
          <div className="form-grid">
            {field("name", "Nombre", "text", {
              required: true,
              maxLength: 120,
            })}
            {field("origin", "Origen · IATA", "text", {
              required: true,
              minLength: 3,
              maxLength: 3,
            })}
            {field("destinations", "Destinos · separados por coma", "text", {
              required: true,
            })}
            {field("departure_from", "Salida desde", "date", {
              required: true,
              min: day(0),
            })}
            {field("departure_to", "Salida hasta", "date", {
              required: true,
              min: form.departure_from,
            })}
            {field("return_from", "Regreso desde", "date", {
              required: true,
              min: form.departure_from,
            })}
            {field("return_to", "Regreso hasta", "date", {
              required: true,
              min: form.return_from,
            })}
            {field("adults", "Adultos", "number", {
              min: 1,
              max: 9,
              required: true,
            })}
            <label>
              Clase
              <select
                value={form.cabin}
                onChange={(e) => set("cabin", e.target.value)}
              >
                <option value="economy">Economy</option>
                <option value="premium_economy">Premium economy</option>
                <option value="business">Business</option>
                <option value="first">First</option>
              </select>
            </label>
            <label>
              Moneda
              <select
                value={form.currency}
                onChange={(e) => set("currency", e.target.value)}
              >
                {["EUR", "USD", "GBP"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label>
              Escalas máximas por trayecto
              <select
                value={form.max_stops}
                onChange={(e) => set("max_stops", e.target.value)}
              >
                <option value="">Cualquiera</option>
                <option value="0">Directo</option>
                <option value="1">1 escala</option>
                <option value="2">2 escalas</option>
                <option value="3">3 escalas</option>
              </select>
            </label>
            {field("min_nights", "Estancia mínima · noches", "number", {
              min: 1,
              max: 365,
              required: true,
            })}
            {field("max_nights", "Estancia máxima · noches", "number", {
              min: form.min_nights,
              max: 365,
              required: true,
            })}
            {field("max_price", "Precio máximo total", "number", {
              min: 1,
              placeholder: "Sin límite",
            })}
            {field("target_price", "Precio objetivo total", "number", {
              min: 1,
              placeholder: "Opcional",
            })}
            {field(
              "max_duration_minutes",
              "Duración máxima por trayecto · min",
              "number",
              { min: 30, max: 5760, placeholder: "Sin límite" },
            )}
            {field("airlines", "Aerolíneas · nombres o códigos", "text", {
              placeholder: "Iberia, BA",
            })}
          </div>
          <details className="advanced-options">
          <summary>Opciones avanzadas · cobertura y fuentes</summary>
          <div className="form-grid">
            <label>
              Estrategia
              <select
                value={form.strategy}
                onChange={(e) => set("strategy", e.target.value)}
              >
                <option value="waterfall">
                  Escalonada · detener al encontrar ofertas
                </option>
                <option value="exhaustive">
                  Exhaustiva · consultar todas las fuentes
                </option>
              </select>
            </label>
            {field("max_combinations", "Máximo de combinaciones", "number", {
              min: 1,
              max: 120,
              required: true,
            })}
            {field(
              "max_provider_calls",
              "Máximo de llamadas a adaptadores",
              "number",
              { min: 1, max: 300, required: true },
            )}
          </div>
          <p className="muted">
            La caché se consulta primero. Las referencias de precios no detienen
            la búsqueda. Los límites incluyen reintentos; un adaptador puede
            hacer varias peticiones HTTP.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={form.allow_experimental}
              onChange={(e) => set("allow_experimental", e.target.checked)}
            />
            Permitir fuentes experimentales sin clave, si están habilitadas en
            el servidor
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.require_complete_trip}
              onChange={(e) => set("require_complete_trip", e.target.checked)}
            />
            Exigir ida y vuelta detalladas · excluye precios con regreso sin
            verificar
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(e) => set("active", e.target.checked)}
            />
            Incluir en seguimiento diario cuando el worker esté activo
          </label>
          <details>
            <summary>
              Elegir proveedores · vacío utiliza todos los compatibles
            </summary>
            <div className="controls">
              {providers.map((p) => (
                <label className="check" key={p.name}>
                  <input
                    type="checkbox"
                    checked={form.provider_names.includes(p.name)}
                    onChange={(e) =>
                      set(
                        "provider_names",
                        e.target.checked
                          ? [...form.provider_names, p.name]
                          : form.provider_names.filter((n) => n !== p.name),
                      )
                    }
                  />
                  {p.name}
                  {!p.enabled ? " (sin configurar)" : ""}
                </label>
              ))}
            </div>
          </details>
          </details>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {preview && (
            <p className="notice">
              {preview.planned_combinations} de {preview.total_combinations}{" "}
              combinaciones planificadas · {preview.omitted_combinations}{" "}
              omitidas · hasta {preview.max_provider_calls} llamadas. No se ha
              consultado ninguna API externa.
            </p>
          )}
          <div className="controls actions">
            <button type="button" className="secondary" onClick={estimate}>
              Estimar cobertura
            </button>
            <button type="submit">
              {busy ? "Procesando…" : "Guardar búsqueda"}
            </button>
          </div>
        </fieldset>
      </form>
    </details>
  );
}
