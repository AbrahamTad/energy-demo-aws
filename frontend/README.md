# EnergyDemo frontend

React + TypeScript workspace with Home, Energy Dashboard, Login, Register,
User Dashboard, Profile and Settings, plus email verification and password
recovery. Public charts show the current database-backed `/api/energy` response;
the protected dashboard loads only the signed-in user's persistent records from
`/api/me/energy`. Personal create/edit/delete forms, paging and loading/error
states use Cognito access tokens held in memory. Ownership is enforced server-side
from the verified Cognito `sub`; no personal readings are fabricated or published.
Source filtering and CSV export work locally on the public snapshot.
UI primitives, icons and charts use CSS/SVG; the only new runtime dependencies
are React Router and AWS Amplify Auth (modular imports).

## Routes and sessions

Hash routes (`/#/energy`, `/#/profile`) support direct navigation/reloads on the
existing private S3 + CloudFront site. No global 403/404-to-index rewrite is added,
so API errors remain API errors. `/dashboard`, `/profile` and `/settings` require
a Cognito session; the public energy endpoint is intentionally unchanged.

Authentication uses SRP via Amplify, email verification, password recovery,
optional TOTP enrollment/challenges, profile attribute updates, and global
sign-out. Access/ID/refresh tokens stay in Amplify's shared memory storage.
Reloading or closing the tab requires a new sign-in. Only the appearance setting
is persisted in localStorage. No password, profile or JWT is stored there.

AWS-mode builds use the deployed public ID pair in `src/auth/config.ts`:
`eu-north-1_6m60ePWS0` / `796jkcsk4dc5scoc77r8ejies7`. Vite injects both values
at build time, including when GitHub repository variables are unset. Optional
`COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` repository variables must be set
together and match this pair; partial, malformed or conflicting values fail the
AWS build. The reusable Build AWS workflow supplies these public overrides;
the manual deploy workflow consumes its same-commit artifact without rebuilding.
No build or deployment job reads the separate Cognito Terraform state.

For local development, copy `.env.example` to `.env.local` and explicitly fill
both public IDs. Unconfigured local development keeps account actions unavailable.
There is no alternate authentication path. Never put credentials or a client
secret in any `VITE_` variable. An intentional production pool migration must
update the public pair, its regression assertion, and repository variables together.

After source review/merge, ensure Build AWS passes, then start a **new** manual
deployment from `main` using the existing plan and approval safeguards. If the
repository variables contain old values, remove both or set them to the pair
above before building. Do not apply the Cognito root again to release frontend
changes. After release, check `/#/register` → `/#/verify` → `/#/login` with an email
you control, then check `/#/dashboard`, logout, and anonymous protected redirects.
Only the public energy snapshot stays available without an authenticated session.

See [the Cognito deployment guide](../infrastructure/terraform-aws-auth/README.md)
for costs, resources, state isolation, exact approval-only deployment commands,
real-account acceptance checks and identity-state isolation. See the
[DynamoDB guide](../infrastructure/terraform-aws/STEP2-DYNAMODB.md) for private API
authorization, costs, public seed migration and the approval-only release steps.

## Checks

Use Node 24.21.0 as pinned by CI, then from this directory:

```bash
npm ci
npm run lint
npm test
npm run build -- --mode aws
```

Vitest + Testing Library exercise the API parser, retry/filter UI, protected
routes, SRP requests, registration/verification/reset, TOTP challenges, profile
updates, token storage selection and private CRUD/pagination/account isolation.
SDK doubles exist **only in tests**, which
do not call AWS or send email. Live Cognito acceptance requires approval and an
actual pool. The AWS build adds a restrictive content security policy, allowing
same-origin assets/API and the regional Cognito endpoint, without inline scripts
or eval. Vite's development mode omits that production-only policy for HMR.

## Local energy services

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

## Exact first-release commit scope

This historical 38-file scope was committed in `0a4feca`. For the current
DynamoDB release, use the **36-file Step 2.4 allowlist** in the
[DynamoDB guide](../infrastructure/terraform-aws/STEP2-DYNAMODB.md#step-24-exact-release-scope-and-safe-release-order).
Do not reuse this first-release staging command for Step 2.4.

```bash
git add -- \
  .github/workflows/build-aws.yml \
  frontend/.env.example \
  frontend/README.md \
  frontend/index.html \
  frontend/package-lock.json \
  frontend/package.json \
  frontend/public/favicon.svg \
  frontend/src/App.css \
  frontend/src/App.test.tsx \
  frontend/src/App.tsx \
  frontend/src/auth/AuthProvider.tsx \
  frontend/src/auth/client.test.ts \
  frontend/src/auth/client.ts \
  frontend/src/auth/config.test.ts \
  frontend/src/auth/config.ts \
  frontend/src/auth/context.ts \
  frontend/src/components/Energy.tsx \
  frontend/src/components/Forms.tsx \
  frontend/src/components/Icon.tsx \
  frontend/src/components/Layout.tsx \
  frontend/src/components/Theme.tsx \
  frontend/src/index.css \
  frontend/src/lib/energy-context.ts \
  frontend/src/lib/energy.test.ts \
  frontend/src/lib/energy.ts \
  frontend/src/lib/sources.ts \
  frontend/src/lib/theme.ts \
  frontend/src/lib/useAction.ts \
  frontend/src/pages/AccountPages.tsx \
  frontend/src/pages/AuthPages.tsx \
  frontend/src/pages/EnergyPages.tsx \
  frontend/src/test/setup.ts \
  frontend/vite.config.ts \
  frontend/vitest.config.ts \
  infrastructure/terraform-aws-auth/.terraform.lock.hcl \
  infrastructure/terraform-aws-auth/README.md \
  infrastructure/terraform-aws-auth/main.tf \
  infrastructure/terraform-aws-auth/tests/offline.tftest.hcl
```

Do not stage generated `.terraform/` directories, state, saved plans, artifacts,
`.env.local`, or unrelated local infrastructure/database files. The four named
identity source files preserve the separate root; they do not add an auth apply
step or expand deployment IAM permissions.
