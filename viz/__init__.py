"""Dash visualization layer (issues #18-#20).

A self-contained Dash app rendering the core unit layer on an interactive
scatter map, with a separate runtime (`requirements-viz.txt`, gunicorn) and
its own container image (#21).  The `etl` package is imported read-side
(schema constants) but never imports `viz`, keeping the two runtimes apart.
"""