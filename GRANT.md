# Funding proposal: the semantics of Solana's 25 busiest opaque programs

*Submitted to the Solana Foundation, Developer Tooling. Every number in this
document is produced by a script in this repository that you can run yourself,
on a public endpoint, with no API key, in about ten minutes. The commands are at
the end.*

*The working decoder is at **<https://dormant-sigma.vercel.app>**, running in
the browser with no server behind it. It is the reference implementation of what
this proposal would extend to 25 programs, and it takes ten seconds to check.*

---

## The thirty-second version

**Naming Solana instructions is a solved problem. Saying what they do is not.**

Helius decodes 3,600+ programs from their on-chain IDLs. Shyft and deBridge ship
free, open-source parsers that do the same. Any claim that Solana transactions
are unreadable should be met with those three products, and this proposal does
not make that claim.

All three are **IDL-driven**, and that leaves two structural gaps:

**1. Fifteen of the twenty-five busiest opaque programs publish no IDL at all.**
Measured, not assumed. Helius states it "falls back to raw data and raw
accounts" for programs it cannot decode. Those fifteen are **12.4% of all
mainnet instruction volume**, they are disproportionately AMMs and launchpads,
and reaching them requires hand-written parsers that nobody has published.

**2. An IDL names; it never states effect.** It tells you an instruction is
`set_authority` taking an account named `new_authority`. It does not tell you
that `new_authority` never signs this transaction, so control is leaving the
room with nobody present to speak for it. That is the question a signer, an
indexer or a monitor actually needs answered, and **no IDL-derived tool answers
it for any program** -- including the ten in this list with excellent IDLs.

**I am asking for $45,000 to write effect semantics for the twenty-five busiest
opaque programs, and to publish the result as a free, MIT dataset.** They are
named by program ID below. Five milestones, each accepted against a number you
generate yourself, with the predicted number written in advance so a miss is
visible.

---

## You already asked for this. Nobody measured it.

In September 2024 the Foundation published an RFP titled Discriminator Database:

> Teams in the Solana ecosystem regularly face challenges interacting with
> unknown deployed contracts and **parsing unknown instructions**... which would
> lead to **an incremental increase in developer productivity and speed of
> interaction of Solana tooling**.

And on its forum thread:

> Generally speaking, **it is quite hard for data and monitoring teams to parse
> instructions cleanly.**

Its deadline passed in October 2024 and this is not a response to it. It is
cited because it is the Foundation stating, in writing and with a price, that
the problem is worth solving. What it did not contain was the size of the hole.

`measurement/parsing_gap.py`, two independent runs, inner and CPI instructions
included, vote traffic and ComputeBudget excluded so the denominator is honest:

| | run A | run B |
|---|---|---|
| non-vote transactions | 5,172 | 5,488 |
| instructions | 35,727 | 31,986 |
| **cannot be read by the RPC's own parser** | **42.1%** | **36.2%** |
| transactions containing at least one | **98.7%** | **87.6%** |
| distinct unreadable programs | 199 | 191 |

---

## The strongest objection to funding this, and what happened when I tested it

At full strength:

> *Your figure measures what the RPC's `jsonParsed` does, not what is knowable.
> Anchor programs can upload their IDL on chain. Cache those and much of the gap
> closes with a script, not hand-written semantics.*

`measurement/idl_availability.py` derives each program's Anchor IDL address and
asks the chain whether it exists. Of the top 25:

| | programs | share of top-25 volume |
|---|---|---|
| publish an on-chain Anchor IDL | **10** | **57.7%** |
| publish none | **15** | **42.3%** |

As shares of all mainnet instructions:

| level | reachable by | legible |
|---|---|---|
| 0 | the RPC alone, today | **63.8%** |
| 1 | + caching every on-chain IDL | **80.7%** |
| 2 | + semantics for the top 25 | **93.1%** |

**Level 1 is not hypothetical and it is not a weekend's work I am offering to
do. It is a shipped product, three times over.** Helius decodes 3,600+ programs
from their on-chain IDLs on its paid plans; Shyft and deBridge publish free,
open-source IDL parsers. If naming were the goal, the ecosystem is already
served and this proposal should be declined.

That is the honest state of the art, and it is why this proposal is not about
legibility in general. Two things survive it, and both are structural
consequences of every existing tool being IDL-driven.

**Fifteen of the twenty-five publish no IDL.** Helius states it "falls back to
raw data and raw accounts" for programs it cannot decode, and an IDL parser with
no IDL has nothing to parse. Those fifteen are **12.4% of all mainnet
instruction volume**. Reaching them means hand-written parsers, per program,
which is work somebody has to do and nobody has published.

**And an IDL names; it never states effect.** It tells you an instruction is
`set_authority` with an account named `new_authority`. It does not tell you that
`new_authority` never signs the transaction and that control is therefore
leaving the room. That is unsolved for all 25 programs, including the ten with
excellent IDLs, and it is unsolved by Helius, Shyft and deBridge alike -- they
deserialize arguments, which is a different and easier thing.

