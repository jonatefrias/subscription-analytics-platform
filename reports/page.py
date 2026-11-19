"""Page shell shared by every report: styles, navigation, tooltip script and small HTML helpers."""

from __future__ import annotations

from html import escape

REPO = "https://github.com/jonatefrias/subscription-analytics-platform"
NAV = [
    ("index.html", "Overview"),
    ("revenue.html", "Revenue"),
    ("retention.html", "Retention"),
    ("acquisition.html", "Acquisition"),
    ("experiment.html", "Experiment"),
]

CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --raised: #ffffff; --ink: #0b0b0b; --ink2: #52514e; --line: #e4e3df; --on-dark: #ffffff;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --raised: #222221; --ink: #f0efec; --ink2: #c3c2b7; --line: #34342f; --on-dark: #ffffff;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--ink); line-height: 1.55;
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 820px; margin: 0 auto; padding: 0 16px 64px; }
nav { display: flex; flex-wrap: wrap; gap: 4px 18px; padding: 18px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
nav a { color: var(--ink2); text-decoration: none; padding: 2px 0; }
nav a[aria-current] { color: var(--ink); font-weight: 600; border-bottom: 2px solid var(--ink); }
nav a:hover { color: var(--ink); }
nav .repo { margin-left: auto; }
h1 { font-size: clamp(26px, 4.5vw, 34px); line-height: 1.2; margin: 40px 0 12px; letter-spacing: -0.01em; text-wrap: balance; }
h2 { font-size: 20px; line-height: 1.3; margin: 48px 0 8px; text-wrap: balance; }
p { margin: 0 0 12px; max-width: 68ch; }
a { color: var(--s1); }
.lede { font-size: 18px; color: var(--ink2); }
.kicker { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink2); margin-top: 40px; }
.kicker + h1 { margin-top: 6px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 24px 0 8px; }
.tile { background: var(--raised); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }
.tile b { display: block; font-size: 26px; line-height: 1.15; font-variant-numeric: tabular-nums; }
.tile span { font-size: 13px; color: var(--ink2); }
figure { margin: 16px 0 8px; background: var(--raised); border: 1px solid var(--line); border-radius: 8px; padding: 16px 12px 10px; overflow-x: auto; }
figcaption { font-size: 13px; color: var(--ink2); padding: 0 4px 10px; }
.chart { display: block; width: 100%; min-width: 520px; height: auto; font-family: inherit; }
.chart text { fill: var(--ink2); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.chart .value, .chart .label { fill: var(--ink); font-size: 12px; }
.chart .cell { font-size: 10px; }
.chart .note { font-size: 11px; }
.chart .grid { stroke: var(--line); stroke-width: 1; }
.chart .axis { stroke: var(--ink2); stroke-width: 1; }
.chart .note-line { stroke: var(--ink2); stroke-width: 1; stroke-dasharray: 3 3; }
.chart .band { fill: var(--ink2); fill-opacity: 0.16; }
.chart .hit { fill: transparent; }
.chart [data-tip]:hover { filter: brightness(1.12); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 13px; color: var(--ink2); padding: 0 4px 8px; }
.key i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
details { margin: 4px 0 0; font-size: 13px; color: var(--ink2); }
summary { cursor: pointer; padding: 4px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; font-size: 13px; margin: 8px 0; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 5px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { font-weight: 600; color: var(--ink2); }
table.wide { width: 100%; font-size: 14px; color: var(--ink); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-top: 24px; }
.card { display: block; background: var(--raised); border: 1px solid var(--line); border-radius: 8px; padding: 18px; color: inherit; text-decoration: none; }
.card:hover { border-color: var(--ink2); }
.card h3 { margin: 0 0 6px; font-size: 17px; }
.card b { display: block; font-size: 24px; margin: 10px 0 2px; font-variant-numeric: tabular-nums; }
.card p { font-size: 14px; color: var(--ink2); margin: 0; }
.source { font-size: 13px; color: var(--ink2); border-top: 1px solid var(--line); margin-top: 56px; padding-top: 16px; }
.source code, p code, li code { font-size: 0.9em; background: var(--raised); border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; }
ul { padding-left: 20px; max-width: 68ch; }
li { margin-bottom: 6px; }
#tip { position: fixed; pointer-events: none; z-index: 10; max-width: 280px; background: var(--ink); color: var(--surface);
  font-size: 12.5px; line-height: 1.4; padding: 6px 9px; border-radius: 6px; display: none; white-space: pre-line; }
"""

JS = """
const tip = document.getElementById('tip');
document.addEventListener('pointermove', (e) => {
  const mark = e.target.closest('[data-tip]');
  if (!mark) { tip.style.display = 'none'; return; }
  tip.textContent = mark.dataset.tip.split(' | ').join('\\n');
  tip.style.display = 'block';
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(e.clientX + 14, window.innerWidth - r.width - 8) + 'px';
  tip.style.top = Math.max(e.clientY - r.height - 12, 8) + 'px';
});
document.addEventListener('pointerleave', () => { tip.style.display = 'none'; });
"""


def page(filename: str, title: str, body: str, source: str) -> str:
    links = "".join(
        f'<a href="{href}"{" aria-current=" + chr(34) + "page" + chr(34) if href == filename else ""}>{name}</a>'
        for href, name in NAV
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Matchday+ analytics</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<nav>{links}<a class="repo" href="{REPO}">Repository</a></nav>
{body}
<p class="source">{source} Matchday+ is a fictional company and all data is synthetic (default dataset, seed 42).
These pages are generated by <code>reports/build.py</code> and rebuilt on every merge to <code>main</code>.</p>
</div>
<div id="tip" role="status"></div>
<script>{JS}</script>
</body>
</html>
"""


def tiles(items: list[tuple[str, str]]) -> str:
    return (
        '<div class="tiles">'
        + "".join(f'<div class="tile"><b>{escape(v)}</b><span>{escape(k)}</span></div>' for k, v in items)
        + "</div>"
    )


def figure(caption: str, chart: str, legend: str = "", table: str = "") -> str:
    details = f'<details><summary>Data table</summary><div class="scroll">{table}</div></details>' if table else ""
    return f"<figure><figcaption>{escape(caption)}</figcaption>{legend}{chart}</figure>{details}"


def table(headers: list[str], rows: list[list[str]], wide: bool = False) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table{' class=' + chr(34) + 'wide' + chr(34) if wide else ''}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
