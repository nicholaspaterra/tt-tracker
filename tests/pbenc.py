"""Minimal protobuf ENCODER for building synthetic aiscore responses in tests.

The real captured fixture (tests/fixtures/matches_20260710.bin) proves the
parser against reality; these helpers build small controlled scenarios whose
expected outputs are computed by hand.
"""


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(fno, payload):
    """Length-delimited field (wire type 2)."""
    if isinstance(payload, str):
        payload = payload.encode()
    return varint(fno << 3 | 2) + varint(len(payload)) + payload


def vfield(fno, value):
    """Varint field (wire type 0)."""
    return varint(fno << 3 | 0) + varint(value)


def odds_set(values):
    """Odds-set message: repeated string field 1."""
    return b"".join(field(1, v) for v in values)


def odds_list_response(towin, book="bet365"):
    """Synthetic odds/list response in the documented layout:
    {15: {2: market{2: current odds-set}, 4: book-info{2: name}}}."""
    market = field(2, odds_set(towin))          # current odds
    info = field(2, book)
    block = field(2, market) + field(4, info)   # 2 = to-win market, 4 = book info
    return field(15, block)


def team(tid, name):
    return field(1, tid) + field(6, name)


def competition(cid, name):
    return field(1, cid) + field(5, name)


def match(mid, comp_id, home_id, away_id, start, status, ft=None, towin=None):
    b = field(1, mid)
    b += field(4, field(1, comp_id))
    b += field(6, field(1, home_id))
    b += field(7, field(1, away_id))
    b += vfield(15, start)
    b += vfield(16, status)
    if towin is not None:
        # {30: {7: {1: odds-set}}} — one to-win row [oh, "0", oa, "0"]
        row = field(1, odds_set(towin))
        b += field(30, field(7, row))
    if ft is not None:
        packed = varint(ft[0]) + varint(ft[1])
        b += field(111, field(8, packed))
    return b


def matches_response(comps, teams, matches):
    """Synthetic day-slate response: {15: {1: comp*, 2: match*, 3: team*}}."""
    body = b"".join(field(1, c) for c in comps)
    body += b"".join(field(2, m) for m in matches)
    body += b"".join(field(3, t) for t in teams)
    return field(15, body)