Level 1 answers *what is this called*, and is done. Level 2 answers *what will
this do to me*, and is what this proposal builds.

---

## The 25 programs

Ranked by instruction volume from `measurement/parsing_gap.py`. Regenerable.

| # | instructions | program | on-chain IDL |
|---|---|---|---|
| 1 | 1,662 | `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` | yes |
| 2 | 1,395 | `JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4` | yes |
| 3 | 1,158 | `EtrnLzgbS7nMMy5fbD42kXiUzGg8XQzJ972Xtk1cjWih` | no |
| 4 | 954 | `pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ` | yes |
| 5 | 479 | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` | yes |
| 6 | 443 | `FLUX6xBayGxLX9UcimVRxXFMHH6q43mAbRvDzSpCsvfK` | no |
| 7 | 390 | `TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH` | no |
| 8 | 294 | `Db8hf6HoijsAi6PZdXn4wByhB6LVrn17MPS6XprQBEwH` | no |
| 9 | 241 | `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` | no |
| 10 | 238 | `Prism8hsRo6Ww5jiN5Zeh3YDPLZHqHduCPSAV7JF7qv` | no |
| 11 | 204 | `CLEANALo6FtS6quqTTEXDGFFTuSKMkeKGgcweeiPRJzK` | yes |
| 12 | 186 | `Archer8kgiavM61GyusMzaaS2ft5sALtNsD1HxkUPMhy` | no |
| 13 | 180 | `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo` | yes |
| 14 | 166 | `dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN` | yes |
| 15 | 165 | `ojh19ojaKduoJZuaJADhcVGp4xt1TcdAvZmpVsCorch` | no |
| 16 | 149 | `QuaNtZsgYRe5Z9Bk4LZ4cTD9tbkVoyCNf1R2BN9bBDv` | no |
| 17 | 134 | `5kZmvKbaqNjSNEnQKEREEKu5r9JkaDRKrQMUvZagCMoz` | no |
| 18 | 130 | `cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG` | yes |
| 19 | 126 | `dijkbkCAKfFTCxQg3u1pg82gVU1jJGHBBRcteD11mBu` | no |
| 20 | 114 | `Gmso1uvJnLbawvw7yezdfCDcPydwW2s2iqG3w6MDucLo` | yes |
| 21 | 113 | `W1LDCARDa67SPBG7TFpQivHnEZXRtxCFP13ysEd1bWR` | no |
| 22 | 109 | `DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH` | yes |
| 23 | 108 | `phDEVv4w6BcfkLrLNeXr8HhhgQxnxziVGXpGPcaadMf` | no |
| 24 | 107 | `DhpyNWkdxFh3DRPsBrwRwrK3TYC5t7Q4arnSvf3t84HY` | no |
| 25 | 106 | `NA247a7YE9S3p9CdKmMyETx8TTwbSdVbVYHHxpnHTUV` | no |

The protocol identities are deliberately absent. A few are recognisable on
sight; the rest I will not fill in from memory in a funding document. The IDs,
volumes and IDL availability are measured. **Identification is the first
milestone's deliverable, not a precondition of it.**

---

## What "modelled" means

A program counts only when all four hold:

1. **Every instruction discriminant observed** for it across a 30-block mainnet
   sample is named with its effect on account state, or explicitly returns
   `UNKNOWN`. Silence is never reported as safety; that rule already holds in
   the shipped code and is not relaxed for coverage.
2. **At least one test per instruction**, covering the account-role mapping,
   passing in CI.
3. **`parsing_gap.py` shows the movement.** If the headline does not move by
   the amount the table predicts, the program is not done, however much code
   exists.
4. **Merged and published** in the dataset, under MIT.

The acceptance test is a number you generate, not a claim I make.

---

## Schedule

Five milestones, twenty weeks, $9,000 each. The last column is the number you
run.

Each tranche is **due upon completion** of its deliverable, not on signature.

| # | week | tranche | deliverable | `parsing_gap.py` reads |
|---|---|---|---|---|
| 1 | 2 | $9,000 | all 25 programs identified by protocol, each classified by IDL availability, published as a table | ~64% |
| 2 | 6 | $9,000 | 6 of 25 modelled, tested, merged | ~73% |
| 3 | 10 | $9,000 | 13 of 25 | ~82% |
| 4 | 15 | $9,000 | 20 of 25 | ~89% |
| 5 | 20 | $9,000 | 25 of 25, plus JSON and Parquet dumps, a queryable API, and an independent review published in full | ~93% |

The percentages are predictions from the cumulative curve already measured, and
they are falsifiable. If milestone 3 reads 74% instead of 82%, I have missed.

Milestone 1 is deliberately short and early. It is two weeks of work, it is
useful on its own -- a published map of which 25 programs carry the volume and
which of them can be read cheaply does not exist today -- and it means the first
payment is tied to something real rather than to a signature. Exposure is one
tranche at any time.

---

## Budget

| line | amount |
|---|---|
| 10 programs that publish an on-chain IDL, at $1,200 each | $12,000 |
| 15 programs that publish nothing, reverse-engineered from instruction data and observed state changes, at $2,200 each | $33,000 |
| **total** | **$45,000** |

The budget is two lines on purpose: tiered by a property that was measured, not
estimated. That is how the total was **derived**. What it is **spent on**:

| line | amount |
|---|---|
| Paid archival RPC access, five months -- historical transaction pulls and state-change replay | $1,500 |
| Dataset hosting and the queryable API, year one -- JSON and Parquet dumps, no key | $1,000 |
| Independent third-party review of the semantics, published in full at Milestone 5 | $4,000 |
| Engineering time, 20 weeks full-time, one person (~$1,925/week) | $38,500 |
| **total** | **$45,000** |

Paid archival RPC is not optional: recovering fifteen undocumented programs
means pulling large volumes of historical transactions and replaying observed
state changes, and public endpoints rate-limit and drop large blocks -- a
failure hit while running the measurement this proposal rests on. The
independent review is deliberate: a semantics dataset only I have checked is
worth less than one somebody competent has tried to break.

**The anchor.** The Discriminator Database RFP earmarked $60,000 to *name*
instructions ecosystem-wide, with a UI, an API and a dump. This proposes what
they *do to account state*, on the programs carrying ~93% of volume, with the
same distribution surface.

---

## Not in this proposal

Real work, deliberately excluded because I cannot promise the result:

- **Preconditions over account values** -- a symbolic-execution result. The
  engine today evaluates one class of precondition (whether the party receiving
  control signs the transaction) and does not claim more.
- **The Drift transactions themselves.** Their payloads are not public and I
  have not obtained them. What is shown is that the reported *shape* returns
  STOP, and that the shape occurred 0 times in 10,336 signable mainnet
  transactions.
- **Integration into a signing workflow**, which needs a partner who wants it.

---

## What happens if I stop

I am one person, and for a dataset meant to be depended on, maintenance matters
more than delivery. Pretending otherwise would be the weakest part of this
proposal, so here is how it is structured against that.

**The output is data, not a service.** Semantics are plain declarative entries
-- program, instruction discriminant, account roles, effect -- published as JSON
and Parquet under MIT. If I disappear, they keep working. Nothing expires,
nothing needs a server of mine, nothing is behind an API key of mine. That is a
deliberate difference from every commercial parser in this space.

**Each program is independently useful.** There is no all-or-nothing artefact.
Twelve programs modelled is twelve programs of coverage that the ecosystem keeps
regardless of what happens to the remaining thirteen, and `parsing_gap.py`
reports exactly how much was gained.

**The contribution path is the same one I use.** The ranked queue is generated,
not curated; the acceptance test is a script, not my judgement. Anyone who wants
to add the 26th program runs the same command, meets the same four conditions,
and opens a pull request. Bus factor is a property of processes that live in
one person's head, and this one deliberately does not.

**On being a student.** Milestone 4 lands in a period that may overlap exams,
and I would rather say so than discover it. The schedule is five milestones at
five-week intervals rather than a single twenty-week block precisely so slippage
is visible early and priced at one tranche, not five.

---

## Prior art, accurately

| | what it does | licence |
|---|---|---|
| **Helius** Parsed Events | decodes 3,600+ programs from their on-chain IDLs; falls back to raw data for the rest | paid, closed, open beta |
| **Shyft** transaction parser | IDL-based parsing plus hand-written parsers for System, Token, ATA | open source, free |
| **deBridge** transaction parser | decodes arbitrary instructions from an IDL or a custom scheme | open source, free |
| **Solscan / explorers** | display parsed instructions for programs they have registered | closed |

All of them name instructions and deserialize arguments. None of them states an
instruction's effect on account state, and all of them are IDL-driven, so all of
them degrade to raw bytes on the fifteen programs in this list that publish no
IDL. That is the gap, and it is narrow on purpose.

---

## Against the four published criteria

**Public good.** MIT, no crippled tier: engine, semantics library, browser tool,
CLI, and every measurement with its data. A novel proof of concept in a specific
sense: stating what an unexecuted transaction does as a condition on account
state, computed offline.

**Open source.** Everything, including the experiments that argued against this
proposal.

**Only possible on Solana.** Transactions declare every account they touch up
front, so the free variables of a precondition are finite, named and known
before execution. Ethereum's storage reads are discovered during execution, so
the variable set cannot be bounded in advance.

**Clear use of funds.** A named list, a unit price tiered by a measured
property, a stated split between external cost and engineering time, and a
pass/fail test you run.

---

## Verify all of it

```
git clone https://github.com/let-the-dreamers-rise/dormant && cd dormant
python -m pytest tests -q                       # 23 tests
python measurement/parsing_gap.py --blocks 12   # the gap, and the ranked queue
python measurement/idl_availability.py          # the objection, tested
python -m dormant <base64-transaction>          # the engine
```

Python 3.10+, standard library only for the engine and both gap measurements.
