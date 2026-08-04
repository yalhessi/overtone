"""Render a `Sketch` as a dependency graph, in the spirit of Lean's blueprints.

A blueprint answers, at a glance, the two questions a sketch is for: what does
this proof depend on, and how far along is it. Lean's `leanblueprint` colours
each node by whether its statement and proof are done and whether its
dependencies are; the same idea transfers directly, with our statuses drawn from
verification runs instead of from a human ticking items off.

Graphviz does the layout when it is installed -- its crossing minimisation is
worth far more than anything hand-rolled -- and `bootstrap.sh` puts it in an
isolated prefix because the base environment's Python pin conflicts with the
conda package. Where it is absent, a built-in layered renderer takes over: our
graphs are already topologically layered by `Sketch.layers()`, which is most of a
Sugiyama layout, leaving a barycentre pass and some SVG. Same statuses, same
palette, worse edge routing, no dependency.

Either way the SVG is self-contained and theme-aware, so it renders in an editor
preview, on GitHub, and in a browser without assets. Colour rides on CSS classes
rather than baked-in fills, which is what lets a graphviz-produced SVG still
respond to `prefers-color-scheme`.
"""
import json
import re
import shutil
import subprocess
from html import escape
from pathlib import Path

STATUS_ORDER = ("proved", "proved_scoped", "failed", "blocked", "pending")

# Fill / stroke / text, light and dark. Semantic, and deliberately not the
# accent hue: a reader should be able to tell state from shape and colour at
# once without a legend, and still be able to read it in either theme.
PALETTE = {
    "proved":        ("#dcefe6", "#0f7a52", "#0b3d2a", "#12301f", "#4fc38d", "#bfe8d2"),
    "proved_scoped": ("#f6ebd8", "#9a6206", "#4a2f05", "#2e2312", "#d9a441", "#f0dcb4"),
    "failed":        ("#f7e2df", "#b03a30", "#5a1a15", "#2e1715", "#e8776a", "#f5cdc7"),
    "blocked":       ("#e6e9f0", "#8d95a8", "#4d566b", "#171c26", "#4a5468", "#8b94a8"),
    "pending":       ("#eef0f5", "#b3bccd", "#5b6478", "#131822", "#39404f", "#7b8497"),
}
LABEL = {
    "proved": "proved from the axioms",
    "proved_scoped": "proved with its parents supplied",
    "failed": "attempted, unproven",
    "blocked": "blocked — a parent is unproven",
    "pending": "not attempted",
}

NODE_W, NODE_H, GAP_X, GAP_Y = 158, 46, 22, 74
PAD, LEGEND_H = 26, 74


def statuses(sketch, results):
    """Per-node status, best time, and how much scope that best run needed.

    `results` is the flat list `dag.verify` returns. A node is `proved` when it
    went through with nothing supplied and `proved_scoped` when it needed its
    parents -- a distinction worth showing, because it is the difference between
    a rung that stands alone and one that only exists inside the sketch.
    """
    out = {}
    for name in sketch.nodes:
        runs = [r for r in results if r["node"] == name]
        wins = [r for r in runs if r["proved"]]
        # A run with no concrete result is one still in flight -- the live
        # directory scan sees its input file before its outcome exists. Counting
        # that as a failure would paint a running node red.
        settled = [r for r in runs if r.get("result") not in (None, "?")]
        if wins:
            best = min(wins, key=lambda r: r["cpu"] if r["cpu"] is not None else 0)
            st = "proved_scoped" if best.get("n_support") else "proved"
            out[name] = {"status": st, "cpu": best["cpu"],
                         "direction": best["direction"],
                         "n_support": best.get("n_support", 0)}
        elif settled:
            cpus = [r["cpu"] for r in settled if r["cpu"] is not None]
            out[name] = {"status": "failed", "cpu": max(cpus) if cpus else None,
                         "direction": None, "n_support": 0}
        else:
            out[name] = {"status": "pending", "cpu": None, "direction": None,
                         "n_support": 0}
    # A node never attempted because a parent failed is blocked, not merely
    # pending; the distinction says whether the sketch or the schedule is at
    # fault.
    for name, (_, _, parents) in sketch.nodes.items():
        if out[name]["status"] == "pending" and any(
                out[p]["status"] not in ("proved", "proved_scoped")
                for p in parents):
            out[name]["status"] = "blocked"
    return out


def _positions(sketch):
    """Layer each node, then order within layers by parent barycentre."""
    layers = sketch.layers()
    order = {n: i for layer in layers for i, n in enumerate(layer)}
    for _ in range(4):                       # converges quickly at this size
        for depth, layer in enumerate(layers):
            if depth == 0:
                continue
            def bary(n):
                ps = sketch.nodes[n][2]
                return (sum(order[p] for p in ps) / len(ps)) if ps else order[n]
            layer.sort(key=lambda n: (bary(n), n))
            for i, n in enumerate(layer):
                order[n] = i
    width = max(len(l) for l in layers)
    span = width * NODE_W + (width - 1) * GAP_X
    pos = {}
    for depth, layer in enumerate(layers):
        w = len(layer) * NODE_W + (len(layer) - 1) * GAP_X
        x0 = PAD + (span - w) / 2
        for i, n in enumerate(layer):
            pos[n] = (x0 + i * (NODE_W + GAP_X), PAD + depth * (NODE_H + GAP_Y))
    return pos, layers, span


def _edge(x1, y1, x2, y2):
    dy = max(18, (y2 - y1) * 0.42)
    return f"M{x1:.1f},{y1:.1f} C{x1:.1f},{y1 + dy:.1f} {x2:.1f},{y2 - dy:.1f} {x2:.1f},{y2:.1f}"


