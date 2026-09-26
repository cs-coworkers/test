# nexus-tools

Scripts for the Nexus2 migration. Owner: Cody. Specs and records live in Nexus, not here:
PRD `v1:00_Company/00_Projects/nexus-v2/PRD.md`, handoff `2026-09-26-clarice-to-cody-nexus2-migration-tooling`.

## `bin/export_v1_handoffs.py`: queue-day export

This is a one-time copy of every v1 handoff with status `open` or `accepted` into Nexus2 `queues/handoffs/`. Each copy is one file in the `skills/handoff/` format. It adds `to`, `from`, `date` and `topic` to the frontmatter, because `nexus.py index` reads these fields. The body is the v1 file. The script rewrites v1 paths in the body (absolute or relative) as `v1:<path>` pointers. It never overwrites, moves or deletes anything, so a re-run is safe.

Run it on queue day, on a machine where both drives are mounted:

1. Build the manifest from the v1 database with the Supabase connector (project `coworkers-global`). Save the
   result as `rows.json`, either as a bare list or as `{"generated_at": "<today>", "rows": [...]}`:

   ```sql
   select slug, from_agent, to_agent, opened_at, topic, status,
          accepted_at::date as accepted_on, updated_at::date as updated_on, file_path
   from public.handoffs where status in ('open', 'accepted') order by opened_at, slug;
   ```

2. Do a dry run: `python bin/export_v1_handoffs.py --manifest rows.json --v1-root <v1 Nexus folder>`
3. Write: add `--write`. Then run `python bin/nexus.py index` and `python bin/nexus.py lint`.

**Done when:** the dry run reports 0 conflict, 0 missing v1 file and 0 bad slug. After the write, `_generated/queue-handoffs.md` lists every exported row.
**Exit 1** means some items need a human. `machine_path` lists v1 bodies that hold a drive letter or user-home path the rewrite could not turn into a `v1:` pointer. Fix these by hand, or `nexus.py lint` fails with the `os-path` rule.

Snapshot on 2026-09-26: 154 rows (136 accepted, 18 open), all under `00_Company/02_Playbooks/handoffs/`, and every slug is valid.

## Tests

`python -m unittest discover nexus-tools/tests` needs Python 3.8+ and PyYAML.
