# Dormant

> **Live: [dormant-sigma.vercel.app](https://dormant-sigma.vercel.app)** -- the
> decoder runs on that page, in your browser. No install, no wallet, no RPC, no
> server behind it. It opens with a real transaction already read.
>
> **Solana Foundation reviewers:** the funding proposal is in
> [`GRANT.md`](GRANT.md) -- the 25 programs by ID, the acceptance test, the
> schedule, the budget, and the commands to verify every number yourself.

**What does this transaction do when it wakes up?**

A Solana transaction signed with a durable nonce does not expire. It sits,
valid, until someone submits it -- weeks or months later, against a state
nobody has seen yet. On 1 April 2026 that cost Drift Protocol $286M: attackers
spent months building trust, then got Security Council members to pre-sign
transactions that later transferred administrative control.

Dormant takes a signed, unexecuted transaction and says what it does, as a
condition rather than a guess.

**Live in the browser, nothing installed:**
https://claude.ai/code/artifact/3ec087a6-26a7-4df1-867b-febe649156e3

Paste a base64 transaction and read the verdict. The decoder and the semantics
library run inside the page -- no server, no RPC call, no telemetry, nothing
leaves your browser. A CLI cannot reach a signer at the moment of signing,
which is the only moment that matters; the page can. Source is `web/index.html`,
a direct port of `wire.py` and `semantics.py`, verified to give identical
verdicts on the same fixtures.

Or locally:

    python -m dormant <base64-or-base58-payload>

No network. No wallet. No account. It decodes the wire format itself, because
asking an RPC to parse a transaction you have not submitted defeats the
purpose.

## What it says

```
STOP. This transaction transfers control and never expires.

Both at once. In 10,336 signable mainnet transactions that combination
never occurred honestly -- not once.

00  System.AdvanceNonceAccount                            [NOTICE]
    Durable nonce. This transaction DOES NOT EXPIRE -- it stays valid
    until someone submits it, which may be months from now, against a
    state you cannot see.

01  BPFLoaderUpgradeable.SetAuthority                   [CRITICAL]
    Moves authority over UPGRADE AUTHORITY of program data 4vJ9..kLKi
    to CktR..Ezy8, which does NOT sign this transaction. Control leaves
    the room: nobody here speaks for the address about to hold it.
    checked: new authority CktR..Ezy8 is not a signer of this transaction
```

That is the Drift shape. The same transaction with `CktR..Ezy8` added as a
signer returns **NOTICE**, not CRITICAL -- because an ordinary authority
rotation has both parties present and consenting in the same transaction.

That distinction is the one precondition this actually computes, and it is the
whole design. Protocols rotate authority constantly; firing an alarm on every
rotation trains people to click through, which is precisely the habituation
that made blind signing normal. When the recipient does **not** sign, control
leaves the room -- nobody in the transaction speaks for the address about to
own it. The Drift attackers were never signers. They were destinations.

## Two rules it will not break

**Silence is never safety.** A program that is not in the semantics library
returns UNKNOWN, and so does an instruction tag we cannot name inside a program
we otherwise model. A tool that prints "no findings" for something it has never
seen teaches people to sign, which is how this class of loss happens.

**The durable nonce is a property of the whole transaction.** It changes what
signing *means* -- the signature stops being a decision about now and becomes a
decision about an unbounded future -- so it goes at the top, not buried at
instruction zero where it was in the real attack.

## Measured

### Does it stay quiet? The alarm budget

A detector is only useful if it fires on the bad thing AND stays silent
otherwise. The second half needs no users at all, only real traffic. Over 30
mainnet blocks, 30,861 transactions, with vote traffic excluded because no
human ever signs it -- **10,336 signable transactions**:

| class | count | rate |
|---|---|---|
| durable nonce alone | 841 | **8.14%** -- one in twelve |
| any control transfer | 14 | 0.135% -- one in 740 |
| upgrade authority transfer | 0 | none observed |
| **durable nonce AND control transfer** | **0** | **0.0000%** |

This measurement changed the design. A durable nonce on its own is **ordinary**,
so alerting on it would fire every twelfth transaction and teach people to click
through -- the same habituation the Drift signers were operating under. It is
reported as context now, not as an alarm.

The **conjunction** is the signal: control changing hands in a transaction that
never expires. Not seen once in 10,336. Zero is an upper bound rather than a
proof of never -- by the rule of three the true rate is under 0.029% at 95%
confidence -- and legitimate cases surely exist, since an offline-signed
authority rotation is a reasonable thing to do. They are simply rare enough
that one deserves a human's full attention.

### Does it understand what it sees? Coverage

Against mainnet slot 444,524,444:

| | |
|---|---|
| Decoder agreement with the RPC's own parse | **100.00%** (1,172/1,172, legacy + v0 + lookup tables) |
| Determined offline, all transactions | 60.6% |
| **Determined offline, excluding vote traffic** | **7.8%** |

The honest number is **7.8%**. The 60.6% figure is inflated by vote
transactions, which are 57% of a block and which nobody signs in a multisig.
For the population this tool exists to serve, it is silent nine times in ten
today.

Coverage, not cleverness, is the binding constraint -- and it is a ranked work
queue rather than a mystery. The tool reports which unmodelled programs it met
most often, so the next thing to build is always known.

## What this does NOT do

The strongest reason to distrust a security tool is a description that outruns
its code, so here is the boundary.

**One class of precondition is computed, not all of them.** Signer-presence for
the party receiving control is evaluated per transaction, from the payload
alone. Conditions over account *values* are not: there is no
`DANGEROUS whenever oracle 7xK.. reports above 4.2e9` here. That is a symbolic
execution result and it is not claimed.

**The actual Drift payloads have never been run through this.** They are not
public and I have not obtained them. What is demonstrated is that the *shape*
reported in the incident returns STOP, and that this shape occurred zero times
in 10,336 real signable transactions. That is a strong claim about base rates
and an unproven one about Drift specifically. If you have the payloads, that is
the single most useful thing you could send.

**Coverage is 7.8% of signable traffic.** Nine transactions in ten return
"cannot be read offline" today. The tool says so on every one of them rather
than implying safety, but do not picture a finished product.

## Layout

    dormant/wire.py       decode the transaction wire format, no dependencies
    dormant/semantics.py  what each instruction does to state -- the asset
    dormant/analyze.py    the report a signer reads
    dormant/__main__.py   the CLI
    dormant/web/          the browser build, a port of wire.py + semantics.py
    measurement/          the experiments that decided the design
    tests/                23 tests

    python -m pytest tests -q

Python 3.10+. No dependencies for the library itself; the measurement scripts
use `requests` against public RPC.

## Licence

MIT. The engine, the semantics library, the browser build, the CLI and the
corpus are free and stay free.
