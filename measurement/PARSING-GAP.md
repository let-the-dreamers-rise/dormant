# How much of Solana can anybody actually read?

In September 2024 the Solana Foundation published an RFP called
**Discriminator Database**, and stated the problem in its own words:

> Teams in the Solana ecosystem regularly face challenges interacting with
> unknown deployed contracts and **parsing unknown instructions**. A community
> discriminator dataset would lead to a public good grouping of IDL
> discriminators that any developer can pull from when needed, which would lead
> to an incremental increase in developer productivity and speed of interaction
> of Solana tooling.

And, answering a question on the forum thread:

> Generally speaking, **it is quite hard for data and monitoring teams to parse
> instructions cleanly.**

The RFP earmarked $60,000. What it did not contain -- what nobody has
published -- is **the size of the hole**. This measures it.

    python measurement/parsing_gap.py --blocks 12

No API key, public RPC, ten minutes. A measurement anybody can rerun is worth
more than a bigger one nobody can check.

## Method

Every instruction in a run of consecutive mainnet blocks is classified by
whether the RPC's own `jsonParsed` encoding could name it:

- **LEGIBLE** -- the RPC returned a `parsed` field. Natively known programs:
  System, SPL Token, Associated Token, Stake, Memo. Anyone can read these with
  no extra knowledge and no dependencies.
- **OPAQUE** -- raw base58 data. Reading it requires an IDL, a discriminator
  table, or hand-written semantics that the reader has to find or build.

The RPC's parser is the right yardstick precisely because it is **the floor**:
it is what every developer gets for free, with no indexer, no IDL registry and
no paid API. Everything above that floor is effort being duplicated in every
team on the network, independently, forever.

**Inner instructions are counted.** A transaction that looks like one Jupiter
call is often a dozen CPIs underneath, and a monitoring team has to read all of
them. Excluding them would understate the gap by more than half.

**Two exclusions, both to avoid inflating the answer.** Pure vote transactions
are dropped -- they are more than half of a block and nobody parses them for
meaning. ComputeBudget instructions are dropped from the headline even though
the RPC genuinely does not name them: they are native, change no account state,
and take four lines to decode. Counting them would push the headline from ~36%
to ~56% for free, which is exactly the kind of number this measurement exists
to not produce. The raw figure is printed underneath the headline anyway.

## Result

Two independent runs, September 2026, near slot 444,898,000:

| | run A (10 blocks) | run B (12 blocks) |
|---|---|---|
| non-vote transactions | 5,172 | 5,488 |
| instructions (incl. CPI) | 35,727 | 31,986 |
| **opaque** | **42.06%** | **36.17%** |
| transactions with >= 1 opaque instruction | **98.72%** | **87.55%** |
| distinct opaque programs | 199 | 191 |

**Roughly four in ten instructions executing on Solana right now cannot be read
by the tool every developer already has.** They appear in the large majority of
transactions.

## The part that makes it fundable: the hole is bounded

The tail is long -- around 200 distinct opaque programs in twelve blocks, a
fifth of them seen exactly once. But volume is not uniformly distributed, and
that changes the shape of the job completely:

| programs modelled | share of opaque volume | **share of ALL instructions legible** |
|---|---|---|
| top 1 | 14% | 69% |
| top 5 | 49% | 81% |
| top 10 | 63% | 87% |
| **top 25** | **81%** | **93%** |
| top 50 | 92% | 97% |
| top 100 | 98% | 99% |

(run B; run A agrees within a point at every row -- top 25 gives 93.81% there
against 93.07% here.)

**Twenty-five programs takes Solana from roughly 60% legible to roughly 93%.**

That is the finding. This is not an open-ended research problem, it is a finite
and rather short list of work, and until now nobody knew how short.

The top of the current queue:

| program | what it is |
|---|---|
| `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` | Pump AMM |
| `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` | Jupiter aggregator v6 |
| `EtrnLzgbS7nMMy5fbD42kXiUzGg8XQzJ972Xtk1cjWih` | |
| `pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ` | |
| `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` | |

The full ranked queue, 200 entries deep, is written to `parsing_gap.json` on
every run. The queue is the deliverable as much as the percentage is: it means
the next unit of work is never a guess.