def to_svg(sketch, results=(), *, title="", subtitle=""):
    st = statuses(sketch, results)
    pos, layers, span = _positions(sketch)
    head = 52 if title else 0
    W = span + 2 * PAD
    H = PAD + len(layers) * (NODE_H + GAP_Y) - GAP_Y + PAD + LEGEND_H + head

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'width="{W:.0f}" height="{H:.0f}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">']
    p.append("<style>"
             ".bg{fill:#f7f8fb}.ttl{fill:#181d29}.sub{fill:#7b849a}.ed{stroke:#b9c1d2}"
             "@media(prefers-color-scheme:dark){"
             ".bg{fill:#0d1017}.ttl{fill:#dde3ef}.sub{fill:#6d7690}.ed{stroke:#2f3747}"
             + "".join(
                 f".n-{k} rect{{fill:{v[3]};stroke:{v[4]}}}.n-{k} .t{{fill:{v[5]}}}"
                 for k, v in PALETTE.items())
             + "}"
             + "".join(
                 f".n-{k} rect{{fill:{v[0]};stroke:{v[1]}}}.n-{k} .t{{fill:{v[2]}}}"
                 for k, v in PALETTE.items())
             + "</style>")
    p.append(f'<rect class="bg" width="{W:.0f}" height="{H:.0f}"/>')

    y = PAD - 4
    if title:
        p.append(f'<text class="ttl" x="{PAD}" y="{y + 12}" font-size="15" '
                 f'font-weight="600">{escape(title)}</text>')
        if subtitle:
            p.append(f'<text class="sub" x="{PAD}" y="{y + 32}" font-size="11">'
                     f'{escape(subtitle)}</text>')

    p.append(f'<g transform="translate(0,{head})">')
    p.append('<g class="ed" fill="none" stroke-width="1.2">')
    for name, (_, _, parents) in sketch.nodes.items():
        cx, cy = pos[name]
        for parent in parents:
            px, py = pos[parent]
            dashed = ' stroke-dasharray="3 3"' if st[name]["status"] in (
                "blocked", "pending") else ""
            p.append(f'<path d="{_edge(px + NODE_W / 2, py + NODE_H, cx + NODE_W / 2, cy)}"'
                     f'{dashed}/>')
    p.append("</g>")

    for name, (lhs, rhs, parents) in sketch.nodes.items():
        x, y0 = pos[name]
        s = st[name]
        when = ("—" if s["cpu"] is None
                else f'{s["cpu"]:.1f}s' if s["status"].startswith("proved")
                else f'>{s["cpu"]:.0f}s')
        scope = f' · {s["n_support"]}p' if s["n_support"] else ""
        tip = (f'{name}\n{lhs} = {rhs}\n{LABEL[s["status"]]}'
               + (f'\n{s["direction"]} {when}' if s["direction"] else ""))
        p.append(f'<g class="n-{s["status"]}"><title>{escape(tip)}</title>'
                 f'<rect x="{x:.1f}" y="{y0:.1f}" width="{NODE_W}" height="{NODE_H}" '
                 f'rx="4" stroke-width="1.5"/>'
                 f'<text class="t" x="{x + 9:.1f}" y="{y0 + 19:.1f}" font-size="11" '
                 f'font-weight="600">{escape(name[:20])}</text>'
                 f'<text class="t" x="{x + 9:.1f}" y="{y0 + 35:.1f}" font-size="10" '
                 f'opacity=".8">{escape(when + scope)}</text></g>')
    p.append("</g>")

    ly = PAD + len(layers) * (NODE_H + GAP_Y) - GAP_Y + head + 26
    lx = PAD
    for k in STATUS_ORDER:
        n = sum(1 for v in st.values() if v["status"] == k)
        if not n:
            continue
        p.append(f'<g class="n-{k}"><rect x="{lx}" y="{ly - 9}" width="11" height="11" '
                 f'rx="2" stroke-width="1.2"/></g>'
                 f'<text class="sub" x="{lx + 17}" y="{ly}" font-size="10.5">'
                 f'{escape(LABEL[k])} ({n})</text>')
        lx += 20 + 6.05 * len(LABEL[k]) + 26
    p.append("</svg>")
    return "\n".join(p)


def _qualified(label: str) -> bool:
    """Does this TPTP label carry a caveat rather than a plain claim?

    "~NAME" marks a statement equivalent to that problem's conjecture but not
    identical to it; a parenthesised note marks a differing axiom set, where
    matching the conjecture is not solving the problem. Both must survive
    truncation.
    """
    return label.startswith("~") or "(" in label


