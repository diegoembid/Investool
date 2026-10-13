"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type Health,
  type Me,
  type ProviderUsage,
  type SmokeResult,
  type Usage,
} from "@/lib/api";
import styles from "./dashboard.module.css";

const PROVIDER_NAMES: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI" };

const STATUS_LABELS: Record<string, string> = {
  succeeded: "Correcta",
  cached: "Desde caché",
  blocked: "Bloqueada",
  failed: "Error",
  reserved: "En curso",
  abandoned: "Sin cerrar",
};

// Orden y forma en singular/plural para el resumen de llamadas.
const STATUS_COUNTS: [string, string, string][] = [
  ["succeeded", "correcta", "correctas"],
  ["cached", "desde caché", "desde caché"],
  ["blocked", "bloqueada", "bloqueadas"],
  ["failed", "con error", "con error"],
  ["reserved", "en curso", "en curso"],
  ["abandoned", "sin cerrar", "sin cerrar"],
];

const int = (n: number) => new Intl.NumberFormat("es-ES").format(n);

const usd = (v: string | number, digits = 4) =>
  new Intl.NumberFormat("es-ES", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(v));

const eur = (v: number) =>
  new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(v);

const when = (iso: string) =>
  new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "medium" }).format(
    new Date(iso),
  );

function Meter({ spent, cap, large = false }: { spent: number; cap: number; large?: boolean }) {
  const ratio = cap > 0 ? Math.min(spent / cap, 1) : 1;
  const level = ratio >= 1 ? "full" : ratio >= 0.8 ? "high" : "ok";
  return (
    <div
      className={`${styles.meter} ${large ? styles.meterLarge : ""}`}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={cap}
      aria-valuenow={spent}
      aria-label={`Gastado ${usd(spent)} de ${usd(cap, 2)} USD`}
    >
      <div className={`${styles.fill} ${styles[level]}`} style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}

function callSummary(counts: Record<string, number>): string {
  const parts = STATUS_COUNTS.filter(([status]) => counts[status]).map(
    ([status, one, many]) => `${counts[status]} ${counts[status] === 1 ? one : many}`,
  );
  return parts.length ? `Llamadas este mes: ${parts.join(", ")}.` : "Sin llamadas este mes.";
}

function ProviderRow({
  p,
  fx,
  onTested,
}: {
  p: ProviderUsage;
  fx: number;
  onTested: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SmokeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const spent = Number(p.month_spent_usd);
  const cap = Number(p.month_cap_usd);

  async function test() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.smokeTest(p.provider));
      onTested();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se ha podido hacer la prueba.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={styles.provider}>
      <div className={styles.providerHead}>
        <h3>{PROVIDER_NAMES[p.provider] ?? p.provider}</h3>
        <span className={p.configured ? "muted" : "error"}>
          {p.configured ? "Clave configurada" : "Falta la clave en el fichero .env"}
        </span>
      </div>
      <Meter spent={spent} cap={cap} />
      <p className={styles.figures}>
        {usd(spent)} de {usd(cap, 2)} USD
        <span className="muted"> (unos {eur(spent * fx)})</span>
      </p>
      <p className="muted">{callSummary(p.calls_by_status)}</p>
      <div className={styles.testRow}>
        <button className="secondary" onClick={test} disabled={busy || !p.configured}>
          {busy ? "Probando…" : "Probar conexión"}
        </button>
        <span aria-live="polite">
          {result && (
            <span className={result.ok ? styles.okText : "error"}>
              {result.ok
                ? `Funciona con ${result.model}. ${result.detail}. Coste: ${usd(result.cost_usd, 6)} USD.`
                : result.detail}
            </span>
          )}
          {error && <span className="error">{error}</span>}
        </span>
      </div>
    </li>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [u, h] = await Promise.all([api.usage(), api.health()]);
      setUsage(u);
      setHealth(h);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError("No se ha podido cargar el panel. Comprueba que el backend está en marcha.");
    }
  }, [router]);

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        return load();
      })
      .catch(() => router.replace("/login"));
  }, [load, router]);

  async function logout() {
    await api.logout().catch(() => undefined);
    router.replace("/login");
  }

  if (!me) return null;

  const fx = usage ? Number(usage.usd_to_eur) : 0;
  const monthSpent = usage ? Number(usage.month_spent_usd) : 0;
  const monthCap = usage ? Number(usage.monthly_cap_usd) : 0;
  const monthName = usage
    ? new Intl.DateTimeFormat("es-ES", { month: "long", timeZone: "UTC" }).format(
        new Date(usage.as_of),
      )
    : "";

  return (
    <>
      <header className={styles.bar}>
        <span className={styles.brand}>Investool</span>
        <span className={styles.user}>
          <span>{me.email}</span>
          <button onClick={logout} className={styles.logout}>
            Cerrar sesión
          </button>
        </span>
      </header>

      <main className={styles.main}>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {usage && !usage.ai_enabled && (
          <p className={styles.notice} role="status">
            La IA está desactivada (AI_ENABLED=false en el fichero .env). No se hará ninguna
            llamada a los proveedores.
          </p>
        )}

        {usage && (
          <section className={styles.spend} aria-labelledby="spend-title">
            <h1 id="spend-title">Gasto de IA en {monthName}</h1>
            <p className={styles.total}>
              {usd(monthSpent)} <span className={styles.unit}>de {usd(monthCap, 2)} USD</span>
            </p>
            <Meter spent={monthSpent} cap={monthCap} large />
            <p className="muted">
              Unos {eur(monthSpent * fx)}. Hoy: {usd(usage.today_spent_usd)} de{" "}
              {usd(usage.daily_cap_usd, 2)} USD. Al llegar a un tope, las llamadas se bloquean
              hasta el día o el mes siguiente (hora UTC).
            </p>
          </section>
        )}

        {usage && (
          <section aria-labelledby="providers-title">
            <h2 id="providers-title" className={styles.h2}>
              Proveedores
            </h2>
            <ul className={styles.providers}>
              {usage.providers.map((p) => (
                <ProviderRow key={p.provider} p={p} fx={fx} onTested={load} />
              ))}
            </ul>
          </section>
        )}

        {usage && (
          <section aria-labelledby="calls-title">
            <h2 id="calls-title" className={styles.h2}>
              Últimas llamadas
            </h2>
            {usage.recent_calls.length === 0 ? (
              <p className="muted">
                Todavía no hay llamadas. Pulsa Probar conexión en un proveedor para comprobar que
                su clave funciona.
              </p>
            ) : (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">Fecha</th>
                      <th scope="col">Proveedor y modelo</th>
                      <th scope="col">Uso</th>
                      <th scope="col">Estado</th>
                      <th scope="col" className={styles.num}>
                        Tokens (entrada + salida)
                      </th>
                      <th scope="col" className={styles.num}>
                        Coste (USD)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.recent_calls.map((c) => (
                      <tr key={c.id}>
                        <td className={styles.date}>{when(c.created_at)}</td>
                        <td>
                          {PROVIDER_NAMES[c.provider] ?? c.provider}
                          <span className={`muted ${styles.model}`}>{c.model}</span>
                        </td>
                        <td>{c.purpose === "smoke_test" ? "Prueba de conexión" : c.purpose}</td>
                        <td>
                          <span className={styles[`st_${c.status}`]}>
                            {STATUS_LABELS[c.status] ?? c.status}
                          </span>
                          {c.error && <span className={`muted ${styles.reason}`}>{c.error}</span>}
                        </td>
                        <td className={styles.num}>
                          {c.input_tokens + c.output_tokens > 0
                            ? `${int(c.input_tokens)} + ${int(c.output_tokens)}`
                            : "–"}
                        </td>
                        <td className={styles.num}>{usd(c.cost_usd, 6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {health && (
          <footer className={`muted ${styles.footer}`}>
            Base de datos: {health.database === "ok" ? "funcionando" : "con errores"}. Versión{" "}
            {health.version}.
          </footer>
        )}
      </main>
    </>
  );
}