## Why this is worth money to the network rather than to me

Every indexer, explorer, wallet, monitoring service, analytics dashboard and
security tool on Solana solves this same problem privately today, at its own
cost, with its own coverage and its own bugs. It is a **horizontal dependency**:
the work is duplicated across every team, and none of the copies compound.

A shared, machine-readable account of what instructions do is the classic shape
of a public good -- it cannot be captured by whoever builds it, which is exactly
why it does not get built commercially, and exactly why it is a grant and not a
product.

And the leverage runs the right way: better parsing means better tooling, which
means developers ship faster, which means more applications, which means more
transactions. The Foundation named that chain itself -- *"an incremental
increase in developer productivity and speed of interaction of Solana tooling."*

## Honest limits

- Twelve blocks are seconds of one day. Volume mix shifts with market activity;
  a memecoin frenzy raises Pump AMM's share and a quiet hour lowers it. The
  *shape* of the curve replicated across two independent samples, but the
  ranking of individual programs will move.
- "Legible to the RPC" is a floor, not a ceiling. Some opaque programs publish
  Anchor IDLs on chain, so a developer willing to fetch and cache them can read
  more than 64%. Measuring how much more is the obvious next experiment and it
  is not done here -- so treat the 36-42% as the gap facing a developer using
  the default tools, not as the gap facing one who has already built an IDL
  fetching pipeline.
- Naming an instruction is not the same as knowing what it does to state.
  A discriminator database gives you the former. `../dormant/semantics.py` is an
  attempt at the latter, and it is much harder.

---

# Addendum: the strongest objection to the above, measured

The honest limits section said an on-chain Anchor IDL lets a developer read
more than the RPC hands them, that measuring how much more was the obvious next
experiment, and that it had not been done. It has now: `idl_availability.py`.

The objection deserves stating at full strength, because it is the one that
should decide whether semantics work is worth funding at all:

> Your 42% measures what the RPC's `jsonParsed` does, not what is *knowable*.
> Most modern Anchor programs upload their IDL on chain. Fetch and cache those
> and much of the gap closes with a caching script, not hand-written semantics.

**It is half right, and the half matters.** Of the top 25 opaque programs:

| | programs | share of top-25 volume |
|---|---|---|
| publish an on-chain Anchor IDL | **10** | **57.7%** |
| publish none | **15** | **42.3%** |

So a caching script is worth real coverage, and anyone claiming otherwise has
not checked. The full ladder, in shares of *all* mainnet instructions:

| level | reachable by | legible |
|---|---|---|
| **0** | the RPC alone, today | **63.8%** |
| **1** | + caching every on-chain IDL | **80.7%** |
| **2** | + semantics for the top 25 | **93.1%** |

**Level 1 is a weekend's work and it is genuinely worth 17 points.** That is a
real finding and it argues against part of the case for funding this.

Two things survive it.

**Fifteen of the twenty-five publish nothing.** They are 12.4% of all mainnet
instruction volume and no amount of caching reaches them. They are
disproportionately AMMs and launchpads -- the programs moving the most value,
and the ones least interested in being read.

**And an IDL names; it does not state effect.** This is the distinction the
whole project rests on. An IDL will tell you an instruction is called
`set_authority` and takes an account named `new_authority`. It will not tell you
that `new_authority` is not a signer of this transaction, and that control is
therefore leaving the room with nobody present to speak for it. That is not a
naming problem and no IDL solves it. It is unsolved for all 25 programs,
including the 10 with excellent IDLs.

So the levels are not degrees of the same thing. Level 1 answers *what is this
called*. Level 2 answers *what will this do to me*. Only the second is a
question a signer can act on, and only the second is what this project builds.

**What this changed.** Modelling a program with a published IDL is meaningfully
cheaper than reverse-engineering one without, so pricing them identically was
wrong. The cost model is now tiered by a measured property of each named
program rather than by an average.

    python measurement/idl_availability.py

Pure Python, public RPC, no key. The ed25519 on-curve test needed for
`find_program_address` is implemented in the file rather than imported, so the
result stays reproducible by anyone.
