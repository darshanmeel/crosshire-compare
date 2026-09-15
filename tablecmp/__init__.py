"""CrossHire Compare - the pieces behind compare_app.py.

sql       quoting and DuckDB connections
theme     the Crosshire house style: tokens, CSS, status strip
sources   one CSV file and which of its rows to read
values    how a value is read: transform steps, type, canonical text
columns   the column table: pairing, common names, key and compare ticks
keys      key uniqueness, suggestion (Desbordante or DuckDB)
profile   per-column statistics and value frequencies
compare   running a comparison (engine, position, or hash) and reading it back
report    the Crosshire-styled HTML report
auto      two files in, the rest worked out
ui_*      the Streamlit screens
"""
