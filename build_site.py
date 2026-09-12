"""Compose the public site from the landing page and the tool fragment.

`dormant/web/index.html` is authored as an Artifact fragment: the host injects
the doctype, head and body, so the page is only the tool. A reviewer needs more
than a paste box, but the tool has to stay live on the page -- a screenshot of a
decoder proves nothing. So this lifts the working parts out of the fragment
(its CSS, its input rail and verdict panel, its script) and sets them inside
`site/page.html`, which carries the argument around them.

One source of truth for the tool, one for the prose, one generated artefact.

    python build_site.py
"""

from pathlib import Path

FRAGMENT = Path("dormant/web/index.html")
PAGE = Path("site/page.html")
OUT = Path("docs/index.html")

fragment = FRAGMENT.read_text(encoding="utf-8")

css = fragment.partition("<style>")[2].partition("</style>")[0]

# Only the working part: the input rail and the verdict panel. The fragment's
# own masthead and footer are replaced by the page's.
after_cols = fragment.partition('<div class="cols">')[2]
demo = '<div class="cols">' + after_cols.partition("<footer>")[0].rstrip()

js = "<script>" + fragment.partition("<script>")[2].rstrip()

if not (css and demo and js):
    raise SystemExit("could not split %s into css/markup/script" % FRAGMENT)

page = PAGE.read_text(encoding="utf-8")
for marker, value in (("/*TOOL_CSS*/", css),
                      ("<!--TOOL_DEMO-->", demo),
                      ("<!--TOOL_JS-->", js)):
    if marker not in page:
        raise SystemExit("marker missing from %s: %s" % (PAGE, marker))
    page = page.replace(marker, value, 1)

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(page, encoding="utf-8")
print("wrote %s (%d bytes)" % (OUT, len(page)))
