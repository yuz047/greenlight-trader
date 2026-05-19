# Supabase setup

1. Create a new Supabase project.
2. Open the SQL editor and run `schema.sql` once.
3. Project Settings → API:
   - Copy `Project URL` → `SUPABASE_URL` (GH Actions) and `NEXT_PUBLIC_SUPABASE_URL` (Vercel).
   - Copy `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (GH Actions, **secret**).
   - Copy `anon` key → `NEXT_PUBLIC_SUPABASE_ANON_KEY` (Vercel — safe to expose).

The schema enables RLS and grants `SELECT` to anyone via the anon key.
Writes only succeed with the service-role key, which never leaves GitHub Actions.

If you skip Supabase entirely, everything still works — the Python engine writes
to `data/*.json` and the Next.js dashboard falls back to those files at build time.
