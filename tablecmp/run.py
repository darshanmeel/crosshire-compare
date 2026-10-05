"""Run a saved config with no page: the same comparison on other files, one pair or many.

    python -m tablecmp.run hr_compare_payroll__config.json
    python -m tablecmp.run config.json --left jan/hr.csv --right jan/payroll.csv --out results
    python -m tablecmp.run config.json --pairs pairs.csv --out results
    python -m tablecmp.run config.json --left hr_feb.csv --right payroll_feb.csv --connections team.yml

The config comes from the Downloads tab after a run (or the run folder's __config.json).
Its "pairs" list, or a --pairs CSV with left,right[,name_left,name_right] columns, runs
each pair on the config's settings. A database side asks for its password, or reads
COMPARE_PASSWORD_<CONNECTION>. A side picked from a folder connection takes a bare file name,
read in that folder; --connections adds a JSON or YAML connections file for the run. Exit code: 0 all identical, 1 a difference, 2 an error.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import os
import sys
from pathlib import Path

from .connections import FILES_ENV, load_all
from .runconfig import ConfigError, PairOutcome, env_name, pairs_of, read_config, run_pair


def passwords_for(conf: dict, pairs: list[dict]) -> dict[str, str]:
    """A password for each connection the run will fetch from that has none saved: from
    COMPARE_PASSWORD_<NAME>, else asked for once in a terminal."""
    from . import connections as cx
    wanted = {conf["sides"][w].get("connection") for w in "AB"
              if not any(p.get("left" if w == "A" else "right") for p in pairs)}
    out: dict[str, str] = {}
    for name in sorted(n for n in wanted if n):
        try:
            cx.resolve(name)
            continue
        except cx.PasswordNeeded:
            pass
        except KeyError:
            continue                              # said by the pair that needs it
        given = os.environ.get(f"COMPARE_PASSWORD_{env_name(name)}")
        if given:
            out[name] = given
        elif sys.stdin.isatty():
            out[name] = getpass.getpass(f"Password for connection {name}: ")
    return out


def read_pairs(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
                for r in csv.DictReader(fh)]
    if rows and not {"left", "right"} <= set(rows[0]):
        raise ConfigError(f"{path}: needs a left and a right column")
    return [r for r in rows if r.get("left") or r.get("right")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tablecmp.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("config", help="the __config.json saved after a run")
    ap.add_argument("--left", help="another file for side A - a bare name is read in A's folder connection")
    ap.add_argument("--right", help="another file for side B")
    ap.add_argument("--name-left", help="what to call side A (default: the file's stem)")
    ap.add_argument("--name-right", help="what to call side B")
    ap.add_argument("--pairs", help="a CSV of pairs: left,right[,name_left,name_right]")
    ap.add_argument("--out", "-o", help="copy each run folder here (default: it stays in the work folder)")
    ap.add_argument("--connections", "-c", action="append", default=[],
                    help="a JSON or YAML connections file to use as well (may be given again)")
    ap.add_argument("--quiet", "-q", action="store_true", help="no progress, just the results")
    args = ap.parse_args(argv)
    before = os.environ.get(FILES_ENV)
    if args.connections:                         # read-only, under the store and the environment
        os.environ[FILES_ENV] = os.pathsep.join(
            [str(Path(c).resolve()) for c in args.connections] + [before or ""]).strip(os.pathsep)
    try:
        return _run(args)
    finally:                                     # a caller's environment is left as it was
        if before is None:
            os.environ.pop(FILES_ENV, None)
        else:
            os.environ[FILES_ENV] = before


def _run(args: argparse.Namespace) -> int:
    say = (lambda _m: None) if args.quiet else (lambda m: print("  " + str(m), flush=True))
    try:
        conf = read_config(Path(args.config).read_text(encoding="utf-8"))
        pairs = read_pairs(args.pairs) if args.pairs else pairs_of(conf, args.left, args.right)
        load_all()                               # a connections file that cannot be read stops here
    except (OSError, ValueError) as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    passwords = passwords_for(conf, pairs)
    done: list[PairOutcome] = []
    for i, p in enumerate(pairs, 1):
        names = (p.get("name_left") or (args.name_left if len(pairs) == 1 else None),
                 p.get("name_right") or (args.name_right if len(pairs) == 1 else None))
        print(f"[{i}/{len(pairs)}] {p.get('left') or conf['sides']['A'].get('path') or conf['sides']['A'].get('connection')}"
              f"  against  {p.get('right') or conf['sides']['B'].get('path') or conf['sides']['B'].get('connection')}",
              flush=True)
        o = run_pair(conf, p.get("left") or None, p.get("right") or None, names, args.out, passwords, say)
        done.append(o)
        if o.error:
            print(f"  ✗ {o.status}: {o.error}", flush=True)
        else:
            c = o.counts
            print(f"  → {o.status}: {c['matched']:,} matched · {c['differ']:,} differ ({c['cells']:,} cells) · "
                  f"{c['only_left']:,} only left · {c['only_right']:,} only right\n    {o.folder}", flush=True)
    if len(done) > 1:
        print(f"\n{len(done)} pairs: " + ", ".join(
            f"{sum(o.status == s for o in done)} {s.lower()}" for s in dict.fromkeys(o.status for o in done)))
    if any(o.error for o in done):
        return 2
    return 0 if all(o.status == "Identical" for o in done) else 1


if __name__ == "__main__":
    raise SystemExit(main())
