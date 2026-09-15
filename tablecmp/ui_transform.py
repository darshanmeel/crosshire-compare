"""Transform and convert values: steps per column per side, previewed on five rows."""
from __future__ import annotations

import duckdb
import streamlit as st

from .columns import set_steps
from .sources import Side
from .state import bump, forget_results
from .theme import esc
from .ui_columns import Setup
from .values import (FORMAT_PRESETS, NUMERIC_PARAMS, PARAM_LABELS, STEPS, TYPES,
                     ReadOptions, blank_param, conversion_report, describe_step, final_kind,
                     function_catalog, has_x, try_steps)


def _steps_html(steps: list) -> str:
    if not steps:
        return '<div class="steps"><span class="n">—</span>no steps: the value as it is in the file</div>'
    parts = [f'<span class="n">{i + 1:02d}</span>{esc(describe_step(s))}' for i, s in enumerate(steps)]
    return '<div class="steps">' + '<span class="arrow">→</span>'.join(parts) + "</div>"


def render(A: Side, B: Side, NA: str, NB: str, setup: Setup, opts: ReadOptions) -> None:
    if not setup.specs:
        return
    with_steps = [s.canon for s in setup.specs if s.a_steps or s.b_steps]
    with st.expander("Transform and convert values - trim, left, replace, to date… "
                     "step by step, previewed on the first five rows"
                     + (f" · {len(with_steps)} column(s) have steps" if with_steps else ""),
                     expanded=False):
        st.caption(
            "Pick a column and a side, then add steps: each one runs on the result of the "
            "one before - trim → left 10 → to timestamp (format) → to date. Steps run before "
            "the pair's **Type**; a conversion step sets the Type for you. A value a "
            "conversion cannot read keeps its text, so it shows up as a difference and in "
            "**Check this column**. The preview is the first five rows of that file.")
        h1, h2, h3 = st.columns([3, 2, 2])
        canon = h1.selectbox("Column", setup.canon, key="tx_col")
        side_name = h2.radio("Side", [NA, NB], key="tx_side", horizontal=True)
        which = "A" if side_name == NA else "B"
        spec = next(s for s in setup.specs if s.canon == canon)
        side = A if which == "A" else B
        kind_now = spec.kind
        kind = h3.selectbox("Type · both sides", TYPES, index=TYPES.index(kind_now),
                            key=f"tx_kind_{canon}_{kind_now}")
        if kind != kind_now:
            cm = st.session_state["cmap"]
            cm.loc[cm["Common name"] == canon, "Type"] = kind
            bump()
            forget_results()
            st.rerun()

        steps = list(spec.steps(which))
        st.markdown(f"**{esc(side_name)} · {esc(canon)}** &nbsp; {_steps_html(steps)}",
                    unsafe_allow_html=True)

        a1, a2, a3 = st.columns([2, 3, 1])
        op = a1.selectbox("Add a step", list(STEPS), key="tx_op")
        _, params = STEPS[op]
        values: dict[str, str] = {}
        with a2:
            if "fmt" in params:
                preset = st.selectbox("What the value looks like", [""] + list(FORMAT_PRESETS),
                                      key="tx_fmt_preset",
                                      format_func=lambda k: f"{k}   →   {FORMAT_PRESETS[k]}" if k else "(auto)")
                values["fmt"] = FORMAT_PRESETS.get(preset, "")
                custom_fmt = st.text_input("or a format", value=values["fmt"], key=f"tx_fmt_{preset}",
                                           placeholder="%d/%m/%Y %H:%M")
                values["fmt"] = custom_fmt.strip()
            for name in params:
                if name == "fmt":
                    continue
                if name in NUMERIC_PARAMS:
                    values[name] = str(st.number_input(PARAM_LABELS[name], 1, 100000, 6 if name == "n" else 4,
                                                       key=f"tx_p_{name}"))
                elif name == "expr":
                    values[name] = st.text_input(PARAM_LABELS[name], key="tx_p_expr",
                                                 placeholder="upper(split_part(x, '-', 1))")
                    cat = function_catalog()
                    pick = st.selectbox("DuckDB functions - type to search", range(len(cat)), index=None,
                                        key="tx_fn", format_func=lambda i: cat.at[i, "signature"],
                                        placeholder="left · regexp_replace · split_part · strptime …")
                    if pick is not None:
                        row = cat.iloc[int(pick)]
                        st.caption(f"`{row['template']}` - {row['description']}"
                                   + (f" · e.g. `{row['example']}`" if row["example"] else ""))
                else:
                    values[name] = st.text_input(PARAM_LABELS[name], key=f"tx_p_{name}")
        with a3:
            st.write("")
            st.write("")
            if st.button("Add", key="tx_add", type="primary", width="stretch"):
                if op == "custom expression" and not has_x(values.get("expr", "")):
                    st.error("The expression must mention `x`, the value.")
                elif (missing := blank_param({"op": op, "params": values})):
                    st.error(f"Type the {missing} first - one space counts.")
                else:
                    steps.append({"op": op, "params": values})
                    _save(canon, which, steps, kind)
            if st.button("Remove last", key="tx_pop", width="stretch", disabled=not steps):
                _save(canon, which, steps[:-1], kind)
            if st.button("Clear", key="tx_clear", width="stretch", disabled=not steps):
                _save(canon, which, [], kind)
            other = "B" if which == "A" else "A"
            if st.button(f"Copy to {NB if which == 'A' else NA}", key="tx_copy", width="stretch",
                         disabled=not steps):
                _save(canon, other, steps, kind)

        try:
            prev = try_steps(side, spec.src(which), steps, kind, opts)
            st.dataframe(prev, width="stretch", hide_index=True, height=45 + 35 * max(len(prev), 1))
        except duckdb.Error as exc:
            st.error(f"DuckDB says: {exc}")
        if st.button("Check this column on all rows", key="tx_check",
                     help="Counts the values on each side that do not convert."):
            try:
                rep = conversion_report(A, B, [spec], NA, NB, opts)
                if len(rep):
                    st.dataframe(rep, width="stretch", hide_index=True)
                else:
                    st.info("Text with no steps - nothing to convert.")
            except duckdb.Error as exc:
                st.error(f"DuckDB says: {exc}")


def _save(canon: str, which: str, steps: list, kind: str) -> None:
    cm = st.session_state["cmap"]
    set_steps(cm, canon, which, steps)
    fk = final_kind(steps)
    if fk:
        cm.loc[cm["Common name"] == canon, "Type"] = fk
    bump()
    forget_results()
    st.rerun()
