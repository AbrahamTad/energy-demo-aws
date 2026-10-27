import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { resolveBuildCognitoConfig } from "./src/auth/config.js";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const cognito = resolveBuildCognitoConfig(
    mode,
    env.VITE_COGNITO_USER_POOL_ID,
    env.VITE_COGNITO_CLIENT_ID,
  );
  return {
    define: cognito
      ? {
          "import.meta.env.VITE_COGNITO_USER_POOL_ID": JSON.stringify(
            cognito.userPoolId,
          ),
          "import.meta.env.VITE_COGNITO_CLIENT_ID": JSON.stringify(
            cognito.userPoolClientId,
          ),
        }
      : {},
    plugins: [
      react(),
      {
        name: "aws-content-security-policy",
        transformIndexHtml: () =>
          mode === "aws"
            ? [
                {
                  tag: "meta",
                  attrs: {
                    "http-equiv": "Content-Security-Policy",
                    content:
                      "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://cognito-idp.eu-north-1.amazonaws.com; object-src 'none'; base-uri 'self'; form-action 'self'",
                  },
                  injectTo: "head-prepend",
                },
              ]
            : [],
      },
    ],
    server: {
      proxy: {
        "/api":
          mode === "floci"
            ? {
                target: "http://127.0.0.1:4567",
                // Floci uses the Host header to select our existing REST API.
                changeOrigin: false,
                headers: {
                  host: "2dc5378b0c.execute-api.localhost.floci.io:4567",
                },
                rewrite: (path) => `/dev${path}`,
              }
            : {
                target: "http://127.0.0.1:8000",
                changeOrigin: true,
              },
      },
    },
  };
});
