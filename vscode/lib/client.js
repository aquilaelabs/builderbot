'use strict';
// BuilderBot's controller as the extension speaks to it: sign in as the
// person, then every call carries their own cookie and nothing wider. What
// they may do is decided by the server on every request (the Files API's
// gate, the terminal relay's); this file only carries the answers back.
const http = require('http');
const https = require('https');
const ws = require('./ws');

// The Files API version this extension speaks, said on every call with the
// extension's own release; the server says its own in the projects answer,
// and refuses one older than it keeps (426) in words this shows (R79 step 8).
const API = 1;
let RELEASE = '';
try { RELEASE = require('../package.json').version || ''; } catch { RELEASE = ''; }
const SAYS = { 'X-BB-Api': String(API), 'X-BB-App': `vscode/${RELEASE || '0.0.0'}` };

class Refused extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

function request(base, path, { method = 'GET', headers = {}, body = null, rejectUnauthorized = true } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(path, base);
    const secure = u.protocol === 'https:';
    const req = (secure ? https : http).request({
      host: u.hostname, port: u.port || (secure ? 443 : 80), path: u.pathname + u.search, method,
      headers: { Connection: 'close', ...headers, ...(body !== null ? { 'Content-Length': Buffer.byteLength(body) } : {}) },
      // A connection of its own each time: the dashboard answers one request
      // per connection, and Node's pool reusing a closed one hung up the next
      // request, a terminal's upgrade among them.
      agent: false,
      rejectUnauthorized,
    }, res => {
      const chunks = [];
      res.on('data', d => chunks.push(d));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
    if (body !== null) req.write(body);
    req.end();
  });
}

// The person's name and password for the cookie a browser would get: the
// same signed token, revoked by a password change or the account's removal.
// The password itself is never kept.
async function signIn(base, name, password, opts = {}) {
  const body = new URLSearchParams({ username: name, password, next: '/' }).toString();
  const r = await request(base, '/login', {
    method: 'POST', body, rejectUnauthorized: opts.rejectUnauthorized !== false,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  const set = [].concat(r.headers['set-cookie'] || []).map(c => /bb_session=([^;]+)/.exec(c)).find(Boolean);
  if (r.status !== 303 || !set || !set[1]) {
    throw new Refused(r.status, /Wrong username or password/.test(r.body.toString())
      ? 'Wrong username or password.' : `sign-in refused (${r.status})`);
  }
  return set[1];
}

class Client {
  constructor(base, cookie, opts = {}) {
    this.base = base.replace(/\/+$/, '');
    this.cookie = cookie;
    this.tls = opts.rejectUnauthorized !== false;
  }

  headers(extra = {}) {
    return { Cookie: `bb_session=${this.cookie}`, ...SAYS, ...extra };
  }

  async post(path, payload) {
    const r = await request(this.base, path, {
      method: 'POST', body: JSON.stringify(payload), rejectUnauthorized: this.tls,
      headers: this.headers({ 'Content-Type': 'application/json' }),
    });
    let j = {};
    try { j = JSON.parse(r.body.toString() || '{}'); } catch { j = {}; }
    if (r.status === 401 || (r.status >= 300 && r.status < 400)) {
      throw new Refused(401, 'Not signed in to BuilderBot, or the sign-in has expired: BuilderBot: Sign In.');
    }
    if (r.status >= 400) throw new Refused(r.status, j.error || `refused (${r.status})`, j);
    return j;
  }

  files(project, action, extra = {}) {
    return this.post('/api/v1/files', { action, project, ...extra });
  }

  // The projects this account may open in an editor, with its access to each.
  async projects() {
    const j = await this.post('/api/v1/files', { action: 'projects' });
    return { api: j.api, projects: j.projects || [], tooOld: controllerTooOld(j) };
  }

  // The dashboard's status, as the page reads it, for what opening an agent's
  // session needs of it (R128): the boot of the machine a new session starts
  // on, without which bb-tty attaches to a running session and starts none,
  // and which of this account's sessions run.
  async status() {
    const r = await request(this.base, '/api/status', { headers: this.headers(), rejectUnauthorized: this.tls });
    if (r.status === 401 || (r.status >= 300 && r.status < 400)) {
      throw new Refused(401, 'Not signed in to BuilderBot, or the sign-in has expired: BuilderBot: Sign In.');
    }
    let j = {};
    try { j = JSON.parse(r.body.toString() || '{}'); } catch { j = {}; }
    if (r.status >= 400) throw new Refused(r.status, j.error || `refused (${r.status})`, j);
    return j;
  }

  // A session's terminal: the dashboard's own relay at /term, so the same
  // checks decide whose terminal it is and whether it may be typed into.
  async terminal(arg) {
    const q = `?arg=${encodeURIComponent(arg)}`;
    const tok = await request(this.base, `/term/token${q}`, { headers: this.headers(), rejectUnauthorized: this.tls });
    let token = '';
    if (tok.status === 200) {
      try { token = JSON.parse(tok.body.toString()).token || ''; } catch { token = ''; }
    } else if (tok.status >= 400) {
      throw new Refused(tok.status, tok.body.toString().replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 300)
        || `the terminal was refused (${tok.status})`);
    }
    const url = this.base.replace(/^http/, 'ws') + `/term/ws${q}`;
    const sock = await ws.connect(url, { headers: this.headers(), protocols: ['tty'], rejectUnauthorized: this.tls });
    return { sock, token };
  }
}

// The plain sentence for a controller older than this extension, from the
// API its projects answer says (none said is 1), or ''. A newer controller
// keeps what this one reads, and refuses it outright once it does not.
function controllerTooOld(answer) {
  const said = (answer || {}).api;
  const theirs = said === undefined || said === null ? 1 : Number(said) || 0;
  return theirs >= API ? ''
    : `BuilderBot's Files API is version ${theirs} and this extension needs ${API}: update BuilderBot on the controller.`;
}

module.exports = { API, SAYS, Client, Refused, signIn, request, controllerTooOld };
