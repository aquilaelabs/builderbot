'use strict';
// ttyd's protocol over the controller's /term relay: the same terminal the
// dashboard opens, spoken from VS Code. One byte says what each message is
// ('0' input or output, '1' a resize or the window title, '2' ttyd's
// preferences); the first message is the auth token and the size, as JSON.
const { EventEmitter } = require('events');

const INPUT = '0', RESIZE = '1';
const OUTPUT = '0', TITLE = '1';

class Ttyd extends EventEmitter {
  // client: a Client (client.js); arg: what the dashboard puts after ?arg=,
  // `claude:PROJECT` for a project's Claude session, `codex:PROJECT` or
  // `copilot:PROJECT` for another coding agent's.
  constructor(client, arg) {
    super();
    this.client = client;
    this.arg = arg;
    this.sock = null;
    this.decoder = new TextDecoder();
  }

  async open(columns, rows) {
    const { sock, token } = await this.client.terminal(this.arg);
    this.sock = sock;
    sock.on('message', buf => {
      const kind = String.fromCharCode(buf[0]);
      const rest = buf.subarray(1);
      if (kind === OUTPUT) this.emit('output', this.decoder.decode(rest, { stream: true }));
      else if (kind === TITLE) this.emit('title', rest.toString('utf8'));
    });
    sock.on('close', () => this.emit('close'));
    sock.on('error', e => this.emit('error', e));
    sock.send(Buffer.from(JSON.stringify({ AuthToken: token, columns, rows })));
  }

  write(text) {
    if (this.sock) this.sock.send(Buffer.concat([Buffer.from(INPUT), Buffer.from(text, 'utf8')]));
  }

  resize(columns, rows) {
    if (this.sock) this.sock.send(Buffer.from(RESIZE + JSON.stringify({ columns, rows })));
  }

  close() {
    if (this.sock) this.sock.close();
  }
}

module.exports = { Ttyd };
