'use strict';
// BuilderBot's own terminal (R133) on the controller's /termws: the same
// terminal the dashboard's dock opens, spoken from VS Code. To the server a
// type byte (0 keys, 1 a resize as JSON cols/rows) and its body; from it
// the terminal's bytes. A close carries why the terminal ended.
const { EventEmitter } = require('events');

const KEYS = 0, RESIZE = 1;

class Term extends EventEmitter {
  // client: a Client (client.js); arg: the terminal's words, as the
  // dashboard's tab has them: `claude:PROJECT` for a project's Claude
  // session, `codex:PROJECT` or `copilot:PROJECT` for another coding agent's.
  constructor(client, arg) {
    super();
    this.client = client;
    this.arg = arg;
    this.sock = null;
    this.decoder = new TextDecoder();
  }

  async open(columns, rows) {
    const sock = await this.client.terminal(this.arg, columns, rows);
    this.sock = sock;
    sock.on('message', buf => this.emit('output', this.decoder.decode(buf, { stream: true })));
    sock.on('close', (code, why) => this.emit('close', why || ''));
    sock.on('error', e => this.emit('error', e));
  }

  send(kind, body) {
    if (this.sock) this.sock.send(Buffer.concat([Buffer.from([kind]), body]));
  }

  write(text) {
    this.send(KEYS, Buffer.from(text, 'utf8'));
  }

  resize(cols, rows) {
    this.send(RESIZE, Buffer.from(JSON.stringify({ cols, rows })));
  }

  close() {
    if (this.sock) this.sock.close();
  }
}

module.exports = { Term };
