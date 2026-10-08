# Original Massive source archive

This archive preserves both the upstream and the original local source before
the separate yfinance migration. It contains no active workflows at the branch
root, so publishing this archive branch does not schedule a run or deploy Pages.
Old workflow definitions are preserved inside the source ZIPs for reference.

- Repository: https://github.com/yuz047/greenlight-trader
- Upstream source: `85199fbf2d8e39b600880977185e4c7c87d7ce0b`
- Migration source: `8ad51a585da46e0d2e7b020714a580e74c23ebc0`
- Archive date: 2026-10-06 UTC
- Intended archive branch: `archive/massive-original-20261006`
- Intended upstream recovery tag: `archive/massive-original-20261006-85199fb`

## Files and verification

| File | Source files | SHA-256 |
| --- | ---: | --- |
| `archives/massive-upstream-source-85199fb.zip` | 57 | `ad83145dd91dc2422ee829cc66a5084a7b47a0d573963361ed36d9ff33fdb988` |
| `archives/massive-local-source-20261006.zip` | 53 | `c9e8d4f3e887743060ca8e74e17dccb89b11dd610d0eaf6bdfbe41b5782d1ef5` |

`archives/source-archive-manifest.json` lists every archived source file and its
SHA-256. It identifies 13 content differences between shared upstream/local
files, distinguishes line-ending differences, and lists four source files that
exist only in the upstream version. The local source ZIP preserves the local
variant exactly; it is not replaced by the upstream copy.

These publishable ZIPs contain code, tests, documentation, web source, workflow
definitions and audited empty/example configuration. Generated `data/` outputs,
raw Yahoo histories, private archive metadata, credentials, caches and execution
environments are excluded. ZIP CRC verification and source credential scans
passed. The path scan finds two occurrences: each ZIP retains the same personal
filesystem-path line in `web/app.js` that was already present in the public
upstream source. No additional personal paths were introduced. This is a source
preservation archive, not a claim that the original source contains no personal
paths.

The two earlier full original ZIPs remain private local backups. They are
gitignored and are not the two source-only ZIPs in this archive branch. Generated
data differences are retained in those local originals rather than published.

## Recovery

To restore either source variant, verify its ZIP SHA-256 and extract the
`greenlight-massive-source/` directory into a separate folder. Supply credentials
through your own existing authorized environment if you later choose to run it.

The original upstream Git source is also recoverable directly:

```text
git clone https://github.com/yuz047/greenlight-trader greenlight-massive-upstream
git -C greenlight-massive-upstream checkout --detach 85199fbf2d8e39b600880977185e4c7c87d7ce0b
```

The recovery tag, when published, pins that same commit. Restoring source does
not enable the legacy scheduler or authorize a deployment. The archive and
migration branches are separate from `main`.
