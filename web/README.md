# GreenLight Trader — web dashboard

Next.js App Router + Tailwind + Recharts. Public read-only.

## Run locally

```bash
npm install
npm run dev      # http://localhost:3000
```

By default the dashboard reads `../data/*.json` from the repo (this is what the
Python engine writes). If you set Supabase env vars, the dashboard reads live
from Postgres at request time.

## Env vars (Vercel)

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

Both can be exposed publicly — read-only access is enforced by RLS in Supabase.
The service-role key (which can write) belongs only in GitHub Actions.
