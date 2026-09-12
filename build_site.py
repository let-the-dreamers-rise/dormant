"""Wrap the Artifact fragment into a standalone page for GitHub Pages.

`dormant/web/index.html` is authored as a fragment: the Artifact host injects
the doctype, head and body around it. GitHub Pages does not, so serving it
directly would render as text. This produces `docs/index.html`, which is the
same tool inside a real document, with a bar linking back to the source and the
funding proposal.

Generated, not edited. Change `dormant/web/index.html` and re-run.

    python build_site.py
"""

from pathlib import Path

SRC = Path("dormant/web/index.html")
OUT = Path("docs/index.html")
REPO = "https://github.com/let-the-dreamers-rise/dormant"

fragment = SRC.read_text(encoding="utf-8")
head, _, body = fragment.partition("</style>")

BAR = """
<style>
.sitebar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;
  max-width:1180px;margin:0 auto;padding:10px 20px 0;
  font:500 12px/1 var(--mono);color:var(--muted)}
.sitebar a{color:var(--muted);text-decoration:none;
  border-bottom:1px solid var(--line)}
.sitebar a:hover{color:var(--accent);border-color:var(--accent)}
.sitebar .sep{opacity:.4}
</style>
<nav class="sitebar">
  <a href="%(repo)s">source</a>
  <span class="sep">/</span>
  <a href="%(repo)s/blob/main/GRANT.md">funding proposal</a>
  <span class="sep">/</span>
  <a href="%(repo)s/blob/main/measurement/PARSING-GAP.md">the measurements</a>
  <span class="sep">/</span>
  <span>MIT, runs entirely in your browser</span>
</nav>
""" % {"repo": REPO}

doc = (
    "<!doctype html>\n"
    '<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    '<meta name="description" content="Paste an unsigned Solana transaction '
    'and read, offline and in your browser, exactly what signing it hands '
    'over.">\n'
    "<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}"
    "</style>\n"
    + head + "</style>\n"
    "</head>\n<body>\n"
    + BAR
    + body
    + "\n</body>\n</html>\n"
)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(doc, encoding="utf-8")
print("wrote %s (%d bytes)" % (OUT, len(doc)))
