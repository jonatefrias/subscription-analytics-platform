"""Small SVG chart helpers for the static reports.

Charts are plain inline SVG so the pages have no JavaScript dependencies and no build step.
Colours are CSS variables (defined in page.py), which is what makes light and dark mode work.
Every mark carries a `data-tip` attribute that the page turns into a hover tooltip.
"""

from __future__ import annotations

import math
from html import escape

W = 720
SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"]


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    first, last = math.floor(lo / step + 1e-9), math.ceil(hi / step - 1e-9)
    return [round(i * step, 10) for i in range(first, last + 1)]


def _svg(height: int, body: list[str], label: str) -> str:
    return (
        f'<svg viewBox="0 0 {W} {height}" role="img" aria-label="{escape(label)}" class="chart">'
        + "".join(body)
        + "</svg>"
    )


def legend(names: list[str], colors: list[str] | None = None) -> str:
    colors = colors or SERIES
    items = "".join(
        f'<span class="key"><i style="background:{c}"></i>{escape(n)}</span>'
        for n, c in zip(names, colors, strict=False)
    )
    return f'<div class="legend">{items}</div>'


def line_chart(
    x_labels: list[str],
    series: list[dict],
    fmt,
    label: str,
    height: int = 300,
    y_min: float | None = 0.0,
    band: tuple[list[float], list[float]] | None = None,
    notes: dict[int, str] | None = None,
    tick_every: int | None = None,
    tick_start: int = 0,
    x_title: str = "",
    zero_line: bool = False,
) -> str:
    """Lines over an ordered x axis. series: [{"name", "values", "color"?}]; None values break the line."""
    left, right, top, bottom = 56, 96, 18, 44 if x_title else 30
    n = len(x_labels)
    values = [v for s in series for v in s["values"] if v is not None]
    if band:
        values += [*band[0], *band[1]]
    lo = min(values) if y_min is None else min(y_min, min(values))
    ticks = _ticks(lo, max(values))
    lo, hi = ticks[0], ticks[-1]

    def x(i):
        return left + (W - left - right) * (i / max(n - 1, 1))

    def y(v):
        return top + (height - top - bottom) * (1 - (v - lo) / (hi - lo))

    out = []
    for t in ticks:
        out.append(f'<line x1="{left}" x2="{W - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>')
        out.append(f'<text x="{left - 8}" y="{y(t) + 4:.1f}" class="tick" text-anchor="end">{escape(fmt(t))}</text>')
    if zero_line and lo < 0 < hi:
        out.append(f'<line x1="{left}" x2="{W - right}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="axis"/>')
    every = tick_every or max(1, round(n / 8))
    for i in range(tick_start, n, every):
        out.append(
            f'<text x="{x(i):.1f}" y="{height - bottom + 18}" class="tick" text-anchor="middle">{escape(x_labels[i])}</text>'
        )
    if x_title:
        out.append(
            f'<text x="{(left + W - right) / 2}" y="{height - 6}" class="tick" text-anchor="middle">{escape(x_title)}</text>'
        )
    for i, text in (notes or {}).items():
        out.append(f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{top}" y2="{height - bottom}" class="note-line"/>')
        anchor = "end" if i > n * 0.75 else "start"
        dx = -5 if anchor == "end" else 5
        out.append(
            f'<text x="{x(i) + dx:.1f}" y="{top + 10}" class="note" text-anchor="{anchor}">{escape(text)}</text>'
        )
    if band:
        upper = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(band[1]))
        lower = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in reversed(list(enumerate(band[0]))))
        out.append(f'<polygon points="{upper} {lower}" class="band"/>')

    ends = []
    for k, s in enumerate(series):
        color = s.get("color", SERIES[k])
        path, pen = [], "M"
        for i, v in enumerate(s["values"]):
            if v is None:
                pen = "M"
                continue
            path.append(f"{pen}{x(i):.1f},{y(v):.1f}")
            pen = "L"
        out.append(
            f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        )
        last = max(i for i, v in enumerate(s["values"]) if v is not None)
        ends.append([y(s["values"][last]), x(last), color, fmt(s["values"][last])])
    ends.sort()
    for a, b in zip(ends, ends[1:], strict=False):  # keep end labels from overlapping
        if b[0] - a[0] < 14:
            b[0] = a[0] + 14
    for ey, ex, _, text in ends:
        out.append(f'<text x="{ex + 8:.1f}" y="{ey + 4:.1f}" class="value">{escape(text)}</text>')

    step = (W - left - right) / max(n - 1, 1)
    for i in range(n):  # one hover column per x position
        parts = [x_labels[i]] + [f"{s['name']}: {fmt(s['values'][i])}" for s in series if s["values"][i] is not None]
        if band:
            parts.append(f"95% CI: {fmt(band[0][i])} to {fmt(band[1][i])}")
        out.append(
            f'<rect x="{x(i) - step / 2:.1f}" y="{top}" width="{step:.1f}" height="{height - top - bottom}" '
            f'class="hit" data-tip="{escape(" | ".join(parts))}"/>'
        )
    return _svg(height, out, label)


