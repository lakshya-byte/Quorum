# PatchLoop frontend

Next.js 16 (App Router), React 19, Tailwind CSS v4. Read `AGENTS.md` first: this is not the Next.js
older docs describe, and the bundled docs live in `node_modules/next/dist/docs/`.

```bash
npm install
npm run mock                 # mock backend on :8080 (no Go, Mongo or agent needed); MOCK_GITHUB_APP=1 simulates the App install
npm run dev                  # http://localhost:3000, NEXT_PUBLIC_API_URL defaults to http://localhost:8080
npm run build && npm run lint
node e2e/flow.cjs            # full product flow in Chromium against the mock (needs `npx next start -p 3000`)
```

Sign up with any email; the OTP code in the mock is `123456`. Connect the demo GitHub account on
`/integrations`, then start a fix from `/new`.

Code map and design notes: `app/docs/frontend/page.mdx` (served at `/docs/frontend`).
