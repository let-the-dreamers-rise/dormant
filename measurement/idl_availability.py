"""How much of the parsing gap closes for free, using on-chain Anchor IDLs?

This experiment exists to attack `parsing_gap.py`'s headline.

That measurement says roughly four in ten mainnet instructions cannot be read
by the RPC's own parser. The strongest objection anyone can raise -- and the
strongest reason to decline funding semantics work -- is that the RPC's parser
is not the limit of what is *knowable*. Anchor programs can publish their IDL
to an account on chain. A developer willing to fetch and cache those reads a
great deal more than the RPC hands them, with a caching script rather than
hand-written semantics.

If most of the top programs publish an IDL, most of the gap is a caching
problem and the honest ask for semantics work is much smaller. If most do not,
the gap is real and semantics are the only way through.

Either answer is worth having and only one of them is comfortable, which is why
it is measured rather than argued.

WHAT AN IDL DOES AND DOES NOT GIVE YOU

An IDL names things: instruction `swap`, field `amount`, account `authority`.
That is genuinely useful and it is what the Foundation's Discriminator Database
RFP asked for. It is not a statement of effect. An IDL tells you an instruction
is called `set_authority` and takes an account called `new_authority`. It does
not tell you that this account never signs the transaction, and that control is
therefore leaving the room. A program with a perfect IDL still needs semantics
for the question this project asks.

So the honest picture is a three-level ladder, and this script measures the gap
between the first two rungs:

    LEVEL 0   the RPC names it                      free today
    LEVEL 1   an on-chain IDL names it              a caching script
    LEVEL 2   something states its effect on state  hand-written, expensive

HOW THE IDL ADDRESS IS DERIVED

Anchor stores a program's IDL at a deterministic address:

    base = find_program_address([], program_id)
    idl  = create_with_seed(base, "anchor:idl", program_id)

`create_with_seed` is a plain sha256. `find_program_address` needs an ed25519
on-curve test, implemented below in pure Python so this script keeps the same
property as every other measurement here: no dependencies, no API key, and
anyone can rerun it.

    python measurement/idl_availability.py
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request

RPC = "https://api.mainnet-beta.solana.com"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# ed25519 field and curve constants.
P = 2 ** 255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    raw = n.to_bytes(32, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw[pad:] if pad else raw


def b58encode(raw: bytes) -> str:
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * pad + out


def on_curve(b: bytes) -> bool:
    """Is this 32-byte value a valid ed25519 point?

    A program-derived address must NOT be, which is what makes it unforgeable:
    no private key can exist for it. Decompress y, solve for x^2, and test
    whether x^2 is a quadratic residue.
    """
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P:
        return False
    y2 = (y * y) % P
    num = (y2 - 1) % P
    den = (D * y2 + 1) % P
    if den == 0:
        return False
    x2 = (num * pow(den, P - 2, P)) % P
    if x2 == 0:
        return True
    # x2 is a square iff x2^((P-1)/2) == 1
    return pow(x2, (P - 1) // 2, P) == 1


def find_program_address(program_id: bytes) -> bytes:
    """Anchor's IDL base: find_program_address with an EMPTY seed list."""
    for bump in range(255, -1, -1):
        h = hashlib.sha256(
            bytes([bump]) + program_id + b"ProgramDerivedAddress").digest()
        if not on_curve(h):
            return h
    raise ValueError("no off-curve address found")


def create_with_seed(base: bytes, seed: str, owner: bytes) -> bytes:
    return hashlib.sha256(base + seed.encode() + owner).digest()


def idl_address(program: str) -> str:
    pid = b58decode(program)
    return b58encode(create_with_seed(find_program_address(pid),
                                      "anchor:idl", pid))


def rpc(method: str, params: list, tries: int = 4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                RPC, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                out = json.loads(r.read())
            if "error" in out:
                return None
            return out.get("result")
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def account_len(addr: str):
    """Byte length of an account's data, or None if it does not exist."""
    res = rpc("getAccountInfo", [addr, {"encoding": "base64"}])
    if not res or not res.get("value"):
        return None
    data = res["value"].get("data")
    if isinstance(data, list) and data:
        import base64
        return len(base64.b64decode(data[0]))
    return 0


def main() -> int:
    queue = json.load(open("measurement/parsing_gap.json",
                           encoding="utf-8"))["queue"][:25]
    total = sum(x["count"] for x in queue)

    print("Checking on-chain Anchor IDLs for the top 25 opaque programs.")
    print("An IDL NAMES instructions. It does not state their effect.\n")
    print("%-46s %8s %9s" % ("program", "ix", "IDL"))
    print("-" * 66)

    with_idl = n_with = 0
    rows = []
    for x in queue:
        addr = idl_address(x["program"])
        size = account_len(addr)
        has = size is not None
        n_with += has
        with_idl += x["count"] if has else 0
        rows.append({"program": x["program"], "count": x["count"],
                     "idl_address": addr, "idl_bytes": size})
        print("%-46s %8d %9s" % (x["program"], x["count"],
                                 ("%d B" % size) if has else "none"))

    print("-" * 66)
    print("programs publishing an on-chain IDL   %d of 25" % n_with)
    print("their share of top-25 instruction volume  %.1f%%"
          % (100 * with_idl / total))
    print("volume with NO on-chain IDL               %.1f%%"
          % (100 * (total - with_idl) / total))
    print()
    print("Reading: the first figure is how much of this gap a caching script")
    print("could NAME for free. The last is what nothing but hand-written")
    print("semantics can reach. Neither figure states effect on account state,")
    print("which is a separate and harder problem for all 25.")

    with open("measurement/idl_availability.json", "w", encoding="utf-8") as f:
        json.dump({"programs": rows, "with_idl": n_with,
                   "volume_with_idl_share": with_idl / total}, f, indent=1)
    print("\nwrote measurement/idl_availability.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
