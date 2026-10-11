import { existsSync, readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

const UI_PORT = Number(process.env.STUDIO_PORT ?? 4400);
const API_PORT = Number(process.env.STUDIO_API_PORT ?? 4401);

// certificat local (mkcert, voir studio/README.md) : HTTPS, que le téléphone exige pour garder l'écran
// allumé ou écouter le micro. Sans lui, on reste en HTTP.
const CERTS = new URL("./.certs/", import.meta.url);
const cert = (name: string) => new URL(name, CERTS);
const https = existsSync(cert("cert.pem")) && existsSync(cert("key.pem"))
  ? { cert: readFileSync(cert("cert.pem")), key: readFileSync(cert("key.pem")) }
  : undefined;

/** /rootCA.crt : le certificat public de l'autorité mkcert, à installer sur le téléphone. */
const rootCA: Plugin = {
  name: "studio-root-ca",
  configureServer(server) {
    server.middlewares.use("/rootCA.crt", (_req, res) => {
      if (!existsSync(cert("rootCA.crt"))) {
        res.statusCode = 404;
        res.end();
        return;
      }
      res.setHeader("Content-Type", "application/x-x509-ca-cert");
      res.end(readFileSync(cert("rootCA.crt")));
    });
  },
};

export default defineConfig({
  plugins: [vue(), rootCA],
  server: {
    port: UI_PORT,
    strictPort: true,
    https,
    // ecoute aussi sur le reseau local : l'interface est joignable depuis le telephone
    host: true,
    // Vite refuse les noms d'hote inconnus : autorise <nom-du-pc>.local (mDNS)
    allowedHosts: [".local"],
    // l'API Python tourne a cote ; Vite lui relaie tout /api (uploads et video compris)
    proxy: { "/api": `http://127.0.0.1:${API_PORT}` },
  },
});
