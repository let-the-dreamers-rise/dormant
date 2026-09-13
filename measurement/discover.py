"""Recover what an undocumented program's instructions DO, from observed effect.

Fifteen of the twenty-five busiest Solana programs publish no IDL. For those,
there is no file to read and no name to look up -- the only evidence available
is the instruction itself and what the ledger records happening around it.

This is the method, run end to end, on one program:

    1. Take every instruction calling the program across a run of blocks,
       top level and inner (CPI) alike.
    2. Group them by DISCRIMINATOR -- the first eight bytes of instruction
       data. Anchor programs put a stable 8-byte tag there; native-style
       programs use one byte and simply repeat across the remaining seven.
       Either way the leading bytes separate one operation from another.
    3. For each occurrence, record what the transaction's own metadata says
       changed: the direction of every declared account's lamport and token
       balance, plus its signer/writable roles.
    4. Report, per discriminator, how CONSISTENT that effect shape is.

Step 4 is the whole point, and it is falsifiable. If a discriminator's effect
shape is near-constant across hundreds of independent transactions, the effect
is a property of the instruction and can be written down. If it scatters, the
effect depends on data or state this approach cannot see, and the honest output
is to say so rather than to guess. A high determinism figure is the evidence
that reverse engineering this program is tractable; a low one is the evidence
that it is not, and both are worth publishing.

This does not recover argument layouts or produce an IDL. It recovers effect,
which is the thing an IDL would not have told you anyway.

No API key. Public RPC only.

    python measurement/discover.py --program EtrnLzgbS7nMMy5fbD42kXiUzGg8XQzJ972Xtk1cjWih --blocks 14
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from parsing_gap import get_block, rpc
from solana import declared_accounts, outcome_shape, roles

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# sha256("anchor:event")[:8]. Anchor emits structured events by having the
# program invoke ITSELF with this discriminator, so an event shows up in the
# ledger as an ordinary instruction. On a busy Anchor program that is half of
# all apparent instruction volume, carrying no accounts and changing no state.
# Counting it as an operation would inflate the work queue and make every
# program look twice as complicated as it is.
ANCHOR_EVENT = "e445a52e51cb9a1d"


def b58_bytes(data: str) -> bytes:
    """Base58 string to raw bytes. Leading '1's are leading zero bytes."""
    if not data:
        return b""
    num = 0
    for ch in data:
        idx = B58.find(ch)
        if idx < 0:
            return b""
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8 or 1, "big")
    pad = len(data) - len(data.lstrip("1"))
    return b"\x00" * pad + raw


def resolved(tx: dict) -> dict:
    """A copy of the transaction whose accountKeys include lookup-table loads.

    A v0 transaction names most of its accounts indirectly, through address
    lookup tables, and `jsonParsed` returns those separately in
    `meta.loadedAddresses`. The balance arrays, however, are indexed over the
    FULL account list -- static keys, then loaded writable, then loaded
    readonly. Reading effect off `accountKeys` alone silently scores every
    lookup-table account as absent, which on modern DeFi traffic is most of
    them. This splices the list back together in the canonical order.

    The existing measurement helpers are left untouched on purpose: they
    produced numbers already published, and quietly changing the code under a
    quoted figure is its own kind of dishonesty.
    """
    msg = dict(tx["transaction"]["message"])
    keys = list(msg.get("accountKeys") or [])
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    for pubkey in loaded.get("writable") or []:
        keys.append({"pubkey": pubkey, "signer": False, "writable": True})
    for pubkey in loaded.get("readonly") or []:
        keys.append({"pubkey": pubkey, "signer": False, "writable": False})
    msg["accountKeys"] = keys
    return {"transaction": {"message": msg}, "meta": tx.get("meta") or {}}


def walk(tx: dict):
    """Every instruction, top level and inner, with its nesting flag."""
    msg = tx.get("transaction", {}).get("message", {})
    for ix in msg.get("instructions", []):
        yield ix, False
    for group in (tx.get("meta") or {}).get("innerInstructions") or []:
        for ix in group.get("instructions", []):
            yield ix, True


def own_logs(tx: dict, program: str) -> list:
    """The program's own log lines from its first invocation frame.

    Balance deltas are blind to instructions whose entire effect is a write to
    account data -- an oracle update, a config change, a position record. For
    those, the runtime log is the only evidence in the block, and it is often
    remarkably forthcoming: Anchor's generated dispatcher emits
    `Program log: Instruction: <Name>` before handing off, so a program with no
    published IDL routinely announces its own method names anyway.

    Attribution is the catch, because log lines carry no instruction index.
    The caller only uses this when the transaction contains exactly ONE real
    (non-event) instruction for the program, which makes the mapping
    unambiguous. That discards data and keeps the attribution sound, which is
    the right trade for evidence meant to be published.
    """
    lines = (tx.get("meta") or {}).get("logMessages") or []
    return _frame_logs(lines, program)


def any_logs(tx: dict, program: str) -> list:
    """The program's log vocabulary, regardless of how often it was invoked.

    Unattributable to a specific discriminator, so it is kept separate from
    per-operation evidence -- but a program invoked twice in every transaction
    (an open/close pair, a guard wrapping a trade) would otherwise contribute
    nothing at all, and what a program calls itself is worth knowing even when
    you cannot say which instruction said it.
    """
    lines = (tx.get("meta") or {}).get("logMessages") or []
    if not any(ln.startswith("Program " + program) and " invoke [" in ln
               for ln in lines):
        return []
    return _frame_logs(lines, program)


def _frame_logs(lines: list, program: str) -> list:
    out, inside, depth = [], False, 0
    for ln in lines:
        if ln.startswith("Program " + program) and " invoke [" in ln:
            inside, depth = True, 0
            continue
        if not inside:
            continue
        if " invoke [" in ln:
            depth += 1
            continue
        if ln.endswith(" success") or " failed" in ln:
            if depth == 0:
                break
            depth -= 1
            continue
        # Only lines emitted by the program itself, not by anything it called.
        if depth == 0 and ln.startswith("Program log: "):
            out.append(ln[len("Program log: "):][:80])
    return out


def token_deltas(tx: dict) -> set:
    """Every absolute balance change the transaction recorded, as raw units.

    Used to test a guess about argument layout. An instruction that says "sell
    N tokens" has to move N tokens, so if the 64-bit field at a given offset
    keeps turning up in the ledger's own delta set, that field is the amount.
    Lamport deltas are included because quote-side amounts are often SOL.
    """
    meta = tx.get("meta") or {}
    out = set()
    pre = {r["accountIndex"]: r["uiTokenAmount"].get("amount")
           for r in meta.get("preTokenBalances") or []}
    post = {r["accountIndex"]: r["uiTokenAmount"].get("amount")
            for r in meta.get("postTokenBalances") or []}
    for idx in set(pre) | set(post):
        try:
            delta = abs(int(post.get(idx) or 0) - int(pre.get(idx) or 0))
        except (TypeError, ValueError):
            continue
        if delta:
            out.add(delta)
    lam_pre = meta.get("preBalances") or []
    lam_post = meta.get("postBalances") or []
    for i in range(min(len(lam_pre), len(lam_post))):
        delta = abs(lam_post[i] - lam_pre[i])
        if delta:
            out.add(delta)
    return out


def verify_args(program: str, disc: str, blocks: int) -> None:
    """Test whether the 64-bit fields after the discriminator are amounts.

    This is the step that separates naming an instruction from understanding
    it. A log line gives you `Instruction: Sell`; it does not tell you what is
    being sold or how much. If the u64 at offset 8 equals a balance change the
    ledger recorded, in transaction after transaction, then the layout is not a
    guess any more.
    """
    slot = rpc("getSlot", [{"commitment": "finalized"}])
    if slot is None:
        raise SystemExit("could not reach the RPC")

    seen = 0
    hits = Counter()
    for i in range(blocks):
        block = get_block(slot - i)
        if block is None:
            continue
        for tx in block.get("transactions") or []:
            if (tx.get("meta") or {}).get("err") is not None:
                continue
            deltas = None
            for ix, _ in walk(tx):
                if ix.get("programId") != program:
                    continue
                raw = b58_bytes(str(ix.get("data") or ""))
                if len(raw) < 16 or raw[:8].hex() != disc:
                    continue
                if deltas is None:
                    deltas = token_deltas(tx)
                seen += 1
                for off in (8, 16):
                    if len(raw) >= off + 8:
                        val = int.from_bytes(raw[off:off + 8], "little")
                        if val and val in deltas:
                            hits[off] += 1
        sys.stderr.write("\r  %d/%d blocks, %d samples" % (i + 1, blocks, seen))
        sys.stderr.flush()
    sys.stderr.write("\n")

    print("\nprogram        %s" % program)
    print("discriminator  %s" % disc)
    print("samples        %d\n" % seen)
    if not seen:
        print("  none found in this slot range")
        return
    for off in (8, 16):
        print("  u64 at byte offset %-3d matches an observed balance delta"
              "  %5.1f%%  (%d/%d)"
              % (off, 100 * hits[off] / seen, hits[off], seen))
    print("\n  A field matching the ledger's own deltas in most transactions is"
          "\n  an amount. One that rarely matches is a limit or a slippage"
          "\n  bound -- a number the instruction is allowed to not reach.")


def modal(counter: Counter):
    """Most common value and the share of observations it accounts for."""
    if not counter:
        return None, 0.0
    value, hits = counter.most_common(1)[0]
    return value, hits / sum(counter.values())


def collect(program: str, blocks: int) -> dict:
    slot = rpc("getSlot", [{"commitment": "finalized"}])
    if slot is None:
        raise SystemExit("could not reach the RPC to get a starting slot")

    obs = defaultdict(lambda: {
        "count": 0, "inner": 0, "arity": Counter(), "roles": Counter(),
        "shape": Counter(), "datalen": Counter(), "logs": Counter(),
    })
    stats = {"blocks": 0, "skipped": 0, "tx": 0, "failed": 0, "hits": 0}
    vocab = Counter()

    for i in range(blocks):
        block = get_block(slot - i)
        if block is None:
            stats["skipped"] += 1
            continue
        stats["blocks"] += 1
        for tx in block.get("transactions") or []:
            stats["tx"] += 1
            # A failed transaction's balance deltas are the fee, not the
            # instruction's effect. Including them would teach the model that
            # every operation drains the fee payer.
            if (tx.get("meta") or {}).get("err") is not None:
                stats["failed"] += 1
                continue
            hits = []
            for ix, is_inner in walk(tx):
                if ix.get("programId") != program:
                    continue
                raw = b58_bytes(str(ix.get("data") or ""))
                if raw:
                    hits.append((raw[:8].hex(), ix, is_inner, len(raw)))
            if not hits:
                continue

            rtx = resolved(tx)
            for line in any_logs(tx, program):
                vocab[line] += 1

            # Name an operation from the logs only when this transaction ran
            # exactly one real instruction of the program. The event self-CPI
            # does not count -- it is the program talking about the operation,
            # not a second operation.
            real = [h for h in hits if h[0] != ANCHOR_EVENT]
            logs = own_logs(tx, program) if len(real) == 1 else []
            named = real[0][0] if len(real) == 1 else None

            for disc, ix, is_inner, datalen in hits:
                accts = declared_accounts(ix)
                rec = obs[disc]
                rec["count"] += 1
                rec["inner"] += 1 if is_inner else 0
                rec["arity"][len(accts)] += 1
                rec["roles"][roles(rtx, accts)] += 1
                rec["shape"][outcome_shape(rtx, accts)] += 1
                rec["datalen"][datalen] += 1
                if disc == named:
                    for line in logs:
                        rec["logs"][line] += 1
                stats["hits"] += 1

        done = i + 1
        sys.stderr.write("\r  %d/%d blocks, %d instructions"
                         % (done, blocks, stats["hits"]))
        sys.stderr.flush()
    sys.stderr.write("\n")
    return {"program": program, "stats": stats, "obs": obs, "vocab": vocab}


def report(result: dict, top: int) -> dict:
    program, stats, obs = result["program"], result["stats"], result["obs"]
    total = stats["hits"] or 1

    rows = []
    for disc, rec in sorted(obs.items(), key=lambda kv: -kv[1]["count"]):
        shape, shape_det = modal(rec["shape"])
        role, role_det = modal(rec["roles"])
        arity, _ = modal(rec["arity"])
        datalen, _ = modal(rec["datalen"])
        rows.append({
            "discriminator": disc, "count": rec["count"],
            "share": rec["count"] / total,
            "inner_share": rec["inner"] / rec["count"],
            "arity": arity, "data_len": datalen,
            "roles": role, "roles_determinism": role_det,
            "shape": shape, "shape_determinism": shape_det,
            "distinct_shapes": len(rec["shape"]),
            "logs": [line for line, _ in rec["logs"].most_common(4)],
        })

    print("\nprogram      %s" % program)
    print("blocks       %d read, %d skipped" % (stats["blocks"], stats["skipped"]))
    print("transactions %d seen, %d failed and excluded"
          % (stats["tx"], stats["failed"]))
    print("instructions %d calling this program" % stats["hits"])
    print("operations   %d distinct discriminators\n" % len(rows))

    if not rows:
        print("  Nothing found. The program may be idle in this slot range.")
        return {"program": program, "stats": stats, "operations": rows}

    print("  %-17s %7s %7s %6s %5s %7s  %s"
          % ("discriminator", "count", "share", "cum", "accts", "det",
             "effect shape (modal)"))
    cum = 0.0
    for row in rows[:top]:
        cum += row["share"]
        print("  %-17s %7d %6.1f%% %5.1f%% %5s %6.1f%%  %s"
              % (row["discriminator"], row["count"], 100 * row["share"],
                 100 * cum, row["arity"], 100 * row["shape_determinism"],
                 (row["shape"] or "")[:58]))
    if len(rows) > top:
        print("  ... %d more, %.1f%% of volume"
              % (len(rows) - top, 100 * (1 - cum)))

    named = [r for r in rows[:top] if r["logs"]]
    if named:
        print("\n  what the program calls them (its own runtime logs):")
        for row in named:
            print("    %-17s %s" % (row["discriminator"], "; ".join(row["logs"])))

    vocab = result.get("vocab") or Counter()
    if vocab:
        print("\n  the program's log vocabulary (not attributable to one"
              " discriminator):")
        for line, hits in vocab.most_common(10):
            print("    %5d  %s" % (hits, line))

    # The headline: weight each operation's determinism by how often it runs.
    # An operation seen twice being unpredictable matters far less than the
    # one carrying half the program's traffic being unpredictable.
    weighted = sum(r["shape_determinism"] * r["count"] for r in rows) / total
    covered = sum(r["share"] for r in rows[:top])
    print("\n  volume-weighted effect determinism  %.1f%%" % (100 * weighted))
    print("  top %d operations cover              %.1f%% of this program"
          % (top, 100 * covered))
    print("\n  Read: when one discriminator's effect shape repeats across"
          "\n  hundreds of independent transactions, the effect is a property"
          "\n  of the instruction and can be written down without source.")
    return {"program": program, "stats": stats,
            "weighted_determinism": weighted, "operations": rows,
            "log_vocabulary": [
                {"line": line, "count": hits}
                for line, hits in (result.get("vocab") or Counter()).most_common(30)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--blocks", type=int, default=14)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out", default="")
    ap.add_argument("--args", default="",
                    help="discriminator to test for argument layout")
    args = ap.parse_args()

    if args.args:
        verify_args(args.program, args.args, args.blocks)
        return 0

    result = collect(args.program, args.blocks)
    summary = report(result, args.top)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
        print("\n  wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