def to_dot(sketch, results=(), *, title="", annot=None):
    """Graphviz source. Colour rides on `class`, not on baked-in attributes.

    Presentation attributes lose to any CSS rule, so emitting a class per node
    lets the stylesheet injected by `render` restyle the graph per theme while
    graphviz still does the layout.
    """
    st = statuses(sketch, results)
    annot = annot or {}
    esc = lambda s: str(s).replace('\\', '\\\\').replace('"', '\\"')
    out = ["digraph sketch {",
           '  bgcolor="transparent"; rankdir=TB; nodesep=0.28; ranksep=0.52;',
           '  node [shape=box style="rounded,filled" fontname="monospace" '
           'fontsize=10 margin="0.14,0.07" penwidth=1.4];',
           '  edge [color="#9aa3b5" penwidth=1.1 arrowsize=0.6];']
    if title:
        out.append(f'  labelloc=t; fontname="sans-serif" fontsize=13; '
                   f'label="{esc(title)}\\n";')
    for name, (lhs, rhs, _) in sketch.nodes.items():
        s = st[name]
        when = ("" if s["cpu"] is None
                else f'\\n{s["cpu"]:.1f}s' if s["status"].startswith("proved")
                else f'\\n>{s["cpu"]:.0f}s')
        scope = f' · {s["n_support"]}p' if s["n_support"] else ""
        tip = f'{lhs} = {rhs}  —  {LABEL[s["status"]]}'
        tptp = (annot.get(name) or {}).get("tptp") or []
        # TPTP identity is the most useful thing on a node: it says the
        # step is a benchmark problem, not merely an internal lemma.
        #
        # Truncating the list must never be what hides a warning. Anything
        # qualified -- a differing axiom set, an equivalent-but-not-identical
        # statement -- is always shown, and a silently dropped tail is counted
        # rather than omitted.
        shown = [t for t in tptp if _qualified(t)]
        for t in tptp:
            if t not in shown and len(shown) < 3:
                shown.append(t)
        shown.sort(key=tptp.index)
        rest = len(tptp) - len(shown)
        tag = ("\\n(" + ", ".join(shown)
               + (f", +{rest} more" if rest else "") + ")") if tptp else ""
        fill, line, text = PALETTE[s["status"]][:3]
        # Both the class and the concrete colours: the class lets the injected
        # stylesheet re-theme the SVG, and the attributes mean `dot -Tpng` on
        # the .dot alone still comes out coloured.
        out.append(f'  "{name}" [id="node-{name}" class="n-{s["status"]}" '
                   f'label="{name}{tag}{when}{scope}" '
                   f'fillcolor="{fill}" color="{line}" fontcolor="{text}" '
                   f'tooltip="{esc(tip)}"];')
    for name, (_, _, parents) in sketch.nodes.items():
        for p in parents:
            style = ' style=dashed' if st[name]["status"] in (
                "blocked", "pending") else ""
            out.append(f'  "{p}" -> "{name}" [id="edge-{p}__{name}" '
                       f'class="e-{st[name]["status"]}"{style}];')
    out.append("}")
    return "\n".join(out)


def _dot_binary():
    """`dot` from PATH, else the isolated prefix bootstrap.sh installs."""
    found = shutil.which("dot")
    if found:
        return found
    local = Path(__file__).resolve().parents[2] / "build" / "gv" / "bin" / "dot"
    return str(local) if local.exists() else None


_CSS = ("svg{background:#f7f8fb}text{fill:#181d29}"
        + "".join(f".n-{k}>polygon,.n-{k}>path{{fill:{v[0]};stroke:{v[1]}}}"
                  f".n-{k}>text{{fill:{v[2]}}}" for k, v in PALETTE.items())
        + "@media(prefers-color-scheme:dark){svg{background:#0d1017}"
          "text{fill:#dde3ef}g.edge>path{stroke:#39414f}"
          "g.edge>polygon{fill:#39414f;stroke:#39414f}"
        + "".join(f".n-{k}>polygon,.n-{k}>path{{fill:{v[3]};stroke:{v[4]}}}"
                  f".n-{k}>text{{fill:{v[5]}}}" for k, v in PALETTE.items())
        + "}")


def _legend_svg(sketch, results, width):
    st = statuses(sketch, results)
    parts, x = [], 14
    for k in STATUS_ORDER:
        n = sum(1 for v in st.values() if v["status"] == k)
        if not n:
            continue
        parts.append(
            f'<g class="n-{k}"><polygon points="{x},0 {x + 11},0 {x + 11},11 {x},11" '
            f'stroke-width="1.4"/></g>'
            f'<text x="{x + 17}" y="9.5" font-size="10.5" opacity=".75" '
            f'font-family="ui-monospace,Menlo,monospace">{escape(LABEL[k])} ({n})</text>')
        x += 24 + 6.1 * len(LABEL[k]) + 24
    return "".join(parts), x


