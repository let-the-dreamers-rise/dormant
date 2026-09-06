"""The report a signer reads before signing.

Two things this refuses to do, both learned from how Drift actually happened:

1. **Silence is never safety.** An unmodelled program returns UNKNOWN, and the
   report says the effect could not be determined. A tool that renders "no
   findings" for a program it has never heard of teaches people to sign.
2. **The durable nonce is reported as a property of the whole transaction,**
   not as one instruction among others. It changes what signing MEANS -- the
   signature stops being a decision about now and becomes a decision about an
   unbounded future -- so it belongs at the top, not buried at position zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .semantics import (CRITICAL, MODELLED, NOTICE, SAFE, Context,
                        analyse_instruction)
from .wire import decode


@dataclass
class Report:
    version: str
    n_instructions: int
    findings: list = field(default_factory=list)
    durable_nonce: bool = False
    unresolved_lookups: int = 0
    unmodelled: int = 0

    @property
    def verdict(self) -> str:
        if any(f.verdict == CRITICAL for f in self.findings):
            return CRITICAL
        if self.unmodelled:
            return "UNKNOWN"
        if any(f.verdict == NOTICE for f in self.findings):
            return NOTICE
        return SAFE

    @property
    def drift_signature(self) -> bool:
        """A durable nonce AND a transfer of control, in one transaction.

        MEASURED, over 10,336 signable mainnet transactions (30 blocks, vote
        traffic excluded because no human signs it):

            durable nonce alone      8.1366%   1 in 12
            control transfer alone   0.1354%   1 in 740
            BOTH together            0.0000%   none

        That is the whole argument for this being one alert rather than two.
        A durable nonce on its own is ordinary -- alerting on it would fire
        every twelfth transaction and train people to click through, which is
        precisely the habituation that let the Drift signatures happen. The
        conjunction was never observed at all.

        Zero in 10,336 is an upper bound, not a proof of never: by the rule of
        three the true rate is under 0.029% with 95% confidence. Legitimate
        conjunctions surely exist -- an offline-signed authority rotation is a
        reasonable thing to do -- they are just rare enough that seeing one
        deserves a human's full attention.
        """
        return self.durable_nonce and any(
            f.verdict == CRITICAL for f in self.findings)

    @property
    def headline(self) -> str:
        """The one sentence, phrased as a precondition."""
        crits = [f for f in self.findings if f.verdict == CRITICAL]
        checked = [f for f in crits if f.evaluated and not f.unconditional]
        if self.drift_signature:
            return ("STOP. This transaction transfers control AND never "
                    "expires. That combination was not seen once in 10,336 "
                    "signable mainnet transactions. It is the shape of the "
                    "Drift attack.")
        if crits and all(f.unconditional for f in crits):
            return ("DANGEROUS UNCONDITIONALLY -- in every state this can "
                    "execute in, control changes hands.")
        if checked and len(checked) == len(crits):
            # Every dangerous condition was checked against this payload and
            # found to hold. Say so plainly rather than hedging with "whenever",
            # which reads as a hypothetical the reader still has to evaluate.
            return "DANGEROUS -- " + "; ".join(f.precondition for f in checked)
        if crits:
            return "DANGEROUS whenever: " + "; ".join(
                f.precondition for f in crits if not f.unconditional)
        if self.unmodelled:
            return ("UNDETERMINED -- %d instruction(s) are not in the "
                    "semantics library." % self.unmodelled)
        if self.unresolved_lookups:
            return ("UNDETERMINED -- %d account(s) come from address lookup "
                    "tables and are not named in this payload."
                    % self.unresolved_lookups)
        return "SAFE unconditionally -- no authority moves."


def analyse(payload) -> Report:
    tx = decode(payload)
    # The rest of the transaction is context for every rule. Signers matter
    # most: an authority moving to a signer is a rotation among parties who
    # are present; one moving elsewhere sends control out of the room.
    ctx = Context(
        signers=frozenset(a.pubkey for a in tx.accounts if a.signer),
        accounts=frozenset(a.pubkey for a in tx.accounts),
    )
    findings = [analyse_instruction(ix, ctx) for ix in tx.instructions]
    report = Report(
        version=tx.version,
        n_instructions=len(tx.instructions),
        findings=findings,
        durable_nonce=any(f.operation == "System.AdvanceNonceAccount"
                          for f in findings),
        unresolved_lookups=tx.unresolved_lookups,
        # Counts both programs we have never seen and instructions we cannot
        # name inside programs we have. Either way the effect is undetermined.
        unmodelled=sum(1 for f in findings if f.verdict == "UNKNOWN"),
    )
    return report


BADGE = {CRITICAL: "[CRITICAL]", NOTICE: "[notice]  ", SAFE: "[safe]    ",
         "UNKNOWN": "[UNKNOWN] "}


def render(report: Report) -> str:
    out = []
    out.append("=" * 72)
    out.append(report.headline)
    out.append("=" * 72)
    if report.drift_signature:
        out.append("")
        out.append("  !! CONTROL CHANGES HANDS, AND THIS NEVER EXPIRES.")
        out.append("     Whoever holds this payload can submit it at any moment")
        out.append("     they choose, including years from now. You are not")
        out.append("     deciding whether it is safe today.")
        out.append("     Base rate of this combination: 0 in 10,336.")
    elif report.durable_nonce:
        # Ordinary on its own -- 1 in 12 signable transactions -- so this is
        # context, not an alarm. Alerting here would be the noise that teaches
        # people to stop reading.
        out.append("")
        out.append("  note: durable nonce, so this does not expire. Common on")
        out.append("        its own (~8% of signable transactions).")
    out.append("")
    out.append("%s message, %d instruction(s)"
               % (report.version, report.n_instructions))
    out.append("")
    for i, f in enumerate(report.findings):
        out.append("%s %d. %s" % (BADGE.get(f.verdict, "[?]"), i, f.operation))
        for line in _wrap(f.statement, 66):
            out.append("              " + line)
        if not f.unconditional:
            label = "checked" if f.evaluated else "depends on"
            out.append("              %s: %s" % (label, f.precondition))
        out.append("")
    if report.unresolved_lookups:
        out.append("  %d account(s) resolve through address lookup tables and "
                   "cannot be" % report.unresolved_lookups)
        out.append("  named from this payload alone.")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines
