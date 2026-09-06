"""Paste a transaction, get the condition.

    python -m dormant <base64-or-base58>
    echo <payload> | python -m dormant

No network. No wallet. No account.
"""

from __future__ import annotations

import sys

from .analyze import analyse, render


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    payload = args[0] if args else sys.stdin.read()
    if not payload.strip():
        print(__doc__)
        return 2
    try:
        print(render(analyse(payload)))
    except ValueError as exc:
        print("could not decode: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