def render(sketch, dest, results=(), *, title="", subtitle="",
           engine="auto", annot=None):
    """Write `dest` (.svg) plus a sibling .dot. Returns the svg path.

    `engine="dot"` uses graphviz, which minimises edge crossings properly;
    `"builtin"` uses the dependency-free layered renderer; `"auto"` prefers dot
    when it is installed. Both outputs are self-contained and theme-aware.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dot_src = to_dot(sketch, results, title=title, annot=annot)
    dest.with_suffix(".dot").write_text(dot_src + "\n")

    binary = _dot_binary() if engine in ("auto", "dot") else None
    if engine == "dot" and not binary:
        raise RuntimeError("engine='dot' but no graphviz `dot` on PATH")
    if not binary:
        dest.write_text(to_svg(sketch, results, title=title, subtitle=subtitle))
        return dest

    svg = subprocess.run([binary, "-Tsvg"], input=dot_src, capture_output=True,
                         text=True, check=True).stdout
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    m = re.search(r'<svg width="(\d+)pt" height="(\d+)pt"', svg)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (900, 600)

    legend, lw = _legend_svg(sketch, results, w)
    band = 34 if legend else 0
    sub = (f'<text x="14" y="{h + 15}" font-size="11" opacity=".6" '
           f'font-family="ui-monospace,Menlo,monospace">{escape(subtitle)}</text>'
           ) if subtitle else ""
    if sub:
        band += 22
    svg = svg.replace('<svg width="%dpt" height="%dpt"' % (w, h),
                      '<svg width="%d" height="%d"' % (max(w, lw + 20), h + band), 1)
    # graphviz writes "0.00 0.00 W H", so the zeros need the decimal form too.
    svg = re.sub(r'viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"',
                 lambda g: f'viewBox="0 0 {max(float(g.group(1)), lw + 20):.0f} '
                           f'{float(g.group(2)) + band:.0f}"', svg, count=1)
    svg = svg.replace("<svg ", '<svg style="max-width:100%;height:auto" ', 1)
    # Inject after the <svg> element's own closing bracket -- replacing the
    # first ">" in the document would land it inside the XML declaration.
    svg = re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + f"<style>{_CSS}</style>",
                 svg, count=1)
    svg = svg.replace("</svg>",
                      f'{sub}<g transform="translate(0,{h + (22 if sub else 0) + 6})">'
                      f'{legend}</g></svg>')
    dest.write_text(svg)
    return dest


# ---------------------------------------------------------------- interactive

def _raw_dot_svg(dot_src):
    binary = _dot_binary()
    if not binary:
        raise RuntimeError("interactive blueprints need graphviz; see bootstrap.sh")
    svg = subprocess.run([binary, "-Tsvg"], input=dot_src, capture_output=True,
                         text=True, check=True).stdout
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = svg[svg.find("<svg"):]
    # graphviz writes the node name into a <title>, which browsers render as a
    # native tooltip and would race our own.
    svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)
    # Drop the pt dimensions so the viewBox drives size. Note this can leave
    # "<svg\n", so the page selects the element by position rather than by an id
    # patched in here -- string surgery on the tag is what broke last time.
    return re.sub(r'(<svg\b[^>]*?)\swidth="\d+pt"\s+height="\d+pt"', r"\1", svg,
                  count=1)


def to_html(sketch, results=(), details=None, *, title="Sketch blueprint",
            subtitle="", annot=None, timeline=None):
    """A self-contained page: the graph, plus what each node means and its proof.

    Hovering a node lights its ancestors and descendants, which is the question
    a dependency graph exists to answer and the one a static image answers
    worst. Clicking opens the node's statement, its per-direction runs, and the
    proof twee actually found -- `proofs.proof_section`, so a 655 KB search
    trace arrives as the 15 KB that is worth reading.

    `timeline` is a list of `{label, sketch, results, note}`, oldest first, and
    turns the page into a scrubber over a sketch's revisions. The two things
    worth seeing about a sketch are where it ended and how it got there -- and
    parent edits are the most valuable and least visible of those: correcting
    one took `left_moufang_a` from a 300s timeout to 1.0s, which is a single
    line in a diff and invisible in a picture. No timeline means a one-step
    trajectory, so there is one code path rather than two.
    """
    from overtone.agent.dag import diff

    details, annot = details or {}, annot or {}
    steps = list(timeline or []) or [{"label": "current", "sketch": sketch,
                                      "results": results, "note": ""}]

    def node_data(sk, res, with_details):
        st = statuses(sk, res)
        kids = {n: [] for n in sk.nodes}
        for n, (_, _, ps) in sk.nodes.items():
            for q in ps:
                kids[q].append(n)
        out = {}
        for n, (lhs, rhs, parents) in sk.nodes.items():
            d = details.get(n, {}) if with_details else {}
            out[n] = {"lhs": lhs, "rhs": rhs, "parents": list(parents),
                      "children": sorted(kids[n]), "status": st[n]["status"],
                      "label": LABEL[st[n]["status"]], "cpu": st[n]["cpu"],
                      "runs": d.get("runs", []), "proof": d.get("proof", ""),
                      "goal": d.get("goal", ""),
                      "tptp": (annot.get(n) or {}).get("tptp", []),
                      "note": (annot.get(n) or {}).get("note", "")}
        return out, st

    svgs, meta, prev = [], [], None
    for i, step in enumerate(steps):
        sk, res = step["sketch"], step.get("results", ())
        nodes, st = node_data(sk, res, with_details=(i == len(steps) - 1))
        d = (diff(prev, sk) if prev is not None
             else {"added": [], "removed": [], "restated": [], "reparented": [],
                   "n_edits": 0})
        touched = sorted({*d["added"], *(x["node"] for x in d["restated"]),
                          *(x["node"] for x in d["reparented"])})
        svgs.append('<div class="step" data-i="%d">%s</div>'
                    % (i, _raw_dot_svg(to_dot(sk, res, title="", annot=annot))))
        meta.append({"label": step.get("label", "step %d" % i),
                     "note": step.get("note", ""), "nodes": nodes, "diff": d,
                     "touched": touched,
                     "counts": {k: sum(1 for v in st.values() if v["status"] == k)
                                for k in STATUS_ORDER}})
        prev = sk

    counts = meta[-1]["counts"]
    swatches = "".join(
        f'<button class="key n-{k}" data-status="{k}"><i></i>{escape(LABEL[k])}'
        f' <b>{counts[k]}</b></button>' for k in STATUS_ORDER if counts[k])

    css = _HTML_CSS + "".join(
        f".n-{k} > polygon,.n-{k} > path{{fill:{v[0]};stroke:{v[1]}}}"
        f".n-{k} > text{{fill:{v[2]}}}.key.n-{k} i{{background:{v[0]};border-color:{v[1]}}}"
        f".pill.n-{k}{{background:{v[0]};color:{v[2]};border-color:{v[1]}}}"
        for k, v in PALETTE.items()) + "@media(prefers-color-scheme:dark){" + "".join(
        f".n-{k} > polygon,.n-{k} > path{{fill:{v[3]};stroke:{v[4]}}}"
        f".n-{k} > text{{fill:{v[5]}}}.key.n-{k} i{{background:{v[3]};border-color:{v[4]}}}"
        f".pill.n-{k}{{background:{v[3]};color:{v[5]};border-color:{v[4]}}}"
        for k, v in PALETTE.items()) + "}"

    bar = ""
    if len(steps) > 1:
        chips = "".join(
            '<button class="stepchip" data-i="{i}">{label}<span>{n} {what}</span>'
            "</button>".format(
                i=i, label=escape(m["label"]),
                n=(m["diff"]["n_edits"] if i else len(m["nodes"])),
                what=("edits" if i else "nodes"))
            for i, m in enumerate(meta))
        bar = ('<div class="timeline"><button class="nav" id="prev">&#8592;</button>'
               f'<div class="chips">{chips}</div>'
               '<button class="nav" id="next">&#8594;</button></div>')

    return (f"<title>{escape(title)}</title><style>{css}</style>"
            f'<div class="shell"><header><div>'
            f'<div class="eyebrow">sketch blueprint</div>'
            f"<h1>{escape(title)}</h1>"
            f'<p class="sub" id="sub">{escape(subtitle)}</p></div>'
            f'<div class="keys">{swatches}</div></header>'
            f"{bar}"
            f'<div class="body"><div class="canvas" id="canvas">{"".join(svgs)}</div>'
            f'<aside id="panel"><div class="empty">Hover a node to trace its '
            f"dependencies. Click one for its statement and proof.</div></aside>"
            f'</div></div><div id="tip"></div>'
            f"<script>const STEPS={json.dumps(meta)};"
            f"const SUB={json.dumps(subtitle)};{_HTML_JS}</script>")


_HTML_CSS = """
:root{--bg:#eef0f5;--panel:#f7f8fb;--sunk:#e3e7ef;--ink:#181d29;--soft:#4d566b;
  --faint:#7b849a;--line:#cfd5e2;--accent:#2f4fd8;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;}
@media(prefers-color-scheme:dark){:root{--bg:#0d1017;--panel:#141924;--sunk:#0a0d13;
  --ink:#dde3ef;--soft:#9aa4bb;--faint:#6d7690;--line:#272e3d;--accent:#8ea3ff;}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;}
.shell{display:flex;flex-direction:column;height:100vh;}
header{display:flex;gap:20px;justify-content:space-between;align-items:flex-end;
  flex-wrap:wrap;padding:16px 20px 13px;border-bottom:1px solid var(--line);}
.eyebrow{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--faint);font-weight:650;}
h1{margin:4px 0 0;font-size:20px;font-weight:600;letter-spacing:-.01em;}
.sub{margin:3px 0 0;font-size:12px;color:var(--faint);font-family:var(--mono);}
.keys{display:flex;flex-wrap:wrap;gap:7px;}
.key{display:flex;align-items:center;gap:6px;font:inherit;font-size:11.5px;
  color:var(--soft);background:transparent;border:1px solid transparent;
  border-radius:5px;padding:4px 8px;cursor:pointer;}
.key:hover{border-color:var(--line);}
.key.off{opacity:.4;}
.key i{width:11px;height:11px;border-radius:3px;border:1.4px solid;display:block;}
.key b{font-variant-numeric:tabular-nums;color:var(--ink);}
.body{display:flex;flex:1;min-height:0;}
.canvas{flex:1;overflow:auto;padding:18px;min-width:0;}
#canvas svg{max-width:none;}
#canvas svg g.node{cursor:pointer;}
#canvas svg g.node>polygon,#canvas svg g.node>text,#canvas svg g.edge{transition:opacity .12s;}
#canvas svg .dim{opacity:.11;}
#canvas svg g.sel>polygon{stroke-width:3.4;}
#canvas svg g.lit>polygon{stroke-width:2.4;}
aside{width:392px;flex:none;border-left:1px solid var(--line);background:var(--panel);
  overflow:auto;padding:18px 20px 40px;}
.empty{color:var(--faint);font-size:13px;line-height:1.6;}
.pname{font-family:var(--mono);font-size:16px;font-weight:650;overflow-wrap:anywhere;}
.pill{display:inline-block;border:1px solid;border-radius:99px;padding:2px 9px;
  font-size:11px;font-weight:600;margin-top:7px;}
h4{margin:20px 0 7px;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--faint);font-weight:650;}
.eq{font-family:var(--mono);font-size:12.5px;line-height:1.65;background:var(--sunk);
  border:1px solid var(--line);border-radius:5px;padding:9px 11px;overflow-wrap:anywhere;}
.chips{display:flex;flex-wrap:wrap;gap:5px;}
.chip{font-family:var(--mono);font-size:11.5px;padding:3px 8px;border-radius:4px;
  border:1px solid var(--line);background:var(--bg);color:var(--soft);cursor:pointer;}
.chip:hover{border-color:var(--accent);color:var(--accent);}
.none{font-size:12px;color:var(--faint);font-style:italic;}
.tptp{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px;}
.tptp span{font-family:var(--mono);font-size:11px;padding:2px 7px;border-radius:4px;border:1px solid var(--accent);color:var(--accent);}
.note{margin-top:9px;font-size:12px;line-height:1.5;color:var(--soft);border-left:2px solid var(--line);padding-left:9px;}
table{border-collapse:collapse;width:100%;font-size:12px;}
td,th{padding:4px 8px;text-align:left;border-bottom:1px solid var(--line);}
th{font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);}
td.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums;}
pre{margin:0;font-family:var(--mono);font-size:11.5px;line-height:1.55;
  background:var(--sunk);border:1px solid var(--line);border-radius:5px;
  padding:11px;overflow:auto;max-height:46vh;white-space:pre;}
#tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--panel);border:1px solid var(--line);border-radius:6px;
  padding:7px 10px;font-family:var(--mono);font-size:11.5px;max-width:430px;
  box-shadow:0 6px 22px rgba(0,0,0,.17);z-index:9;}
#tip.on{opacity:1;}
#tip b{display:block;margin-bottom:3px;}
#tip span{color:var(--faint);}
.timeline{display:flex;align-items:center;gap:8px;padding:9px 20px;
  border-bottom:1px solid var(--line);background:var(--panel);}
.chips{display:flex;gap:6px;overflow-x:auto;flex:1;}
.stepchip{flex:none;display:flex;flex-direction:column;gap:1px;align-items:flex-start;
  font:inherit;font-size:11.5px;color:var(--soft);background:var(--bg);
  border:1px solid var(--line);border-radius:5px;padding:5px 10px;cursor:pointer;
  font-family:var(--mono);white-space:nowrap;}
.stepchip:hover{border-color:var(--accent);}
.stepchip.on{border-color:var(--accent);color:var(--accent);}
.stepchip span{font-size:10px;opacity:.6;}
.nav{font:inherit;font-size:14px;color:var(--soft);background:var(--bg);
  border:1px solid var(--line);border-radius:5px;padding:3px 9px;cursor:pointer;}
