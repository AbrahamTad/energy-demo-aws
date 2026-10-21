# EnergyDemo frontend

The dashboard supports two local development modes. Run these commands from
`frontend/` in WSL Ubuntu.

| Command | API | Dashboard data source |
| --- | --- | --- |
| `npm run dev` | FastAPI at `http://127.0.0.1:8000` | PostgreSQL |
| `npm run dev:floci` | Floci API Gateway at `http://127.0.0.1:4567` | Lambda sample data |

Start FastAPI and PostgreSQL as usual for the default mode. For Floci mode,
the existing EnergyDemo Floci container and API Gateway `dev` stage must be
available. Floci mode returns Solar, Wind, Hydro, and Battery sample records;
it does not read PostgreSQL.

Open the local URL printed by Vite (normally `http://localhost:5173`). To switch
modes, stop Vite with Ctrl+C, run the other command, and reload the browser.

React requests `/api/energy` in both modes. In Floci mode, Vite connects directly
to `127.0.0.1:4567`, sets the Host header to
`2dc5378b0c.execute-api.localhost.floci.io:4567`, and forwards the path as
`/dev/api/energy`. This selects the existing API without requiring browser DNS
configuration. The browser communicates with Vite on the same origin, so this
development flow does not require API CORS changes.

These proxy settings are for the Vite development server. `npm run build`
checks and builds the frontend; production hosting needs its own API routing.
`npm run preview` does not select the Floci development proxy.

Validation commands:

```bash
npm run lint
npm run build
curl --noproxy '*' http://localhost:5173/api/energy
```

In Floci mode, expect four records and the label
`Data source: Lambda sample data (local Floci API Gateway)`. In the default mode,
expect the records from PostgreSQL and `Data source: PostgreSQL`.

## Vite template reference

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
