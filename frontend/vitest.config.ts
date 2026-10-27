import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    env: {
      VITE_COGNITO_USER_POOL_ID: "eu-north-1_TestFixture",
      VITE_COGNITO_CLIENT_ID: "fixtureclient",
    },
  },
});
