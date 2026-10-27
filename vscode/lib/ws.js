'use strict';
// A websocket client in plain Node, for the terminal (RFC 6455, the client's
// half): the extension carries no dependencies and no build step, and the
// Node inside VS Code's extension host has no WebSocket of its own on every
// version the extension supports.
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const { EventEmitter } = require('events');

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

function frame(opcode, payload) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
  const n = body.length;
  const head = n < 126 ? Buffer.alloc(2) : n < 65536 ? Buffer.alloc(4) : Buffer.alloc(10);
  head[0] = 0x80 | opcode;
  if (n < 126) head[1] = 0x80 | n;
  else if (n < 65536) { head[1] = 0x80 | 126; head.writeUInt16BE(n, 2); }
  else { head[1] = 0x80 | 127; head.writeBigUInt64BE(BigInt(n), 2); }
  // A client masks every frame it sends.
  const mask = crypto.randomBytes(4);
  const out = Buffer.alloc(n);
  for (let i = 0; i < n; i++) out[i] = body[i] ^ mask[i & 3];
  return Buffer.concat([head, mask, out]);
}

class Socket extends EventEmitter {
  constructor(sock, rest) {
    super();
    this.sock = sock;
    this.buf = rest && rest.length ? Buffer.from(rest) : Buffer.alloc(0);
    this.parts = [];
    this.partOp = 0;
    this.closed = false;
    sock.on('data', d => { this.buf = Buffer.concat([this.buf, d]); this.parse(); });
    sock.on('close', () => this.done());
    sock.on('error', e => { this.emit('error', e); this.done(); });
    if (this.buf.length) setImmediate(() => this.parse());
  }

  parse() {
    for (;;) {
      const b = this.buf;
      if (b.length < 2) return;
      const fin = (b[0] & 0x80) !== 0, op = b[0] & 0x0f, masked = (b[1] & 0x80) !== 0;
      let n = b[1] & 0x7f, at = 2;
      if (n === 126) { if (b.length < 4) return; n = b.readUInt16BE(2); at = 4; }
      else if (n === 127) { if (b.length < 10) return; n = Number(b.readBigUInt64BE(2)); at = 10; }
      const key = masked ? b.subarray(at, at + 4) : null;
      if (masked) at += 4;
      if (b.length < at + n) return;
      let data = b.subarray(at, at + n);
      if (key) data = Buffer.from(data.map((x, i) => x ^ key[i & 3]));
      this.buf = b.subarray(at + n);
      if (op === 0x8) {
        // Its code and its words, which say why: the terminal's reason.
        this.code = data.length >= 2 ? data.readUInt16BE(0) : 1005;
        this.why = data.length > 2 ? data.subarray(2).toString('utf8') : '';
        this.close();
        return;
      }
      if (op === 0x9) { this.raw(0xA, data); continue; }
      if (op === 0xA) continue;
      if (op === 0x1 || op === 0x2) { this.partOp = op; this.parts = []; }
      if (op <= 0x2) {
        this.parts.push(Buffer.from(data));
        if (fin) {
          const all = Buffer.concat(this.parts);
          this.parts = [];
          this.emit('message', all, this.partOp === 0x2);
        }
      }
    }
  }

  raw(op, payload) {
    if (!this.closed) this.sock.write(frame(op, payload));
  }

  send(data, binary = true) {
    this.raw(binary ? 0x2 : 0x1, data);
  }

  close() {
    if (this.closed) return;
    try { this.sock.write(frame(0x8, Buffer.alloc(0))); } catch {}
    this.sock.end();
    this.done();
  }

  done() {
    if (this.closed) return;
    this.closed = true;
    this.emit('close', this.code || 1006, this.why || '');
  }
}

// Open `url` (ws: or wss:) with these headers and subprotocols: a Socket, or
// the server's refusal as an Error carrying its status and its words.
function connect(url, { headers = {}, protocols = [], rejectUnauthorized = true } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const secure = u.protocol === 'wss:' || u.protocol === 'https:';
    const key = crypto.randomBytes(16).toString('base64');
    const req = (secure ? https : http).request({
      host: u.hostname, port: u.port || (secure ? 443 : 80), path: u.pathname + u.search, method: 'GET',
      agent: false,                // never a pooled connection the server has closed
      rejectUnauthorized,
      headers: {
        ...headers, Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': key, ...(protocols.length ? { 'Sec-WebSocket-Protocol': protocols.join(', ') } : {}),
      },
    });
    req.on('upgrade', (res, sock, head) => {
      const want = crypto.createHash('sha1').update(key + GUID).digest('base64');
      if (res.headers['sec-websocket-accept'] !== want) {
        sock.destroy();
        return reject(new Error('the server answered the upgrade with the wrong key'));
      }
      resolve(new Socket(sock, head));
    });
    req.on('response', res => {
      let body = '';
      res.on('data', d => { body += d; });
      res.on('end', () => {
        const e = new Error(`${res.statusCode}: ${body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 300)}`);
        e.status = res.statusCode;
        reject(e);
      });
    });
    req.on('error', reject);
    req.end();
  });
}

module.exports = { connect, frame };