def bar_chart(
    rows: list[tuple[str, float]], fmt, label: str, color: str = SERIES[0], x_max: float | None = None
) -> str:
    """Horizontal bars, one per row, with the value written at the end of the bar."""
    return grouped_bar_chart(
        [r[0] for r in rows], [{"name": label, "values": [r[1] for r in rows], "color": color}], fmt, label, x_max
    )


def grouped_bar_chart(categories: list[str], series: list[dict], fmt, label: str, x_max: float | None = None) -> str:
    left, right, top = 150, 70, 6
    k = len(series)
    bar, gap, group_gap = (18, 2, 14) if k > 1 else (20, 0, 10)
    group_h = k * bar + (k - 1) * gap
    height = top + len(categories) * (group_h + group_gap) + 4
    hi = x_max or max(v for s in series for v in s["values"]) * 1.0
    out = []
    for c, category in enumerate(categories):
        y0 = top + c * (group_h + group_gap)
        out.append(
            f'<text x="{left - 10}" y="{y0 + group_h / 2 + 4:.1f}" class="label" text-anchor="end">{escape(category)}</text>'
        )
        for j, s in enumerate(series):
            v = s["values"][c]
            width = max((W - left - right) * v / hi, 1) if hi else 1
            yb = y0 + j * (bar + gap)
            tip = f"{category} | {s['name']}: {fmt(v)}" if k > 1 else f"{category}: {fmt(v)}"
            out.append(
                f'<path d="M{left},{yb} h{width - 4:.1f} a4,4 0 0 1 4,4 v{bar - 8} a4,4 0 0 1 -4,4 h-{width - 4:.1f} z" '
                f'fill="{s.get("color", SERIES[j])}" data-tip="{escape(tip)}"/>'
            )
            out.append(
                f'<text x="{left + width + 6:.1f}" y="{yb + bar / 2 + 4:.1f}" class="value">{escape(fmt(v))}</text>'
            )
    out.append(f'<line x1="{left}" x2="{left}" y1="{top - 2}" y2="{height - 6}" class="axis"/>')
    return _svg(height, out, label)


def stacked_bar_chart(x_labels: list[str], series: list[dict], fmt, label: str, height: int = 320, notes=None) -> str:
    """Vertical stacked bars; positive values stack up from zero and negative values stack down."""
    left, right, top, bottom = 56, 16, 18, 30
    n = len(x_labels)
    pos = [sum(max(s["values"][i], 0) for s in series) for i in range(n)]
    neg = [sum(min(s["values"][i], 0) for s in series) for i in range(n)]
    ticks = _ticks(min(neg), max(pos))
    lo, hi = ticks[0], ticks[-1]
    slot = (W - left - right) / n
    bar = max(slot - 2, 2)

    def y(v):
        return top + (height - top - bottom) * (1 - (v - lo) / (hi - lo))

    out = []
    for t in ticks:
        out.append(f'<line x1="{left}" x2="{W - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>')
        out.append(f'<text x="{left - 8}" y="{y(t) + 4:.1f}" class="tick" text-anchor="end">{escape(fmt(t))}</text>')
    for i, text in (notes or {}).items():
        xi = left + slot * (i + 0.5)
        out.append(f'<line x1="{xi:.1f}" x2="{xi:.1f}" y1="{top}" y2="{height - bottom}" class="note-line"/>')
        out.append(f'<text x="{xi + 5:.1f}" y="{top + 10}" class="note">{escape(text)}</text>')
    for i in range(n):
        up = down = 0.0
        x0 = left + slot * i + 1
        for k, s in enumerate(series):
            v = s["values"][i]
            if v == 0:
                continue
            a, b = (up, up + v) if v > 0 else (down + v, down)
            if v > 0:
                up += v
            else:
                down += v
            h = max(y(a) - y(b) - 1, 0.5)  # 1px surface gap between segments
            tip = f"{x_labels[i]} | {s['name']}: {fmt(v)}"
            out.append(
                f'<rect x="{x0:.1f}" y="{y(b):.1f}" width="{bar:.1f}" height="{h:.1f}" fill="{s.get("color", SERIES[k])}" '
                f'data-tip="{escape(tip)}"/>'
            )
    out.append(f'<line x1="{left}" x2="{W - right}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="axis"/>')
    for i in range(0, n, max(1, round(n / 8))):
        out.append(
            f'<text x="{left + slot * (i + 0.5):.1f}" y="{height - 10}" class="tick" text-anchor="middle">{escape(x_labels[i])}</text>'
        )
    return _svg(height, out, label)


