# measurement

The experiments that decided the design. Both are runnable; neither needs a
paid endpoint.

## `solana.py` -- M1, the kill experiment

**Question:** does the statically declared content of a transaction determine
what it does, or is chain state required? If the same program, instruction and
account roles produce wildly different effects, preconditions are not
computable and the project dies here, cheaply.

**Method.** Balance deltas from the RPC are per *transaction*, not per
instruction, so attributing a delta inside a multi-instruction transaction is
guesswork. Only transactions carrying exactly one state-affecting instruction
are considered (after dropping ComputeBudget, which changes no state). That
throws away most of the corpus, and it is the right trade: a smaller honest
sample beats a larger one built on an assumption.

The outcome measured is the effect *shape* -- for each declared account, in
order, whether lamports rose, fell or held, and the same for token balances.
Exact amounts depend on state by definition and are not the question.

Every key is scored by held-out prediction, 5-fold, with unseen combinations
counted **wrong**, so no key can win by splitting the space until nothing
repeats. A matched-cardinality random control is included, because a key can
otherwise look explanatory when it is only fragmenting.

**Result** -- 30 consecutive mainnet blocks, 30,861 transactions, 2,925
single-instruction samples across 121 programs. All keys scored on the same
331 held-out transactions:

| key | accuracy |
|---|---|
| program | 92.7% |
| program + operation | 98.2% |
| program + operation + arity | 99.1% |
| **program + operation + account roles** | **100.0%** |
| random control, matched cardinality | 96.7% |

The fields a signer can read straight off the transaction predict the effect
shape perfectly, and beat a meaningless control of the same cardinality by 3.3
points. On raw held-out scoring that control collapses to 10.9%, which confirms
the measure punishes fragmentation rather than rewarding it.

**The finding that chose the architecture.** `program + operation + roles`
covers only **58.9%** of held-out transactions -- four in ten present a
combination never seen before. So a lookup table cannot be the product. The
effect has to be *computed* from program semantics, not recalled. The
experiment did not merely endorse the idea; it ruled out the cheaper version.

**Honest limits.** The matched-support subset is 331 transactions and 30
consecutive blocks are minutes of one day. Effect *shape* is coarser than
effect *value*.

## The alarm budget

A detector earns its place by firing on the bad thing **and staying silent
otherwise**. The second half is measurable with no users at all. Over the same
30 blocks, vote traffic excluded -- **10,336 signable transactions**:

| class | count | rate |
|---|---|---|
| durable nonce alone | 841 | **8.14%** -- one in twelve |
| any control transfer | 14 | 0.135% -- one in 740 |
| upgrade authority transfer | 0 | none observed |
| **durable nonce AND control transfer** | **0** | **0.0000%** |

This **changed the design**. The first version banner-warned on every durable
nonce; at 8.14% that fires once every twelve transactions, which is noise that
teaches people to click through -- exactly the habituation the Drift signers
were operating under. The nonce is now reported as context, and the
**conjunction** is the alarm.

Zero is an upper bound, not a proof of never: by the rule of three the true
rate is under 0.029% at 95% confidence. Legitimate cases surely exist, since
offline-signed authority rotation is reasonable. They are rare enough that one
deserves full attention.

## The kill test on simulation

Run against public mainnet RPC on 5 September 2026, on a transaction that
executed successfully on 1 April 2026 at slot 410,201,959:

| test | result |
|---|---|
| replay with its original April blockhash | `err: null`, but `unitsConsumed: null` and zero logs -- the node returned without executing |
| substitute a current blockhash | `invalid transaction: Transaction loads an address table account that doesn't exist` |
| request the historical slot via `minContextSlot` | identical failure; `minContextSlot` is a freshness floor and cannot move backwards |

Meanwhile `getFirstAvailableBlock` returns 0 and `getBlock(409000000)` returns
a real block from March 2026.

**The ledger has a complete time axis. The simulator has none** -- not forward
to when a dormant transaction will land, nor backward to when it was signed.
You cannot fork your way to the answer, because the state you would fork is
gone. That is why this analysis is static rather than simulated.
