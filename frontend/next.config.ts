import type { NextConfig } from "next";

// Dirección interna del backend. En Docker es el servicio "backend"; fuera de Docker,
// el backend arrancado en local.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const isDev = process.env.NODE_ENV !== "production";

// Política de contenido: solo se cargan recursos de este mismo servidor.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    // Las llamadas a la IA pueden tardar varios minutos; por defecto el reenvío corta a 30 s.
    proxyTimeout: 620_000,
  },
  // El navegador solo habla con este servidor; las llamadas /api/* se reenvían al backend.
  // Así la cookie de sesión es del mismo origen y no hace falta habilitar CORS.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
