"""A QR code as an SVG, for an authenticator app to scan (R127).

The dashboard takes no libraries, so this is the encoder: byte mode, error
correction level M, the smallest version that holds the text, the mask the
standard's penalty rules pick. Enough for an otpauth:// address, which is a
hundred-odd characters; anything up to version 40 encodes.
"""

# Level M, versions 1 to 40: error-correction codewords per block, and blocks.
_ECC = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
        26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]
_BLOCKS = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
           17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49]
_FORMAT_M = 0


def _raw_modules(ver):
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        al = ver // 7 + 2
        n -= (25 * al - 10) * al - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - _ECC[ver - 1] * _BLOCKS[ver - 1]


def _mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree):
    out = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _mul(root, 2)
    return out


def _remainder(data, div):
    out = [0] * len(div)
    for b in data:
        f = b ^ out.pop(0)
        out.append(0)
        for i, c in enumerate(div):
            out[i] ^= _mul(c, f)
    return out


def _codewords(text):
    data = text.encode("utf-8")
    for ver in range(1, 41):
        cap = _data_codewords(ver) * 8
        need = 4 + (8 if ver < 10 else 16) + 8 * len(data)
        if need <= cap:
            break
    else:
        raise ValueError("too long for a QR code")
    bits = []

    def put(v, n):
        bits.extend((v >> i) & 1 for i in range(n - 1, -1, -1))
    put(4, 4)
    put(len(data), 8 if ver < 10 else 16)
    for b in data:
        put(b, 8)
    put(0, min(4, cap - len(bits)))
    put(0, -len(bits) % 8)
    pad = [0xEC, 0x11]
    i = 0
    while len(bits) < cap:
        put(pad[i % 2], 8)
        i += 1
    words = [int("".join(map(str, bits[k:k + 8])), 2) for k in range(0, len(bits), 8)]
    nblocks, ecclen = _BLOCKS[ver - 1], _ECC[ver - 1]
    raw = _raw_modules(ver) // 8
    short_n = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = _divisor(ecclen)
    blocks, k = [], 0
    for b in range(nblocks):
        dlen = short_len - ecclen + (0 if b < short_n else 1)
        dat = words[k:k + dlen]
        k += dlen
        ecc = _remainder(dat, div)
        if b < short_n:
            dat = dat + [0]
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecclen or j >= short_n:
                out.append(blk[i])
    return ver, out


class _Grid:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set(self, x, y, dark):
        self.m[y][x] = dark
        self.fn[y][x] = True

    def functions(self):
        n = self.size
        for i in range(n):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        al = self._align()
        last = len(al) - 1
        for i, ax in enumerate(al):
            for j, ay in enumerate(al):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def _align(self):
        if self.ver == 1:
            return []
        al = self.ver // 7 + 2
        step = 26 if self.ver == 32 else (self.ver * 4 + al * 2 + 1) // (al * 2 - 2) * 2
        return [6] + sorted(self.size - 7 - i * step for i in range(al - 1))

    def format(self, mask):
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        b = [(bits >> i) & 1 == 1 for i in range(15)]
        n = self.size
        for i in range(6):
            self.set(8, i, b[i])
        self.set(8, 7, b[6])
        self.set(8, 8, b[7])
        self.set(7, 8, b[8])
        for i in range(9, 15):
            self.set(14 - i, 8, b[i])
        for i in range(8):
            self.set(n - 1 - i, 8, b[i])
        for i in range(8, 15):
            self.set(8, n - 15 + i, b[i])
        self.set(8, n - 8, True)

    def place(self, words):
        n, i = self.size, 0
        total = len(words) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    up = ((right + 1) & 2) == 0
                    y = n - 1 - vert if up else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def masked(self, mask):
        f = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m, score = self.size, self.m, 0
        for lines in (m, [list(c) for c in zip(*m, strict=True)]):
            for row in lines:
                run, prev = 0, None
                for v in row:
                    if v == prev:
                        run += 1
                    else:
                        if run >= 5:
                            score += run - 2
                        run, prev = 1, v
                if run >= 5:
                    score += run - 2
                s = "".join("1" if v else "0" for v in row)
                score += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(n - 1):
            for x in range(n - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(r) for r in m)
        k = (abs(dark * 20 - n * n * 10) + n * n - 1) // (n * n) - 1
        return score + max(0, k) * 10


def matrix(text):
    """The modules, rows of booleans, dark True."""
    ver, words = _codewords(text)
    best = None
    for mask in range(8):
        g = _Grid(ver)
        g.functions()
        g.place(words)
        g.masked(mask)
        g.format(mask)
        p = g.penalty()
        if best is None or p < best[0]:
            best = (p, g)
    return best[1].m


def svg(text, px=6):
    """The code as an SVG, black on white with the four-module quiet zone a
    scanner needs, whatever the page's theme."""
    m = matrix(text)
    n = len(m) + 8
    path = "".join(f"M{x + 4},{y + 4}h1v1h-1z" for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * px}" height="{n * px}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/>'
            f'<path d="{path}" fill="#000"/></svg>')