def heatmap(row_labels: list[str], col_labels: list[str], matrix: list[list[float | None]], fmt, label: str) -> str:
    """One hue, opacity by value. Cells with no data are left empty."""
    left, top, cell_h = 70, 22, 19
    cell_w = (W - left - 4) / len(col_labels)
    height = top + len(row_labels) * cell_h + 4
    out = [
        f'<text x="{left + cell_w * (j + 0.5):.1f}" y="14" class="tick" text-anchor="middle">{escape(c)}</text>'
        for j, c in enumerate(col_labels)
    ]
    for i, r in enumerate(row_labels):
        yc = top + i * cell_h
        out.append(f'<text x="{left - 8}" y="{yc + 13}" class="tick" text-anchor="end">{escape(r)}</text>')
        for j, v in enumerate(matrix[i]):
            if v is None:
                continue
            out.append(
                f'<rect x="{left + j * cell_w + 1:.1f}" y="{yc + 1}" width="{cell_w - 2:.1f}" height="{cell_h - 2}" rx="2" '
                f'fill="var(--s1)" fill-opacity="{0.08 + 0.92 * v:.3f}" '
                f'data-tip="{escape(f"Cohort {r} | {col_labels[j]}: {fmt(v)}")}"/>'
            )
            ink = "var(--on-dark)" if v > 0.55 else "var(--ink)"
            out.append(
                f'<text x="{left + cell_w * (j + 0.5):.1f}" y="{yc + 13}" class="cell" text-anchor="middle" fill="{ink}">'
                f"{escape(fmt(v))}</text>"
            )
    return _svg(height, out, label)


def interval_chart(
    rows: list[tuple[str, float, float, float]], fmt, label: str, band: tuple[float, float] | None = None
) -> str:
    """Point estimates with confidence intervals, one row each, around a zero reference line."""
    left, right, top, row_h, bottom = 150, 24, 8, 30, 28
    height = top + len(rows) * row_h + bottom
    ticks = _ticks(min(0, min(r[2] for r in rows)), max(0, max(r[3] for r in rows)))
    lo, hi = ticks[0], ticks[-1]

    def x(v):
        return left + (W - left - right) * (v - lo) / (hi - lo)

    out = []
    if band:
        out.append(
            f'<rect x="{x(band[0]):.1f}" y="{top}" width="{x(band[1]) - x(band[0]):.1f}" height="{len(rows) * row_h}" class="band"/>'
        )
    for t in ticks:
        out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top}" y2="{height - bottom}" class="grid"/>')
        out.append(
            f'<text x="{x(t):.1f}" y="{height - bottom + 16}" class="tick" text-anchor="middle">{escape(fmt(t))}</text>'
        )
    out.append(f'<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{top}" y2="{height - bottom}" class="axis"/>')
    for i, (name, est, low, high) in enumerate(rows):
        yc = top + row_h * (i + 0.5)
        tip = f"{name}: {fmt(est)} (95% CI {fmt(low)} to {fmt(high)})"
        out.append(f'<text x="{left - 10}" y="{yc + 4:.1f}" class="label" text-anchor="end">{escape(name)}</text>')
        out.append(
            f'<line x1="{x(low):.1f}" x2="{x(high):.1f}" y1="{yc:.1f}" y2="{yc:.1f}" stroke="var(--ink)" stroke-width="2"/>'
        )
        out.append(
            f'<circle cx="{x(est):.1f}" cy="{yc:.1f}" r="5" fill="var(--ink)" stroke="var(--surface)" stroke-width="2"/>'
        )
        out.append(
            f'<rect x="{left}" y="{yc - row_h / 2:.1f}" width="{W - left - right}" height="{row_h}" class="hit" data-tip="{escape(tip)}"/>'
        )
    return _svg(height, out, label)
