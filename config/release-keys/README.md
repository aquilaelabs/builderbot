# Publishers' release keys

The public keys BuilderBot checks a toolchain's download against where its
publisher signs instead of, or as well as, stating a checksum (R137):

- `node.asc`: Node.js's release team, every key named in
  https://github.com/nodejs/release-keys (keys.list), which signs each
  release's SHASUMS256.txt.
- `swift.asc`: Swift's signing keys, https://www.swift.org/keys/all-keys.asc,
  which sign each download (a `.sig` beside it).

A catalog row names its file (`source.checksum.signed.keys` or
`source.checksum.keys`); `scripts/lib/sdkmeta.py` and `scripts/lib/sdk.sh`
check with `gpgv` against these alone, never a keyring of the machine's.
When a publisher adds or rotates a key, this file is fetched again from the
address above and the change reviewed like any other.
