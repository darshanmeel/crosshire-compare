# To do

## Run a comparison again from a config file - no uploading, no setting up

You set up and run a comparison on the page, and you're happy with it. Next you want the same comparison for 5-10 more pairs of files. Only the left and right change. Today you'd upload each pair and redo the column table, the steps and the key on every one.

### What it has to carry
Everything the page decided, so a rerun gives the same answer:
- the sources: file paths, or a saved connection name plus its SQL
- the read options: delimiter, rows to read, file filters
- the column table: pairs, common names, Type, Case, steps on each side (`a_steps` / `b_steps`) and the key-format fixes that were applied
- the key, the compare list, mode (key / position / hash), tolerance, ignore case, trim, empty-as-null, null tokens
- the Rows filters (both / left / right)
- the outputs: table formats, report row limit, save folder

Most of this is already in the run's `cfg`, and in `summary.json` → `settings`. What's missing is the sources and the read options.

### Steps, easiest first
1. **Download the config.** A *Save config* button on the Downloads tab writes `<pair>__config.json`: the run's `cfg` plus the sources and the read options, with a `version` field. Passwords and private keys are never written. A connection is saved by name only.
2. **Run it from the command line**, for many pairs. A runner such as `python -m tablecmp.run config.json`, with
   - `--left/--right` to swap the files, or
   - a `pairs:` list in the file (`[{left, right, name}]`), sharing one set of settings.

   It goes through `run_comparison` and writes the same outputs (cell diffs, one-sided rows, report, summary).

   This can't be plain `csvdiff.py config`. The engine has no column steps, types or key fixes: the app applies those in DuckDB views before the engine runs. Either the runner reuses `tablecmp.values.register` and `compare.run_comparison` (recommended), or the steps get ported into the engine.

   Columns the config names but a new file lacks are reported, not guessed: the pair is skipped with an error and the rest still run.
3. **Load the config on the page.** Next to Upload / Path / Database in the sidebar, a *Config file* option fills both sides and the whole column table from the file, then runs the comparison. Afterwards you can still change anything by hand. Load mapping already does this for the column table alone; this extends it to every setting.
4. **Batch on the page** (optional, later). With a config that has a `pairs:` list, run them all and show one verdict row per pair, linking to each pair's report.

### Tests to write
- config round-trip: save → load → same `signature()`
- runner on two pairs with steps and a key fix gives the same counts as the page
- a missing column fails that pair only
- no secret ever lands in the file
