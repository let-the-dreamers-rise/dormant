"""M1, the kill experiment: is the declared account set enough to determine
what a Solana instruction does?

Dormant's premise is that a transaction's effect can be characterised without
knowing full chain state, because Solana transactions name every account they
touch up front. If that premise is false -- if the same program, the same
instruction and the same account roles produce wildly different effects -- then
preconditions are not computable and the idea dies here, cheaply.

METHOD, and the one honesty constraint that shapes it

A transaction may carry several instructions, and the balance deltas recorded
by the RPC are per TRANSACTION, not per instruction. Attributing a delta to one
instruction inside a multi-instruction transaction is guesswork. So this only
considers transactions carrying exactly ONE state-affecting instruction, after
dropping ComputeBudget instructions, which change no account state. For those,
the transaction delta IS the instruction's effect, with nothing to attribute.

That throws away most of the corpus. It is the right trade: a smaller honest
sample beats a larger one built on an assumption.

WHAT COUNTS AS THE OUTCOME

Not the values -- the SHAPE. For each account the instruction declares, in
order, whether its lamports rose, fell or held, and the same for its token
balance. A precondition predicts shape; exact amounts depend on state by
definition and are not the question.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# State changes nothing, so these are dropped before deciding whether a
# transaction is single-instruction.
NOOP_PROGRAMS = {
    "ComputeBudget111111111111111111111111111111",
}


def b58_prefix(data: str, nbytes: int = 8) -> str:
    """First bytes of an instruction's data, hex, as a discriminator.

    Anchor puts an 8-byte discriminator here; SPL Token uses one byte. Taking
    eight and letting shorter payloads be shorter distinguishes both without
    needing to know which framework a program used.
    """
    if not data:
        return ""
    num = 0
    for ch in data:
        idx = B58.find(ch)
        if idx < 0:
            return "?"
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8 or 1, "big")
    pad = len(data) - len(data.lstrip("1"))
    raw = b"\x00" * pad + raw
    return raw[:nbytes].hex()


def instruction_key(ix: dict) -> tuple:
    """(program, operation). For programs the RPC can parse, the operation is
    its name; otherwise the raw discriminator."""
    pid = ix.get("programId") or ""
    parsed = ix.get("parsed")
    if isinstance(parsed, dict) and parsed.get("type"):
        return (pid, "parsed:" + str(parsed["type"]))
    if isinstance(parsed, str):
        return (pid, "parsed:" + parsed)
    return (pid, "disc:" + b58_prefix(str(ix.get("data") or "")))


def declared_accounts(ix: dict, parsed_info_order: bool = True) -> list:
    """The accounts this instruction declares, in order.

    jsonParsed hides the account list for programs it understands, putting
    named fields in `parsed.info` instead. Those values are pubkeys, so the
    declared set is recoverable -- sorted by field name to keep the order
    stable across transactions of the same type.
    """
    if ix.get("accounts"):
        return list(ix["accounts"])
    parsed = ix.get("parsed")
    if isinstance(parsed, dict):
        info = parsed.get("info") or {}
        out = []
        for field in sorted(info):
            val = info[field]
            if isinstance(val, str) and 32 <= len(val) <= 44:
                out.append(val)
        return out
    return []


def outcome_shape(tx: dict, accounts: list) -> str:
    """Direction of change for each declared account: lamports and tokens.

    'u' up, 'd' down, '.' unchanged, '?' the account is not in the transaction's
    key list at all.
    """
    msg = tx["transaction"]["message"]
    meta = tx["meta"]
    keys = [a["pubkey"] if isinstance(a, dict) else a for a in msg["accountKeys"]]
    index = {k: i for i, k in enumerate(keys)}

    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    tok_pre, tok_post = {}, {}
    for row in meta.get("preTokenBalances") or []:
        tok_pre[row["accountIndex"]] = row["uiTokenAmount"].get("amount")
    for row in meta.get("postTokenBalances") or []:
        tok_post[row["accountIndex"]] = row["uiTokenAmount"].get("amount")

    def direction(before, after):
        if before is None or after is None:
            return "."
        try:
            b, a = int(before), int(after)
        except (TypeError, ValueError):
            return "."
        return "u" if a > b else ("d" if a < b else ".")

    parts = []
    for acct in accounts:
        i = index.get(acct)
        if i is None or i >= len(pre) or i >= len(post):
            parts.append("?")
            continue
        lam = direction(pre[i], post[i])
        tok = direction(tok_pre.get(i), tok_post.get(i))
        parts.append(lam + tok)
    return "|".join(parts)


def roles(tx: dict, accounts: list) -> str:
    """Signer and writable flags for the declared accounts, in order.

    This is the cheapest piece of account metadata a signer can read off the
    transaction itself, so it is the first candidate for what has to be added
    when the operation name alone is not enough.
    """
    msg = tx["transaction"]["message"]
    meta = {}
    for a in msg["accountKeys"]:
        if isinstance(a, dict):
            meta[a["pubkey"]] = (bool(a.get("signer")), bool(a.get("writable")))
    out = []
    for acct in accounts:
        s, w = meta.get(acct, (False, False))
        out.append(("S" if s else "-") + ("W" if w else "-"))
    return "".join(out)


def load_instructions(paths):
    """Every single-instruction transaction across these block files."""
    rows = []
    stats = {"tx": 0, "failed": 0, "multi": 0, "kept": 0, "noaccts": 0}
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            block = json.load(fh).get("result") or {}
        for tx in block.get("transactions") or []:
            stats["tx"] += 1
            meta = tx.get("meta") or {}
            if meta.get("err"):
                stats["failed"] += 1
                continue
            ixs = [
                ix for ix in tx["transaction"]["message"].get("instructions") or []
                if (ix.get("programId") or "") not in NOOP_PROGRAMS
            ]
            if len(ixs) != 1:
                stats["multi"] += 1
                continue
            ix = ixs[0]
            accounts = declared_accounts(ix)
            if not accounts:
                stats["noaccts"] += 1
                continue
            program, operation = instruction_key(ix)
            rows.append({
                "program": program,
                "operation": operation,
                "n": len(accounts),
                "roles": roles(tx, accounts),
                "shape": outcome_shape(tx, accounts),
            })
            stats["kept"] += 1
    return rows, stats


KEYS = {
    "program": lambda r: (r["program"],),
    "program+operation": lambda r: (r["program"], r["operation"]),
    "program+operation+arity": lambda r: (r["program"], r["operation"], r["n"]),
    "program+operation+roles": lambda r: (r["program"], r["operation"], r["roles"]),
}


def determinism(rows, key_fn):
    """Share of repeatedly-seen keys whose effect shape is not unique.

    Same denominator discipline as the ARC census: a key seen once cannot be
    shown ambiguous, so it is excluded rather than counted as clean.
    """
    groups = defaultdict(lambda: defaultdict(int))
    for r in rows:
        groups[key_fn(r)][r["shape"]] += 1
    repeated = ambiguous = t_rep = t_amb = 0
    for shapes in groups.values():
        total = sum(shapes.values())
        if total < 2:
            continue
        repeated += 1
        t_rep += total
        if len(shapes) > 1:
            ambiguous += 1
            t_amb += total
    return {
        "keys": len(groups),
        "repeated": repeated,
        "ambiguous": ambiguous,
        "pair_rate": ambiguous / repeated if repeated else 0.0,
        "transition_rate": t_amb / t_rep if t_rep else 0.0,
    }
