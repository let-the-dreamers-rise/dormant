"""Decode a Solana transaction from its wire bytes, with no dependencies.

This has to work OFFLINE. The point of Dormant is to answer a question about a
transaction before anyone submits it, often before the network has ever seen
it, so asking an RPC to parse it defeats the exercise. A signer holding a
base64 payload must get an answer with no network at all.

Wire format, because getting this wrong silently is easy:

    transaction := compact_array(signature[64]) message
    message     := [0x80|version] header account_keys blockhash
                   compact_array(instruction) [address_table_lookups]
    header      := u8 num_required_signatures, u8 num_readonly_signed,
                   u8 num_readonly_unsigned
    instruction := u8 program_id_index, compact_array(u8 account_index),
                   compact_array(u8 data)

The leading byte of the message distinguishes versions: high bit set means the
low bits are the version (v0 today); otherwise it is a legacy message and that
byte is already num_required_signatures.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    num = int.from_bytes(raw, "big")
    out = ""
    while num:
        num, rem = divmod(num, 58)
        out = B58[rem] + out
    return "1" * pad + (out or "")


def b58decode(text: str) -> bytes:
    pad = len(text) - len(text.lstrip("1"))
    num = 0
    for ch in text:
        idx = B58.find(ch)
        if idx < 0:
            raise ValueError("not base58: %r" % ch)
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * pad + raw


class Cursor:
    """Byte reader that refuses to run off the end quietly."""

    def __init__(self, raw: bytes):
        self.raw, self.pos = raw, 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.raw):
            raise ValueError("truncated: wanted %d at %d of %d"
                             % (n, self.pos, len(self.raw)))
        out = self.raw[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def compact_u16(self) -> int:
        """Solana's ShortVec length prefix: 7 bits per byte, little endian."""
        value = shift = 0
        while True:
            byte = self.u8()
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift > 21:
                raise ValueError("compact-u16 too long")

    def done(self) -> bool:
        return self.pos >= len(self.raw)


@dataclass
class Account:
    pubkey: str
    signer: bool
    writable: bool
    # True when the key came from an address lookup table rather than the
    # message itself. Those pubkeys are NOT in the payload -- only a table
    # address and an index -- so offline analysis cannot name them.
    from_lookup: bool = False


@dataclass
class Instruction:
    program: str
    accounts: list = field(default_factory=list)   # list[Account]
    data: bytes = b""
    program_from_lookup: bool = False


@dataclass
class Transaction:
    version: str
    accounts: list = field(default_factory=list)
    instructions: list = field(default_factory=list)
    recent_blockhash: str = ""
    num_signatures: int = 0
    lookup_tables: list = field(default_factory=list)
    unresolved_lookups: int = 0


def _account_flags(i: int, n_keys: int, req_sig: int, ro_signed: int,
                   ro_unsigned: int) -> tuple:
    """Solana orders keys: writable signers, readonly signers, writable
    non-signers, readonly non-signers. Position alone gives the flags."""
    signer = i < req_sig
    if signer:
        writable = i < req_sig - ro_signed
    else:
        writable = i < n_keys - ro_unsigned
    return signer, writable


def decode(payload) -> Transaction:
    """Decode base64 text, base58 text, or raw bytes into a Transaction."""
    if isinstance(payload, str):
        text = payload.strip()
        try:
            raw = base64.b64decode(text, validate=True)
        except Exception:
            raw = b58decode(text)
    else:
        raw = bytes(payload)

    cur = Cursor(raw)
    n_sigs = cur.compact_u16()
    cur.take(64 * n_sigs)

    first = cur.u8()
    if first & 0x80:
        version = "v%d" % (first & 0x7F)
        req_sig = cur.u8()
    else:
        version = "legacy"
        req_sig = first
    ro_signed, ro_unsigned = cur.u8(), cur.u8()

    n_keys = cur.compact_u16()
    keys = [b58encode(cur.take(32)) for _ in range(n_keys)]
    blockhash = b58encode(cur.take(32))

    accounts = []
    for i, key in enumerate(keys):
        signer, writable = _account_flags(i, n_keys, req_sig, ro_signed,
                                          ro_unsigned)
        accounts.append(Account(key, signer, writable))

    n_ix = cur.compact_u16()
    raw_ix = []
    for _ in range(n_ix):
        prog_idx = cur.u8()
        idxs = [cur.u8() for _ in range(cur.compact_u16())]
        data = cur.take(cur.compact_u16())
        raw_ix.append((prog_idx, idxs, data))

    lookups, extra = [], []
    if version != "legacy" and not cur.done():
        for _ in range(cur.compact_u16()):
            table = b58encode(cur.take(32))
            wr = [cur.u8() for _ in range(cur.compact_u16())]
            ro = [cur.u8() for _ in range(cur.compact_u16())]
            lookups.append({"table": table, "writable": wr, "readonly": ro})
            # Loaded keys append after the message keys: all writable first,
            # then all readonly. Their pubkeys are not in this payload.
            extra.append((len(wr), len(ro), table))

    for n_wr, _, table in extra:
        for _ in range(n_wr):
            accounts.append(Account("lookup:%s" % table[:8], False, True, True))
    for _, n_ro, table in extra:
        for _ in range(n_ro):
            accounts.append(Account("lookup:%s" % table[:8], False, False, True))

    instructions = []
    for prog_idx, idxs, data in raw_ix:
        prog = accounts[prog_idx] if prog_idx < len(accounts) else None
        instructions.append(Instruction(
            program=prog.pubkey if prog else "?",
            accounts=[accounts[i] for i in idxs if i < len(accounts)],
            data=data,
            program_from_lookup=bool(prog and prog.from_lookup),
        ))

    return Transaction(
        version=version,
        accounts=accounts,
        instructions=instructions,
        recent_blockhash=blockhash,
        num_signatures=n_sigs,
        lookup_tables=lookups,
        unresolved_lookups=sum(1 for a in accounts if a.from_lookup),
    )
