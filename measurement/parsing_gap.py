"""How much of Solana mainnet can anybody actually read?

The Solana Foundation's own Discriminator Database RFP states the problem:

    "Teams in the Solana ecosystem regularly face challenges interacting with
    unknown deployed contracts and parsing unknown instructions... it is quite
    hard for data and monitoring teams to parse instructions cleanly."

That is asserted everywhere and measured nowhere. This measures it.

METHOD

For a run of consecutive mainnet blocks, every instruction is classified by
whether the RPC's own `jsonParsed` encoding could name it:

    LEGIBLE   the RPC returned a `parsed` field -- a natively known program
              (System, SPL Token, Associated Token, Vote, Stake, Memo).
              Anyone can read these with no extra knowledge.

    OPAQUE    the RPC returned raw base58 data. Reading it requires an IDL,
              a discriminator table, or hand-written semantics that the
              reader has to find or build for themselves.

The RPC's parser is the right yardstick precisely because it is the floor:
it is what every developer gets for free, without an indexer, an IDL registry
or a paid API. Everything above that floor is duplicated effort somewhere.

Inner instructions are counted too. A transaction that looks like one Jupiter
call is often a dozen CPIs underneath, and a monitoring team has to read all
of them.

WHAT THE OUTPUT IS FOR

Two things, both of which the RFP asks for and neither of which exists:

1. The size of the hole, as a share of real instruction volume.
2. A frequency-ranked work queue -- which programs, in which order, buy the
   most legibility per program modelled. The cumulative curve answers
   "model the top N and you cover X%", which is the only sane way to plan
   this work.

No API key. Public RPC only, deliberately: a measurement anybody can rerun
is worth more than a bigger one nobody can check.

    python measurement/parsing_gap.py --blocks 12
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

# Blocks run to several megabytes and the public endpoint truncates them under
# load. That surfaces as IncompleteRead, not as an HTTP error, so it has to be
# named explicitly or a run dies two blocks in.
TRANSIENT = (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
             http.client.IncompleteRead, http.client.RemoteDisconnected,
             ConnectionError, json.JSONDecodeError)

RPC = "https://api.mainnet-beta.solana.com"

# Consensus traffic. Kept separate rather than dropped: it is more than half of
# a block, so folding it into any percentage silently doubles the answer, and
# that is exactly the kind of inflation this measurement exists to avoid.
VOTE = "Vote111111111111111111111111111111111111111"

# The RPC's jsonParsed encoding does not name ComputeBudget instructions, so
# they count as opaque by the letter of the test -- and they are 43% of the
# opaque volume, which would inflate the headline by half. They are also
# native, change no account state, and take four lines to decode. Counting
# them would be the same error as counting vote traffic. So the headline
# excludes them and the raw figure is printed underneath, because the honest
# number is the one that survives someone else checking it.
TRIVIAL = {"ComputeBudget111111111111111111111111111111"}


def rpc(method: str, params: list, tries: int = 5):
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    for attempt in range(tries):
        req = urllib.request.Request(
            RPC, data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.loads(r.read())
            if "error" in out:
                # -32007/-32009 mean the block was skipped or pruned, which is
                # normal and not worth retrying.
                code = out["error"].get("code")
                if code in (-32007, -32009):
                    return None
                raise RuntimeError(out["error"])
            return out.get("result")
        except TRANSIENT:
            if attempt == tries - 1:
                return None      # skip this block rather than lose the run
            time.sleep(2 * (attempt + 1))
    return None


def get_block(slot: int):
    return rpc("getBlock", [slot, {
        "encoding": "jsonParsed",
        "transactionDetails": "full",
        "maxSupportedTransactionVersion": 0,
        "rewards": False,
    }])


def legible(ix: dict) -> bool:
    """Could the RPC name this instruction without outside help?"""
    return "parsed" in ix


def walk(tx: dict):
    """Every instruction in a transaction, top level and inner (CPI)."""
    msg = tx.get("transaction", {}).get("message", {})
    for ix in msg.get("instructions", []):
        yield ix, False
    for group in (tx.get("meta") or {}).get("innerInstructions") or []:
        for ix in group.get("instructions", []):
            yield ix, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=12)
    ap.add_argument("--out", default="measurement/parsing_gap.json")
    args = ap.parse_args()

    tip = rpc("getSlot", [{"commitment": "finalized"}])
    print("finalized tip: %d" % tip, flush=True)

    total = opaque_n = inner_n = 0
    per_program = Counter()          # opaque instructions, by program
    legible_per_program = Counter()
    tx_total = tx_with_opaque = 0
    blocks_read = []

    slot = tip - 40                  # a little behind the tip, so blocks exist
    while len(blocks_read) < args.blocks:
        blk = get_block(slot)
        slot -= 1
        if not blk:
            continue
        blocks_read.append(slot + 1)
        for tx in blk.get("transactions", []):
            msg = tx.get("transaction", {}).get("message", {})
            programs = {ix.get("programId") for ix in msg.get("instructions", [])}
            if programs == {VOTE}:
                continue             # pure consensus traffic, nobody signs it
            tx_total += 1
            any_opaque = False
            for ix, is_inner in walk(tx):
                pid = ix.get("programId") or "?"
                if pid == VOTE:
                    continue
                total += 1
                inner_n += is_inner
                if legible(ix):
                    legible_per_program[pid] += 1
                else:
                    opaque_n += 1
                    per_program[pid] += 1
                    any_opaque = True
            tx_with_opaque += any_opaque
        print("  slot %d  instructions so far %d" % (slot + 1, total), flush=True)

    if not total:
        print("no instructions read", file=sys.stderr)
        return 1

    trivial_n = sum(per_program[p] for p in TRIVIAL)
    core = Counter({p: n for p, n in per_program.items() if p not in TRIVIAL})
    c_total = total - trivial_n
    c_opaque = opaque_n - trivial_n

    print("\n" + "=" * 68)
    print("THE PARSING GAP -- %d blocks, %d non-vote transactions"
          % (len(blocks_read), tx_total))
    print("=" * 68)
    print("instructions (incl. %d inner/CPI)      %8d" % (inner_n, c_total))
    print("legible to the RPC out of the box     %8d   %6.2f%%"
          % (c_total - c_opaque, 100 * (c_total - c_opaque) / c_total))
    print("OPAQUE -- needs an IDL or semantics   %8d   %6.2f%%"
          % (c_opaque, 100 * c_opaque / c_total))
    print("distinct opaque programs              %8d" % len(core))
    print("transactions containing >=1 opaque ix %8d   %6.2f%%"
          % (tx_with_opaque, 100 * tx_with_opaque / tx_total))
    print("\n(excludes %d ComputeBudget instructions, which the RPC also does"
          % trivial_n)
    print(" not name but which are native and change no state. Counting them")
    print(" would put the headline at %.2f%% -- see TRIVIAL in the source.)"
          % (100 * opaque_n / total))

    print("\nTop opaque programs by instruction volume")
    print("-" * 68)
    print("%-46s %7s %7s %7s" % ("program", "count", "share", "cumul"))
    run = 0
    for pid, n in core.most_common(25):
        run += n
        print("%-46s %7d %6.2f%% %6.2f%%"
              % (pid, n, 100 * n / c_opaque, 100 * run / c_opaque))

    print("\nHow far does modelling N programs get you?")
    print("-" * 68)
    ranked = [n for _, n in core.most_common()]
    for k in (1, 5, 10, 25, 50, 100):
        if k <= len(ranked):
            share = 100 * sum(ranked[:k]) / c_opaque
            of_all = 100 * (c_total - c_opaque + sum(ranked[:k])) / c_total
            print("  top %-4d programs -> %6.2f%% of opaque volume, "
                  "%6.2f%% of ALL instructions legible" % (k, share, of_all))

    tail = sum(1 for _, n in core.items() if n == 1)
    print("\nprograms seen exactly once: %d of %d (%.1f%% of the tail)"
          % (tail, len(core), 100 * tail / len(core)))

    payload = {
        "blocks": blocks_read,
        "transactions_non_vote": tx_total,
        "instructions": c_total,
        "inner_instructions": inner_n,
        "opaque": c_opaque,
        "opaque_share": c_opaque / c_total,
        "tx_with_opaque_share": tx_with_opaque / tx_total,
        "distinct_opaque_programs": len(core),
        "compute_budget_excluded": trivial_n,
        "opaque_share_if_counted": opaque_n / total,
        "queue": [{"program": p, "count": n}
                  for p, n in core.most_common(200)],
        "legible_by_program": dict(legible_per_program.most_common(50)),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