.nav:disabled{opacity:.3;cursor:default;}
.step{display:none;} .step.on{display:block;}
#canvas svg g.changed>polygon{stroke-width:3.4;stroke-dasharray:5 3;}
.diff{border-bottom:1px solid var(--line);padding-bottom:13px;margin-bottom:6px;}
.diff h5{margin:0 0 6px;font-size:10.5px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--faint);font-weight:650;}
.edit{display:flex;gap:8px;font-size:12px;padding:3px 0;align-items:baseline;}
.edit i{font-style:normal;font-family:var(--mono);font-size:10px;font-weight:700;
  padding:1px 5px;border-radius:3px;flex:none;}
.edit code{font-size:11.5px;overflow-wrap:anywhere;}
.edit.add i{background:#dcefe6;color:#0f7a52;}
.edit.rm  i{background:#f7e2df;color:#b03a30;}
.edit.re  i{background:#f6ebd8;color:#9a6206;}
.edit.par i{background:#e2e7fb;color:#2f4fd8;}
@media(prefers-color-scheme:dark){
  .edit.add i{background:#0f2b20;color:#4fc38d;}
  .edit.rm  i{background:#2e1715;color:#e8776a;}
  .edit.re  i{background:#2e2312;color:#d9a441;}
  .edit.par i{background:#1b2444;color:#8ea3ff;}}
@media(max-width:860px){.body{flex-direction:column;}
  aside{width:auto;border-left:0;border-top:1px solid var(--line);max-height:52vh;}}
"""

_HTML_JS = r"""
let cur=STEPS.length-1, D=STEPS[cur].nodes, g=null;
const panel=document.getElementById('panel'), tip=document.getElementById('tip');
const EMPTY='<div class="empty">Hover a node to trace its dependencies. '
          +'Click one for its statement and proof.</div>';
const up=n=>{const s=new Set(),q=[n];while(q.length){const c=q.pop();
  for(const p of D[c].parents)if(!s.has(p)){s.add(p);q.push(p);}}return s;};
const down=n=>{const s=new Set(),q=[n];while(q.length){const c=q.pop();
  for(const k of D[c].children)if(!s.has(k)){s.add(k);q.push(k);}}return s;};
const el=n=>document.getElementById('node-'+n);
let selected=null,muted=new Set();

function clearFx(){g.querySelectorAll('.dim,.lit,.sel').forEach(e=>
  e.classList.remove('dim','lit','sel'));}

function light(n,sel){
  clearFx();
  const keep=new Set([n,...up(n),...down(n)]);
  for(const k in D){const e=el(k);if(!e)continue;
    if(keep.has(k)){e.classList.add(k===n?'sel':'lit');}else{e.classList.add('dim');}}
  g.querySelectorAll('g.edge').forEach(e=>{
    const m=(e.id||'').slice(5).split('__');
    if(!(m.length===2&&keep.has(m[0])&&keep.has(m[1])))e.classList.add('dim');});
  if(sel)selected=n;
}

function restore(){
  clearFx();
  if(selected){light(selected,false);return;}
  if(muted.size)for(const k in D)
    if(muted.has(D[k].status))el(k)?.classList.add('dim');
}

const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const chips=(a)=>a.length?`<div class="chips">${a.map(x=>
  `<button class="chip" data-go="${x}">${esc(x)}</button>`).join('')}</div>`
  :'<div class="none">none</div>';

function show(n){
  const d=D[n];
  const runs=d.runs.length?`<h4>runs</h4><table><tr><th>direction</th><th>result</th>
    <th style="text-align:right">cpu</th></tr>${d.runs.map(r=>
    `<tr><td>${esc(r.direction)}</td><td>${esc(r.result)}</td>
     <td class="n">${r.cpu==null?'—':r.cpu.toFixed(1)+'s'}</td></tr>`).join('')}</table>`:'';
  const tptp=(d.tptp&&d.tptp.length)
    ?`<div class="tptp">${d.tptp.map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:'';
  panel.innerHTML=`<div class="pname">${esc(n)}</div>
    <span class="pill n-${d.status}">${esc(d.label)}</span>${tptp}
    ${d.note?`<div class="note">${esc(d.note)}</div>`:''}
    <h4>statement</h4><div class="eq">${esc(d.lhs)}<br>= ${esc(d.rhs)}</div>
    ${d.goal?`<h4>as sent to twee</h4><div class="eq">${esc(d.goal)}</div>`:''}
    <h4>depends on</h4>${chips(d.parents)}
    <h4>needed by</h4>${chips(d.children)}
    ${runs}
    <h4>proof</h4>${d.proof?`<pre>${esc(d.proof)}</pre>`
      :'<div class="none">no proof found yet</div>'}`;
  panel.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>{
    const t=b.dataset.go;light(t,true);show(t);
    el(t)?.scrollIntoView({behavior:'smooth',block:'center',inline:'center'});});
}

function bindGraph(){
g.querySelectorAll('g.node').forEach(node=>{
  const n=(node.id||'').slice(5); if(!D[n])return;
  node.addEventListener('mouseenter',e=>{
    if(!selected)light(n,false);
    const d=D[n];
    tip.innerHTML=`<b>${esc(n)}${d.tptp&&d.tptp.length?'  ('+esc(d.tptp.join(', '))+')':''}</b>${esc(d.lhs)} = ${esc(d.rhs)}
      <span><br>${esc(d.label)}${d.cpu!=null?' · '+d.cpu.toFixed(1)+'s':''}
      · ${d.parents.length} parent(s), ${d.children.length} dependent(s)</span>`;
    tip.classList.add('on');});
  node.addEventListener('mousemove',e=>{
    const r=tip.getBoundingClientRect();
    tip.style.left=Math.min(e.clientX+14,innerWidth-r.width-12)+'px';
    tip.style.top=Math.min(e.clientY+16,innerHeight-r.height-12)+'px';});
  node.addEventListener('mouseleave',()=>{tip.classList.remove('on');
    if(!selected)restore();});
  node.addEventListener('click',ev=>{ev.stopPropagation();light(n,true);show(n);});
});
}

document.querySelectorAll('.key').forEach(k=>k.onclick=()=>{
  const s=k.dataset.status;
  muted.has(s)?muted.delete(s):muted.add(s);
  k.classList.toggle('off',muted.has(s));
  selected=null;restore();});

function resetPanel(){panel.innerHTML=renderDiff(STEPS[cur])+EMPTY;}
document.getElementById('canvas').addEventListener('click',()=>{
  selected=null;resetPanel();restore();});

// The trajectory. What a sketch ended as, and how it got there -- parent edits
// being the most valuable and least visible kind: one of them was a 300s
// timeout against 1.0s, which is one line of diff and nothing in a picture.
const KINDS=[['added','add','+'],['removed','rm','\u2212'],
             ['restated','re','~'],['reparented','par','\u21c4']];
function renderDiff(m){
  if(cur===0||!m.diff) return '';
  const rows=[];
  for(const [key,cls,mark] of KINDS) for(const e of (m.diff[key]||[])){
    if(key==='added'||key==='removed')
      rows.push(`<div class="edit ${cls}"><i>${mark}</i><code>${esc(e)}</code></div>`);
    else if(key==='restated')
      rows.push(`<div class="edit ${cls}"><i>${mark}</i><div><code>${esc(e.node)}</code>`
        +`<br><code style="opacity:.55">${esc(e.before)}</code>`
        +`<br><code>${esc(e.after)}</code></div></div>`);
    else
      rows.push(`<div class="edit ${cls}"><i>${mark}</i><div><code>${esc(e.node)}</code>`
        +(e.gained.length?`<br>+ <code>${esc(e.gained.join(', '))}</code>`:'')
        +(e.lost.length?`<br>\u2212 <code>${esc(e.lost.join(', '))}</code>`:'')
        +'</div></div>');
  }
  if(!rows.length) rows.push('<div class="none">no structural change</div>');
  return `<div class="diff"><h5>edits in this step</h5>${rows.join('')}</div>`;
}

function showStep(i){
  cur=Math.max(0,Math.min(STEPS.length-1,i));
  const m=STEPS[cur];
  document.querySelectorAll('.step').forEach(x=>
    x.classList.toggle('on',+x.dataset.i===cur));
  document.querySelectorAll('.stepchip').forEach(c=>
    c.classList.toggle('on',+c.dataset.i===cur));
  const pv=document.getElementById('prev'), nx=document.getElementById('next');
  if(pv) pv.disabled=cur===0;
  if(nx) nx.disabled=cur===STEPS.length-1;
  const sub=document.getElementById('sub');
  if(sub&&STEPS.length>1) sub.textContent=m.note||SUB;
  D=m.nodes; selected=null; muted=new Set();
  g=document.querySelector('.step.on svg');
  bindGraph();
  for(const name of (m.touched||[])) el(name)?.classList.add('changed');
  resetPanel();
}

document.querySelectorAll('.stepchip').forEach(c=>c.onclick=()=>showStep(+c.dataset.i));
document.getElementById('prev')?.addEventListener('click',()=>showStep(cur-1));
document.getElementById('next')?.addEventListener('click',()=>showStep(cur+1));
addEventListener('keydown',e=>{
  if(e.key==='Escape'){selected=null;resetPanel();restore();}
  if(e.key==='ArrowLeft')showStep(cur-1);
  if(e.key==='ArrowRight')showStep(cur+1);});
showStep(STEPS.length-1);
"""


def details_from(sketch, outdir: Path, results):
    """Per-node goal clause and proof, read from a run directory.

    Lives here rather than in the CLI because the pipelines write their own
    blueprints now, and the interesting half of a blueprint is the proof behind
    each node. `proofs.proof_section` is what makes it affordable: one node's run
    file is 655 KB of search trace and 15 KB of proof.
    """
    from overtone import proofs
    outdir = Path(outdir)
    out = {}
    for name in sketch.nodes:
        runs = sorted((r for r in results if r["node"] == name),
                      key=lambda r: r["direction"])
        proof, goal = "", ""
        best = min((r for r in runs if r.get("proved")),
                   key=lambda r: r["cpu"] if r.get("cpu") is not None else 0,
                   default=None)
        if best:
            # The row carries its artifact path. Reconstructing a filename from
            # node and direction is what let a retry's output be mistaken for the
            # parented run's, and identity-addressed names cannot be guessed.
            f = Path(best.get("output") or
                     outdir / f"{name}.{best['direction'][2:]}.out")
            if f.exists():
                text = f.read_text(errors="replace")
                proof = proofs.proof_section(text)
                for line in text.splitlines():
                    if line.strip().startswith("Goal 1"):
                        goal = line.strip()
                        break
        out[name] = {"runs": runs, "proof": proof, "goal": goal}
    return out


def write_for_run(sketch, results, dest_dir: Path, *, title, subtitle="",
                  run_dir=None, annot=None, timeline=None, quiet=False):
    """Write `blueprint.svg` and `blueprint.html` for a finished run.

    Never raises. A run that cost CPU-hours must not lose its result because
    graphviz is missing or a label is malformed, so a rendering failure is
    reported and swallowed. Returns the paths written, which may be empty.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        details = details_from(sketch, run_dir or dest_dir, results)
        svg = render(sketch, dest_dir / "blueprint.svg", results, title=title,
                     subtitle=subtitle, annot=annot)
        written.append(svg)
        html = dest_dir / "blueprint.html"
        html.write_text(to_html(sketch, results, details, title=title,
                                subtitle=subtitle, annot=annot,
                                timeline=timeline))
        written.append(html)
        if not quiet:
            print(f"  blueprint -> {html}", flush=True)
    except Exception as e:                                        # noqa: BLE001
        print(f"  blueprint skipped ({type(e).__name__}: {e})", flush=True)
    return written


def write_index(roots, dest: Path, *, title="Overtone runs"):
    """One page linking every run's blueprint, newest first.

    The point is to compare problems side by side: a run directory per problem
    is only browsable if something enumerates them.
    """
    import datetime
    rows = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for html in sorted(root.glob("*/blueprint.html")):
            run = html.parent
            meta = {}
            for name in ("problem.json", "theory.json", "loop.json"):
                f = run / name
                if f.exists():
                    try:
                        meta = json.loads(f.read_text())
                    except json.JSONDecodeError:
                        meta = {}
                    meta["_kind"] = name.removesuffix(".json")
                    break
            rows.append((html.stat().st_mtime, run, html, meta))
    rows.sort(key=lambda r: -r[0])

    def _run_name(m, run):
        # A theory run's `host` is the problem its library was proved from, not
        # what the run is about -- showing it makes a family run look identical
        # to a single-problem run over the same host.
        if m.get("_kind") == "theory":
            return run.name
        return m.get("problem") or run.name

    def cell(m):
        if m.get("_kind") == "theory":
            lib = m.get("library", {})
            return (f"{m.get('n_proved', '?')}/{m.get('n_targets', '?')} targets",
                    f"library {lib.get('n_proved','?')}/{lib.get('n_nodes','?')}, "
                    f"{(lib.get('cost') or {}).get('cpu', 0):.0f}s")
        if m.get("_kind") == "loop":
            return (("proved" if m.get("proved") else "not proved"),
                    f"{m.get('iterations','?')} iteration(s), "
                    f"{m.get('cpu_total',0):.0f}s")
        c = m.get("cost") or {}
        return (("proved" if m.get("proved") else "not proved"),
                f"{m.get('n_proved','?')}/{m.get('n_nodes','?')} nodes, "
                f"{c.get('cpu',0):.0f}s over {c.get('n_runs','?')} runs")

    items = "".join(
        f'<a class="run" href="{html.relative_to(Path(dest).parent) if Path(dest).parent in html.parents else html}">'
        f'<b>{escape(_run_name(meta, run))}</b>'
        f'<span class="k">{escape(meta.get("_kind", run.parent.name))}</span>'
        f'<span class="s">{escape(cell(meta)[0])}</span>'
        f'<span class="d">{escape(cell(meta)[1])}</span>'
        f'<span class="t">{datetime.datetime.fromtimestamp(mt):%Y-%m-%d %H:%M}</span>'
        f"</a>"
        for mt, run, html, meta in rows)
    if not items:
        items = '<p class="none">No runs with blueprints yet.</p>'

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        f"<title>{escape(title)}</title><style>{_INDEX_CSS}</style>"
        f'<div class="wrap"><h1>{escape(title)}</h1>'
        f'<p class="sub">{len(rows)} run(s). Newest first.</p>'
        f'<div class="runs">{items}</div></div>')
    return dest


_INDEX_CSS = """
:root{--bg:#eef0f5;--card:#f7f8fb;--ink:#181d29;--soft:#4d566b;--faint:#7b849a;
  --line:#cfd5e2;--accent:#2f4fd8;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;}
@media(prefers-color-scheme:dark){:root{--bg:#0d1017;--card:#141924;--ink:#dde3ef;
  --soft:#9aa4bb;--faint:#6d7690;--line:#272e3d;--accent:#8ea3ff;}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);}
.wrap{max-width:920px;margin:0 auto;padding:38px 22px 60px;}
h1{font-size:24px;font-weight:600;margin:0;}
.sub{color:var(--faint);font-size:13px;margin:5px 0 22px;}
.runs{display:flex;flex-direction:column;gap:7px;}
.run{display:grid;grid-template-columns:minmax(120px,1fr) 74px 100px 1fr 120px;
  gap:12px;align-items:baseline;padding:11px 14px;background:var(--card);
  border:1px solid var(--line);border-radius:6px;text-decoration:none;
  color:inherit;font-size:13px;}
.run:hover{border-color:var(--accent);}
.run b{font-family:var(--mono);font-size:13.5px;}
.run .k{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);font-weight:650;}
.run .s{font-family:var(--mono);font-size:12px;}
.run .d,.run .t{color:var(--soft);font-size:12px;font-family:var(--mono);}
.run .t{text-align:right;color:var(--faint);}
.none{color:var(--faint);font-size:13px;}
@media(max-width:700px){.run{grid-template-columns:1fr;gap:3px;}
  .run .t{text-align:left;}}
"""
