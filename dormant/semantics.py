"""What each instruction does to account state, and under what condition.

This file is the asset. An engine that computes preconditions is a weekend for
a competent team; knowing what 200 Solana programs actually do to state is
years, and every program added here permanently widens what can be analysed at
all. The census measured that coverage, not cleverness, is the binding
constraint: 41% of held-out mainnet transactions presented an instruction shape
never seen before.

The verdicts are deliberately few:

    SAFE        no authority moves, no unbounded value leaves a signer
    NOTICE      worth reading, not an alarm
    CRITICAL    control over an account or program changes hands

and each carries a PRECONDITION -- the condition on chain state under which the
verdict holds. `true` means it holds in every state the transaction can execute
in, which is the strongest thing that can be said offline and is exactly what
the Drift transactions would have returned.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SYSTEM = "11111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN22 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
LOADER_UPGRADEABLE = "BPFLoaderUpgradeab1e11111111111111111111111"
STAKE = "Stake11111111111111111111111111111111111111"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
VOTE = "Vote111111111111111111111111111111111111111"
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MEMO_LEGACY = "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"

SAFE, NOTICE, CRITICAL, UNKNOWN = "SAFE", "NOTICE", "CRITICAL", "UNKNOWN"


@dataclass
class Context:
    """What the rest of the transaction says, available to every rule.

    Only what is derivable from the payload itself -- no chain state, because
    the state this executes against does not exist yet.
    """
    signers: frozenset = frozenset()
    accounts: frozenset = frozenset()


def _unknown_tag(program: str, label: str, tag) -> "Finding":
    """An instruction tag this library does not recognise.

    Modelling a program is not the same as modelling every instruction in it.
    Programs add instructions; this file lags. Returning SAFE for a tag we
    cannot name would be the same mistake as returning SAFE for a program we
    have never seen, one level further down and considerably easier to miss.
    """
    return Finding(
        UNKNOWN, "%s.unknown(%s)" % (label, tag),
        "Instruction %s of %s is not in the semantics library. Its effect "
        "cannot be determined offline -- this is NOT a statement that it is "
        "safe." % (tag, label), "unknown", program)


@dataclass
class Finding:
    verdict: str
    operation: str
    statement: str
    precondition: str = "true"
    program: str = ""
    # True when the precondition was CHECKED against this payload and found to
    # hold; False when it is a genuine open condition on state that does not
    # exist yet. The difference matters to a reader: "this IS dangerous, here
    # is why" and "this BECOMES dangerous if" call for different actions, and
    # conflating them is how a tool sounds either alarmist or vague.
    evaluated: bool = True

    @property
    def unconditional(self) -> bool:
        return self.precondition == "true"


def _u32(data: bytes, off: int = 0):
    if len(data) < off + 4:
        return None
    return struct.unpack_from("<I", data, off)[0]


def _u64(data: bytes, off: int = 0):
    if len(data) < off + 8:
        return None
    return struct.unpack_from("<Q", data, off)[0]


def _short(pubkey: str) -> str:
    # ASCII only: this text is read in terminals whose encoding we do not pick.
    return pubkey if len(pubkey) <= 12 else pubkey[:4] + ".." + pubkey[-4:]


def _acct(ix, i: int) -> str:
    return _short(ix.accounts[i].pubkey) if i < len(ix.accounts) else "?"


def _recipient_present(pubkey: str, ctx) -> bool:
    """Is the party receiving control a signer of this very transaction?

    THIS IS THE PRECONDITION THAT IS ACTUALLY COMPUTED, and the distinction it
    draws is the difference between an alarm worth reading and noise.

    Protocols rotate authority constantly -- migrations, deploys, handing a
    program to governance. In an ordinary rotation the party taking control is
    a signer: they are present, and they consented in the same transaction.
    Firing CRITICAL on those would train people to click through, which is the
    habituation that made blind signing normal.

    When the recipient is NOT a signer, control leaves the room. Nobody in this
    transaction speaks for the address about to own the program. That is the
    Drift shape -- the attackers were never signers, they were destinations.

    Evaluated from the payload alone, with no chain state and no network.
    """
    if ctx is None:
        return False
    return pubkey in ctx.signers


def _authority_finding(program, operation, subject, new_authority, ctx,
                       what_they_can_do) -> "Finding":
    """One authority transfer, graded by whether the recipient is present."""
    known = _recipient_present(new_authority, ctx)
    target = _short(new_authority) if new_authority else "an unnamed account"
    if known:
        return Finding(
            NOTICE, operation,
            "Moves authority over %s to %s, which also SIGNS this transaction "
            "-- both parties are present. %s"
            % (subject, target, what_they_can_do),
            "new authority %s is a signer here" % target, program, True)
    return Finding(
        CRITICAL, operation,
        "Moves authority over %s to %s, which does NOT sign this transaction. "
        "Control leaves the room: nobody here speaks for the address about to "
        "hold it. %s" % (subject, target, what_they_can_do),
        "new authority %s is not a signer of this transaction" % target,
        program, True)


# --- System program -------------------------------------------------------
# Instruction tag is a little-endian u32.

SYSTEM_OPS = {
    0: "CreateAccount", 1: "Assign", 2: "Transfer", 3: "CreateAccountWithSeed",
    4: "AdvanceNonceAccount", 5: "WithdrawNonceAccount",
    6: "InitializeNonceAccount", 7: "AuthorizeNonceAccount", 8: "Allocate",
    9: "AllocateWithSeed", 10: "AssignWithSeed", 11: "TransferWithSeed",
    12: "UpgradeNonceAccount",
}


def system(ix, ctx=None) -> Finding:
    tag = _u32(ix.data)
    if tag not in SYSTEM_OPS:
        return _unknown_tag(SYSTEM, "System", tag)
    name = SYSTEM_OPS[tag]

    if tag == 4:
        return Finding(
            NOTICE, "System.AdvanceNonceAccount",
            "Durable nonce. This transaction DOES NOT EXPIRE -- it stays valid "
            "until someone submits it, which may be months from now, against a "
            "state you cannot see. Nonce account %s, authority %s."
            % (_acct(ix, 0), _acct(ix, 2)),
            "true", SYSTEM)
    if tag == 7:
        new_auth = ix.accounts[2].pubkey if len(ix.accounts) > 2 else ""
        return _authority_finding(
            SYSTEM, "System.AuthorizeNonceAccount",
            "nonce account %s" % _acct(ix, 0), new_auth, ctx,
            "The holder can mint further non-expiring transactions.")
    if tag == 1 or tag == 10:
        return Finding(
            CRITICAL, "System." + name,
            "Reassigns account %s to a different owning program. The new owner "
            "may rewrite its data freely." % _acct(ix, 0),
            "true", SYSTEM)
    if tag == 5:
        return Finding(
            CRITICAL, "System.WithdrawNonceAccount",
            "Withdraws lamports from nonce account %s to %s."
            % (_acct(ix, 0), _acct(ix, 1)),
            "true", SYSTEM)
    if tag in (2, 11):
        lamports = struct.unpack_from("<Q", ix.data, 4)[0] if len(ix.data) >= 12 else None
        return Finding(
            NOTICE, "System." + name,
            "Transfers %s lamports from %s to %s."
            % (lamports if lamports is not None else "?", _acct(ix, 0), _acct(ix, 1)),
            "true", SYSTEM)
    return Finding(SAFE, "System." + name,
                   "No authority change and no unbounded outflow.", "true", SYSTEM)


# --- SPL Token and Token-2022 --------------------------------------------
# Instruction tag is a single byte.

TOKEN_OPS = {
    0: "InitializeMint", 1: "InitializeAccount", 3: "Transfer", 4: "Approve",
    5: "Revoke", 6: "SetAuthority", 7: "MintTo", 8: "Burn", 9: "CloseAccount",
    10: "FreezeAccount", 11: "ThawAccount", 12: "TransferChecked",
    13: "ApproveChecked", 14: "MintToChecked", 15: "BurnChecked",
    17: "SyncNative", 18: "InitializeAccount3",
}
AUTHORITY_TYPES = {0: "MintTokens", 1: "FreezeAccount", 2: "AccountOwner",
                   3: "CloseAccount"}


def token(ix, program: str, ctx=None) -> Finding:
    if not ix.data:
        return Finding(SAFE, "Token.empty", "No instruction data.", "true", program)
    tag = ix.data[0]
    if tag not in TOKEN_OPS:
        return _unknown_tag(program, "Token", tag)
    name = TOKEN_OPS[tag]

    if tag == 6:
        kind = AUTHORITY_TYPES.get(ix.data[1] if len(ix.data) > 1 else -1, "?")
        has_new = len(ix.data) > 2 and ix.data[2] == 1
        if not has_new:
            return Finding(
                CRITICAL, "Token.SetAuthority",
                "Removes %s authority over %s permanently. No state can undo "
                "this." % (kind, _acct(ix, 0)), "true", program)
        from .wire import b58encode
        new_auth = b58encode(ix.data[3:35]) if len(ix.data) >= 35 else ""
        return _authority_finding(
            program, "Token.SetAuthority",
            "%s of %s" % (kind, _acct(ix, 0)), new_auth, ctx,
            "")
    if tag == 4 or tag == 13:
        delegate = ix.accounts[1].pubkey if len(ix.accounts) > 1 else ""
        return _authority_finding(
            program, "Token." + name,
            "spending on token account %s" % _acct(ix, 0), delegate, ctx,
            "A delegate may move funds later with no further signature "
            "from you.")
    if tag == 9:
        return Finding(
            NOTICE, "Token.CloseAccount",
            "Closes token account %s and sends its rent to %s."
            % (_acct(ix, 0), _acct(ix, 1)),
            "true", program)
    if tag in (3, 12):
        return Finding(
            NOTICE, "Token." + name,
            "Moves tokens from %s to %s." % (_acct(ix, 0), _acct(ix, -1 if tag == 3 else 2)),
            "balance of %s at execution time" % _acct(ix, 0), program,
            evaluated=False)
    if tag in (7, 14):
        return Finding(
            CRITICAL, "Token." + name,
            "Mints new supply of %s into %s." % (_acct(ix, 0), _acct(ix, 1)),
            "true", program)
    if tag == 10:
        return Finding(CRITICAL, "Token.FreezeAccount",
                       "Freezes token account %s." % _acct(ix, 0), "true", program)
    return Finding(SAFE, "Token." + name,
                   "No authority change.", "true", program)


# --- BPF Loader Upgradeable ----------------------------------------------
# The Drift vector. Tag is a little-endian u32.

LOADER_OPS = {0: "InitializeBuffer", 1: "Write", 2: "DeployWithMaxDataLen",
              3: "Upgrade", 4: "SetAuthority", 5: "Close", 6: "ExtendProgram",
              7: "SetAuthorityChecked"}


def loader(ix, ctx=None) -> Finding:
    tag = _u32(ix.data)
    if tag not in LOADER_OPS:
        return _unknown_tag(LOADER_UPGRADEABLE, "BPFLoaderUpgradeable", tag)
    name = LOADER_OPS[tag]

    if tag == 4:
        new_auth = ix.accounts[2].pubkey if len(ix.accounts) > 2 else ""
        return _authority_finding(
            LOADER_UPGRADEABLE, "BPFLoaderUpgradeable.SetAuthority",
            "UPGRADE AUTHORITY of program data %s" % _acct(ix, 0),
            new_auth, ctx,
            "Whoever holds it can replace the program's code, and therefore "
            "control every account the program owns.")

    # Tag 7 is tag 4 with one difference, and the difference is the entire
    # point of the instruction: the runtime REQUIRES the incoming authority to
    # sign. Control cannot leave the room through this instruction, because a
    # payload where it tried would be rejected before it executed. Grading it
    # the same as tag 4 would be the alarmism this library is built to avoid --
    # and one byte is all that separates the two on the wire.
    if tag == 7:
        new_auth = ix.accounts[2].pubkey if len(ix.accounts) > 2 else ""
        target = _short(new_auth) if new_auth else "an unnamed account"
        if _recipient_present(new_auth, ctx):
            return Finding(
                NOTICE, "BPFLoaderUpgradeable.SetAuthorityChecked",
                "Moves UPGRADE AUTHORITY of program data %s to %s, which "
                "signs this transaction. The checked variant will not accept "
                "an authority that is absent, so both parties are present by "
                "construction." % (_acct(ix, 0), target),
                "new authority %s is a signer here" % target,
                LOADER_UPGRADEABLE, True)
        return Finding(
            NOTICE, "BPFLoaderUpgradeable.SetAuthorityChecked",
            "Names %s as the incoming UPGRADE AUTHORITY of program data %s, "
            "but %s does not sign. The checked variant requires it to, so as "
            "written this instruction cannot execute -- it fails rather than "
            "hands anything over." % (target, _acct(ix, 0), target),
            "new authority %s must sign for this to execute at all" % target,
            LOADER_UPGRADEABLE, True)
    if tag == 3:
        return Finding(
            CRITICAL, "BPFLoaderUpgradeable.Upgrade",
            "REPLACES THE CODE of program %s with the contents of buffer %s."
            % (_acct(ix, 1), _acct(ix, 2)),
            "true", LOADER_UPGRADEABLE)
    if tag == 5:
        return Finding(CRITICAL, "BPFLoaderUpgradeable.Close",
                       "Closes program account %s, rendering it unusable."
                       % _acct(ix, 0), "true", LOADER_UPGRADEABLE)
    return Finding(SAFE, "BPFLoaderUpgradeable." + name,
                   "No authority or code change.", "true", LOADER_UPGRADEABLE)


# --- Stake ----------------------------------------------------------------

STAKE_OPS = {0: "Initialize", 1: "Authorize", 2: "DelegateStake", 3: "Split",
             4: "Withdraw", 5: "Deactivate", 6: "SetLockup", 7: "Merge",
             8: "AuthorizeWithSeed"}


def stake(ix, ctx=None) -> Finding:
    tag = _u32(ix.data)
    if tag not in STAKE_OPS:
        return _unknown_tag(STAKE, "Stake", tag)
    name = STAKE_OPS[tag]
    if tag in (1, 8):
        from .wire import b58encode
        new_auth = b58encode(ix.data[4:36]) if len(ix.data) >= 36 else ""
        return _authority_finding(
            STAKE, "Stake." + name,
            "stake account %s" % _acct(ix, 0), new_auth, ctx,
            "The holder controls where this stake and its rewards go.")
    if tag == 4:
        return Finding(NOTICE, "Stake.Withdraw",
                       "Withdraws from stake account %s to %s."
                       % (_acct(ix, 0), _acct(ix, 1)), "true", STAKE)
    return Finding(SAFE, "Stake." + name, "No authority change.", "true", STAKE)


# --- Vote -----------------------------------------------------------------
# 57% of the transactions in a mainnet block. Almost all of it is consensus
# housekeeping and harmless, but the authority and withdraw paths are how a
# validator gets taken over, so they must not be lumped in with the rest.

VOTE_OPS = {
    0: "InitializeAccount", 1: "Authorize", 2: "Vote", 3: "Withdraw",
    4: "UpdateValidatorIdentity", 5: "UpdateCommission", 6: "VoteSwitch",
    7: "AuthorizeChecked", 8: "UpdateVoteState", 9: "UpdateVoteStateSwitch",
    10: "AuthorizeWithSeed", 11: "AuthorizeCheckedWithSeed",
    12: "CompactUpdateVoteState", 13: "CompactUpdateVoteStateSwitch",
    14: "TowerSync", 15: "TowerSyncSwitch",
}
VOTE_CONSENSUS = {2, 6, 8, 9, 12, 13, 14, 15}


def vote(ix, ctx=None) -> Finding:
    tag = _u32(ix.data)
    if tag not in VOTE_OPS:
        return _unknown_tag(VOTE, "Vote", tag)
    name = VOTE_OPS[tag]
    if tag in (1, 7, 10, 11):
        from .wire import b58encode
        new_auth = b58encode(ix.data[4:36]) if len(ix.data) >= 36 else ""
        return _authority_finding(
            VOTE, "Vote." + name,
            "vote account %s" % _acct(ix, 0), new_auth, ctx,
            "The holder controls the validator's stake rewards.")
    if tag == 3:
        return Finding(CRITICAL, "Vote.Withdraw",
                       "Withdraws lamports from vote account %s to %s."
                       % (_acct(ix, 0), _acct(ix, 1)), "true", VOTE)
    if tag == 4:
        return Finding(CRITICAL, "Vote.UpdateValidatorIdentity",
                       "Reassigns the validator identity of vote account %s."
                       % _acct(ix, 0), "true", VOTE)
    if tag == 5:
        return Finding(NOTICE, "Vote.UpdateCommission",
                       "Changes commission on vote account %s." % _acct(ix, 0),
                       "true", VOTE)
    if tag in VOTE_CONSENSUS:
        return Finding(SAFE, "Vote." + name,
                       "Consensus housekeeping. Moves no value and changes no "
                       "authority.", "true", VOTE)
    return Finding(NOTICE, "Vote." + name, "Vote account maintenance.",
                   "true", VOTE)


# --- Associated Token Account --------------------------------------------
# Creating a token account for someone is not a way to take anything from
# them, which is why every instruction here is unconditionally safe.

def ata(ix) -> Finding:
    tag = ix.data[0] if ix.data else 0
    if tag == 0:
        return Finding(SAFE, "AssociatedToken.Create",
                       "Creates the associated token account for %s. Grants "
                       "no authority over existing funds." % _acct(ix, 2),
                       "true", ATA)
    if tag == 1:
        return Finding(SAFE, "AssociatedToken.CreateIdempotent",
                       "Creates the associated token account for %s if it does "
                       "not already exist." % _acct(ix, 2), "true", ATA)
    if tag == 2:
        return Finding(NOTICE, "AssociatedToken.RecoverNested",
                       "Recovers funds from a nested associated token account "
                       "into %s." % _acct(ix, 2), "true", ATA)
    return _unknown_tag(ATA, "AssociatedToken", tag)


def memo(ix, program: str) -> Finding:
    try:
        text = ix.data.decode("utf-8")[:60]
    except UnicodeDecodeError:
        text = "<non-utf8>"
    return Finding(SAFE, "Memo",
                   "Attaches a note; touches no account state. %r" % text,
                   "true", program)


# --- pump.fun AMM ---------------------------------------------------------
# The first program here that the RPC cannot name, and the top of the work
# queue by instruction volume. Everything below was recovered from mainnet
# rather than read out of a source file, by `measurement/discover.py`:
#
#   Operation names   The program's own runtime logs, attributed only in
#                     transactions that ran exactly ONE real instruction of it,
#                     so the mapping is unambiguous rather than correlational.
#
#   Argument layout   Tested, not assumed. If a 64-bit field is an amount, it
#                     has to equal a balance change the ledger recorded. Over
#                     five mainnet blocks the field at byte 8 matched an
#                     observed delta in 96.6% of Buy instructions (140/145) and
#                     73.9% of Sell (156/211); the field at byte 16 matched
#                     4.1% and 0.5%. So offset 8 is the amount, and offset 16
#                     is a bound the trade is permitted not to reach.
#
# Reproduce:
#   python measurement/discover.py --program pAMMBay6... --blocks 5
#   python measurement/discover.py --program pAMMBay6... --args 66063d1201daebea

PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

# sha256("anchor:event")[:8]. Anchor emits structured events by having the
# program invoke ITSELF with this discriminator, so an event appears in the
# ledger as an ordinary instruction. It is fully half of this program's
# apparent instruction volume and it changes no state -- which is worth saying
# out loud, because a work queue that counts events as operations makes every
# Anchor program look twice as big as it is.
ANCHOR_EVENT = "e445a52e51cb9a1d"

# discriminator -> (name, what the amount is, how the bound reads)
PUMP_OPS = {
    "66063d1201daebea": ("Buy", "receive", "spending at most"),
    "c62e1552b4d9e870": ("BuyExactQuoteIn", "receive", "spending at most"),
    "33e685a4017f83ad": ("Sell", "give up", "for at least"),
}


def pump_amm(ix, ctx=None) -> Finding:
    disc = ix.data[:8].hex() if len(ix.data) >= 8 else ""

    if disc == ANCHOR_EVENT:
        return Finding(
            SAFE, "pump.amm.event",
            "An Anchor event: the program invoking itself to record what it "
            "just did. Touches no account state.", "true", PUMP_AMM)

    op = PUMP_OPS.get(disc)
    if op is None:
        return _unknown_tag(PUMP_AMM, "pump.amm", disc or "<no discriminator>")

    name, direction, bound_word = op
    amount, bound = _u64(ix.data, 8), _u64(ix.data, 16)
    if amount is None:
        return _unknown_tag(PUMP_AMM, "pump.amm", disc)

    # Decimals live in the mint account, which is chain state this library
    # refuses to assume. Raw units are the honest unit to print.
    body = ("Swaps through a pump.fun AMM pool: you %s %s base units, %s %s "
            "quote units."
            % (direction, format(amount, ","), bound_word,
               format(bound, ",") if bound is not None else "an unread bound"))

    # The bound is the whole risk, and it is a condition on state that does not
    # exist yet. A swap signed today executes at whatever the pool offers when
    # it lands -- and if the payload also carries a durable nonce, "when it
    # lands" may be months from now, against a pool nobody has seen.
    return Finding(
        NOTICE, "pump.amm." + name,
        body + " The price is whatever the pool offers at execution; only "
        "that bound constrains it.",
        "pool price at execution stays within the stated bound",
        PUMP_AMM, False)


def analyse_instruction(ix, ctx=None) -> Finding:
    """The verdict for one instruction, or an explicit unknown.

    An unmodelled program returns UNKNOWN rather than SAFE. Reporting silence
    as safety is how a tool like this gets people hurt, and the census says
    this branch is taken for a large share of real traffic.
    """
    p = ix.program
    if p == SYSTEM:
        return system(ix, ctx)
    if p in (TOKEN, TOKEN22):
        return token(ix, p, ctx)
    if p == LOADER_UPGRADEABLE:
        return loader(ix, ctx)
    if p == STAKE:
        return stake(ix, ctx)
    if p == VOTE:
        return vote(ix, ctx)
    if p == ATA:
        return ata(ix)
    if p in (MEMO, MEMO_LEGACY):
        return memo(ix, p)
    if p == PUMP_AMM:
        return pump_amm(ix, ctx)
    if p == COMPUTE_BUDGET:
        return Finding(SAFE, "ComputeBudget", "Changes fees and limits only; "
                       "touches no account state.", "true", p)
    return Finding(
        UNKNOWN, "unmodelled",
        "Program %s is not in the semantics library. Its effect cannot be "
        "determined offline -- this is NOT a statement that it is safe."
        % _short(p), "unknown", p)


MODELLED = {SYSTEM, TOKEN, TOKEN22, LOADER_UPGRADEABLE, STAKE, COMPUTE_BUDGET,
            VOTE, ATA, MEMO, MEMO_LEGACY, PUMP_AMM}
