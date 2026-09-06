"""What has to be true before anyone signs anything on this tool's say-so.

The tests that matter most here are the negative ones: that an unmodelled
program is never reported as safe, and that a durable nonce is surfaced as a
property of the whole transaction. Both are ways this tool could get someone
hurt while appearing to work.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dormant.analyze import analyse, render
from dormant.semantics import (CRITICAL, LOADER_UPGRADEABLE, NOTICE, SAFE,
                               SYSTEM, TOKEN)
from dormant.wire import b58decode, b58encode, decode


# --- building transactions to test against --------------------------------

def compact(n: int) -> bytes:
    out = b""
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def key(seed: int) -> bytes:
    return bytes([seed]) * 32


def build(instructions, n_keys=8, req_sig=2, ro_signed=0, ro_unsigned=2,
          version=None):
    """A minimal legacy or v0 transaction carrying these instructions.

    `instructions` are (program_index, [account_indices], data).
    """
    body = b""
    if version is not None:
        body += bytes([0x80 | version])
    body += bytes([req_sig, ro_signed, ro_unsigned])
    body += compact(n_keys) + b"".join(key(i) for i in range(n_keys))
    body += key(200)                                    # recent blockhash
    body += compact(len(instructions))
    for prog, accts, data in instructions:
        body += bytes([prog]) + compact(len(accts)) + bytes(accts)
        body += compact(len(data)) + data
    if version is not None:
        body += compact(0)                              # no lookup tables
    return compact(1) + b"\x00" * 64 + body


# --- the wire format ------------------------------------------------------

def test_base58_roundtrips_including_leading_zeros():
    for raw in (b"\x00" * 32, bytes(range(32)), b"\x00\x00" + b"\xff" * 30):
        assert b58decode(b58encode(raw)) == raw


def test_compact_u16_handles_multibyte_lengths():
    tx = build([(0, [1, 2], b"\x02\x00\x00\x00")], n_keys=200)
    assert len(decode(tx).accounts) == 200


def test_legacy_and_v0_both_decode():
    ix = [(0, [1, 2], b"\x02\x00\x00\x00")]
    assert decode(build(ix)).version == "legacy"
    assert decode(build(ix, version=0)).version == "v0"


def test_signer_and_writable_flags_follow_key_order():
    tx = decode(build([(0, [1], b"")], n_keys=6, req_sig=2, ro_signed=1,
                      ro_unsigned=2))
    flags = [(a.signer, a.writable) for a in tx.accounts]
    assert flags[0] == (True, True)      # writable signer
    assert flags[1] == (True, False)     # readonly signer
    assert flags[2] == (False, True)     # writable non-signer
    assert flags[-1] == (False, False)   # readonly non-signer


def test_truncated_payload_raises_rather_than_guessing():
    tx = build([(0, [1], b"\x02\x00\x00\x00")])
    with pytest.raises(ValueError):
        decode(tx[:20])


# --- the semantics --------------------------------------------------------

def sysvar_ix(tag: int, extra: bytes = b"", accts=(1, 2, 3)):
    return build([(7, list(accts), struct.pack("<I", tag) + extra)], n_keys=8)


def test_an_unmodelled_program_is_UNKNOWN_and_never_safe():
    """The failure mode that would get someone hurt: silence read as safety."""
    # NB: key(0) is 32 zero bytes, which IS the System program. Use a key that
    # is not any real program instead -- an easy fixture bug to write.
    tx = build([(5, [1, 2], b"\xde\xad\xbe\xef")])
    report = analyse(tx)
    assert report.unmodelled == 1
    assert report.verdict == "UNKNOWN"
    assert report.findings[0].verdict != SAFE
    assert "NOT a statement that it is safe" in report.findings[0].statement


def test_durable_nonce_is_reported_on_the_whole_transaction():
    body = build([(7, [1, 2, 3], struct.pack("<I", 4))], n_keys=8)
    # index 7 must be the System program for this to be recognised
    raw = body.replace(key(7), b58decode(SYSTEM))
    report = analyse(raw)
    assert report.durable_nonce is True
    assert "DOES NOT EXPIRE" in report.findings[0].statement


def test_a_durable_nonce_ALONE_does_not_raise_an_alarm():
    """Measured at 8.14% of signable mainnet transactions -- one in twelve.
    Alerting here would be the noise that teaches people to stop reading, which
    is the habituation the Drift signers were operating under."""
    raw = build([(7, [1, 2, 3], struct.pack("<I", 4))], n_keys=8)
    raw = raw.replace(key(7), b58decode(SYSTEM))
    report = analyse(raw)
    assert report.drift_signature is False
    assert not report.headline.startswith("STOP")
    assert "!!" not in render(report)


def test_nonce_PLUS_control_transfer_is_the_signature_and_escalates():
    """Measured at 0 occurrences in 10,336 signable transactions. The
    conjunction is the signal; neither half is."""
    raw = build([(6, [1, 2, 3], struct.pack("<I", 4)),
                 (7, [1, 2, 4], struct.pack("<I", 4))], n_keys=8)
    raw = raw.replace(key(6), b58decode(SYSTEM))
    raw = raw.replace(key(7), b58decode(LOADER_UPGRADEABLE))
    report = analyse(raw)
    assert report.drift_signature is True
    assert report.headline.startswith("STOP")
    assert "0 in 10,336" in render(report)


def test_control_transfer_without_a_nonce_is_critical_but_not_the_signature():
    report = analyse(_with_program(struct.pack("<I", 4), LOADER_UPGRADEABLE))
    assert report.verdict == CRITICAL
    assert report.drift_signature is False


def _with_program(tag_data, program, prog_index=7, accts=(1, 2, 3)):
    raw = build([(prog_index, list(accts), tag_data)], n_keys=8)
    return raw.replace(key(prog_index), b58decode(program))


def test_upgrade_authority_to_a_NON_SIGNER_is_critical():
    """The Drift shape: control leaves the room. Account index 3 is not a
    signer, since only the first two keys are."""
    report = analyse(_with_program(struct.pack("<I", 4), LOADER_UPGRADEABLE,
                                   accts=(1, 2, 3)))
    f = report.findings[0]
    assert f.verdict == CRITICAL
    assert "does NOT sign" in f.statement
    assert "is not a signer" in f.precondition


def test_upgrade_authority_to_a_SIGNER_is_only_a_notice():
    """An ordinary rotation: the party taking control signs here too. Firing
    CRITICAL on these is what trains people to click through."""
    report = analyse(_with_program(struct.pack("<I", 4), LOADER_UPGRADEABLE,
                                   accts=(2, 3, 1)))   # index 1 IS a signer
    f = report.findings[0]
    assert f.verdict == NOTICE
    assert "also SIGNS" in f.statement
    assert report.verdict != CRITICAL


def test_the_precondition_is_computed_from_the_payload_not_hardcoded():
    """The same instruction yields different preconditions depending on who
    signs -- which is what makes it a computed condition rather than a label."""
    to_stranger = analyse(_with_program(struct.pack("<I", 4),
                                        LOADER_UPGRADEABLE, accts=(1, 2, 3)))
    to_signer = analyse(_with_program(struct.pack("<I", 4),
                                      LOADER_UPGRADEABLE, accts=(2, 3, 1)))
    assert to_stranger.findings[0].precondition != to_signer.findings[0].precondition
    assert to_stranger.findings[0].verdict != to_signer.findings[0].verdict


def test_program_code_replacement_is_critical():
    report = analyse(_with_program(struct.pack("<I", 3), LOADER_UPGRADEABLE))
    assert report.findings[0].verdict == CRITICAL
    assert "REPLACES THE CODE" in report.findings[0].statement


def test_token_set_authority_names_the_new_owner():
    data = bytes([6, 2, 1]) + key(42)          # SetAuthority, AccountOwner, Some
    report = analyse(_with_program(data, TOKEN))
    f = report.findings[0]
    assert f.verdict == CRITICAL           # key(42) signs nothing
    assert "AccountOwner" in f.statement


def test_token_authority_removal_is_flagged_not_silently_none():
    data = bytes([6, 2, 0])                    # SetAuthority, None
    report = analyse(_with_program(data, TOKEN))
    f = report.findings[0]
    assert f.verdict == CRITICAL
    assert "permanently" in f.statement
    assert f.unconditional      # no state can undo it, so no condition applies


def test_delegation_to_a_stranger_is_critical_because_it_outlives_this_signature():
    report = analyse(_with_program(bytes([4]), TOKEN, accts=(1, 3, 4)))
    f = report.findings[0]
    assert f.verdict == CRITICAL
    assert "no further signature" in f.statement


def test_a_plain_transfer_is_not_critical():
    data = struct.pack("<I", 2) + struct.pack("<Q", 1000)
    report = analyse(_with_program(data, SYSTEM))
    assert report.findings[0].verdict == NOTICE
    assert report.verdict != CRITICAL


def test_compute_budget_alone_is_safe_unconditionally():
    from dormant.semantics import COMPUTE_BUDGET
    report = analyse(_with_program(b"\x02\x00\x00\x00\x00", COMPUTE_BUDGET))
    assert report.verdict == SAFE
    assert report.headline.startswith("SAFE unconditionally")


def test_critical_beats_safe_when_a_transaction_mixes_both():
    """A dangerous instruction hidden among innocuous ones must dominate --
    which is exactly how the Drift payloads looked routine."""
    raw = build([(6, [1], b"\x02\x00\x00\x00\x00"),
                 (7, [1, 2, 3], struct.pack("<I", 4))], n_keys=8)
    from dormant.semantics import COMPUTE_BUDGET
    raw = raw.replace(key(6), b58decode(COMPUTE_BUDGET))
    raw = raw.replace(key(7), b58decode(LOADER_UPGRADEABLE))
    report = analyse(raw)
    assert report.verdict == CRITICAL
    assert report.headline.startswith("DANGEROUS")


def test_an_unknown_tag_inside_a_MODELLED_program_is_also_not_safe():
    """Modelling a program is not modelling every instruction in it. Programs
    add instructions and this library lags; the lag must read as UNKNOWN."""
    report = analyse(_with_program(struct.pack("<I", 9999), SYSTEM))
    assert report.verdict == "UNKNOWN"
    assert report.findings[0].verdict != SAFE
    assert "NOT a statement that it is safe" in report.findings[0].statement


def test_render_produces_something_a_person_can_read():
    out = render(analyse(_with_program(struct.pack("<I", 4), LOADER_UPGRADEABLE)))
    assert "DANGEROUS" in out
    assert "CRITICAL" in out
    assert "checked:" in out          # the condition was evaluated, not deferred


def test_an_evaluated_condition_reads_differently_from_an_open_one():
    """\"This IS dangerous, here is why\" and \"this BECOMES dangerous if\" ask
    the reader for different things; conflating them makes a tool sound either
    alarmist or vague."""
    evaluated = analyse(_with_program(struct.pack("<I", 4), LOADER_UPGRADEABLE))
    assert evaluated.headline.startswith("DANGEROUS --")
    assert evaluated.findings[0].evaluated is True

    open_cond = analyse(_with_program(bytes([3]), TOKEN))   # Token.Transfer
    assert open_cond.findings[0].evaluated is False
    assert "depends on" in render(open_cond)
