const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const { spawn } = require('child_process');
const { requestModelSummary } = require('./ai');

let pty = null;
try {
  pty = require('node-pty');
} catch (_) {
  pty = null;
}

const HOST = '127.0.0.1';
const PORT = Number(process.env.AI_TERMINAL_PORT) || 47631;
const DATA_DIR = path.join(__dirname, '.terminal');
const LOG_DIR = path.join(DATA_DIR, 'logs');
const DAEMON_FILE = path.join(DATA_DIR, 'daemon.json');
const HISTORY_FILE = path.join(DATA_DIR, 'history.jsonl');
const EVENTS_FILE = path.join(DATA_DIR, 'events.jsonl');
const MAX_RING_CHUNKS = 300;
const DEFAULT_EVENT_TAIL_LINES = 160;
const KEY_SEQUENCES = {
  enter: '\r',
  return: '\r',
  cr: '\r',
  linefeed: '\n',
  lf: '\n',
  ctrlj: '\n',
  tab: '\t',
  escape: '\x1b',
  esc: '\x1b',
  backspace: '\x7f',
  delete: '\x1b[3~',
  up: '\x1b[A',
  down: '\x1b[B',
  right: '\x1b[C',
  left: '\x1b[D',
  home: '\x1b[H',
  end: '\x1b[F',
  ctrlc: '\x03',
  ctrld: '\x04',
  ctrlu: '\x15',
  ctrlw: '\x17',
  ctrlz: '\x1a',
  shiftenter: '\x1b[13;2u',
};

const sessions = new Map();

function ensureDirs() {
  fs.mkdirSync(LOG_DIR, { recursive: true });
}

function nowIso() {
  return new Date().toISOString();
}

function makeId(command) {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const hash = crypto.createHash('sha1').update(`${command}\n${Date.now()}\n${Math.random()}`).digest('hex').slice(0, 8);
  return `${stamp}-${hash}`;
}

function stripAnsi(text) {
  return String(text || '')
    .replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b[=>]/g, '');
}

function appendHistory(event) {
  ensureDirs();
  fs.appendFileSync(HISTORY_FILE, `${JSON.stringify({ time: nowIso(), ...event })}\n`, 'utf8');
}

function makeEventId() {
  return `${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
}

function appendEvent(event) {
  ensureDirs();
  const record = { id: makeEventId(), time: nowIso(), ...event };
  fs.appendFileSync(EVENTS_FILE, `${JSON.stringify(record)}\n`, 'utf8');
  return record;
}

function readEvents(options = {}) {
  if (!fs.existsSync(EVENTS_FILE)) return [];
  const limit = Math.max(1, Number(options.limit) || 50);
  let events = fs.readFileSync(EVENTS_FILE, 'utf8')
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); } catch (_) { return { raw: line }; }
    });
  if (options.afterId) {
    const index = events.findIndex((event) => event.id === options.afterId);
    if (index >= 0) events = events.slice(index + 1);
  }
  if (options.sessionId) events = events.filter((event) => event.sessionId === options.sessionId);
  if (options.type) events = events.filter((event) => event.type === options.type);
  return events.slice(-limit);
}

function summarizeSession(session) {
  return {
    id: session.id,
    name: session.name,
    command: session.command,
    cwd: session.cwd,
    pid: session.pid,
    backend: session.backend,
    pty: session.backend === 'pty',
    status: session.status,
    exitCode: session.exitCode,
    signal: session.signal,
    createdAt: session.createdAt,
    endedAt: session.endedAt,
    durationMs: session.endedAt ? Date.parse(session.endedAt) - Date.parse(session.createdAt) : Date.now() - Date.parse(session.createdAt),
    logFile: path.relative(process.cwd(), session.logFile),
    bytes: session.bytes,
    summarizeOnExit: Boolean(session.summarizeOnExit),
  };
}

function writeSessionLogHeader(session) {
  fs.appendFileSync(session.logFile, [
    `session: ${session.id}`,
    `name: ${session.name || ''}`,
    `command: ${session.command}`,
    `cwd: ${session.cwd}`,
    `backend: ${session.backend}`,
    `createdAt: ${session.createdAt}`,
    '',
    '--- output ---',
    '',
  ].join('\n'), 'utf8');
}

function appendOutput(session, chunk) {
  const text = String(chunk || '');
  session.bytes += Buffer.byteLength(text);
  session.ring.push(text);
  if (session.ring.length > MAX_RING_CHUNKS) session.ring.shift();
  fs.appendFileSync(session.logFile, text, 'utf8');
  for (const res of session.subscribers) {
    res.write(text);
  }
}

function splitLines(text) {
  return String(text || '').replace(/\r\n/g, '\n').split('\n').filter((line) => line.length > 0);
}

function tailLines(lines, limit) {
  const count = Math.max(0, Number(limit) || 0);
  if (count === 0) return '';
  return lines.slice(-count).join('\n');
}

function collectFindings(output) {
  const patterns = [
    { level: 'error', regex: /\b(error|exception|traceback|failed|fatal|cannot find module|module_not_found|enoent|eaddrinuse)\b/i },
    { level: 'warning', regex: /\b(warn|warning|deprecated)\b/i },
  ];
  return splitLines(stripAnsi(output))
    .map((line, index) => ({ line: index + 1, text: line.trim() }))
    .filter((item) => item.text)
    .flatMap((item) => {
      const match = patterns.find((pattern) => pattern.regex.test(item.text));
      return match ? [{ stream: 'output', line: item.line, level: match.level, text: item.text }] : [];
    })
    .slice(0, 12);
}

function buildSessionResult(session, tailLineCount = DEFAULT_EVENT_TAIL_LINES) {
  const output = stripAnsi(getTail(session, tailLineCount));
  const lines = splitLines(output);
  const stillRunning = session.status === 'running';
  const success = !stillRunning && session.exitCode === 0;
  const keyFindings = collectFindings(output);
  const summary = stillRunning
    ? `命令仍在运行，当前尾部输出 ${lines.length} 行。`
    : `命令${success ? '成功' : '失败'}，退出码 ${session.exitCode}，尾部输出 ${lines.length} 行。`;
  const result = {
    schemaVersion: 1,
    command: session.command,
    cwd: session.cwd,
    success,
    exitCode: session.exitCode,
    durationMs: session.endedAt ? Date.parse(session.endedAt) - Date.parse(session.createdAt) : Date.now() - Date.parse(session.createdAt),
    timedOut: false,
    stillRunning,
    summary,
    keyFindings,
    signals: {
      stdoutLines: lines.length,
      stderrLines: 0,
      totalLines: lines.length,
      omittedStdoutLines: 0,
      omittedStderrLines: 0,
    },
    stdoutTail: output,
    stderrTail: '',
    outputTail: output,
    rawLogFile: path.relative(process.cwd(), session.logFile),
    session: summarizeSession(session),
    ai: null,
  };
  result.assessment = buildAssessment(result);
  return result;
}

function buildAssessment(result) {
  const error = (result.keyFindings || []).find((finding) => finding.level === 'error');
  const warning = (result.keyFindings || []).find((finding) => finding.level === 'warning');
  const status = result.stillRunning
    ? 'running'
    : (result.success ? (warning ? 'success_with_warnings' : 'success') : 'failed');
  const effective = result.success && !result.stillRunning;
  const importantLines = (result.keyFindings || []).slice(0, 6).map((finding) => finding.text);
  const nextSteps = result.stillRunning
    ? ['继续检查 events 或 tail，等待最终完成事件。']
    : (effective ? ['结果有效，可继续下一步。'] : ['优先处理 importantLines 中的错误。', '修复后重新运行命令验证。']);
  return {
    status,
    effective,
    needsAttention: !effective || Boolean(error || warning),
    summary: result.summary,
    cause: error ? error.text : (warning ? warning.text : ''),
    nextSteps,
    importantLines,
    exitCode: result.exitCode,
    durationMs: result.durationMs,
    rawLogFile: result.rawLogFile,
    source: 'daemon_exit_event',
    modelSummaryIsAdvisory: true,
    verification: {
      authoritative: true,
      basis: ['local_exit_code', 'local_log_tail', 'local_key_findings'],
      modelSummaryIsAdvisory: true,
      localEvidence: {
        success: result.success,
        exitCode: result.exitCode,
        timedOut: Boolean(result.timedOut),
        stillRunning: Boolean(result.stillRunning),
        durationMs: result.durationMs,
        rawLogFile: result.rawLogFile,
        importantLines: (result.keyFindings || []).slice(0, 8),
      },
      recommendedChecks: result.rawLogFile ? [
        {
          tool: 'terminal_call',
          args: { action: 'inspect', mode: 'logs', logAction: 'read', target: result.rawLogFile, lines: 200 },
          reason: '读取本地原始日志，复验模型摘要和本地 assessment。',
        },
        {
          tool: 'terminal_call',
          args: { action: 'inspect', mode: 'verify', target: result.rawLogFile, lines: 200 },
          reason: '使用纯本地规则重新分析日志，不调用模型。',
        },
      ] : [],
    },
  };
}

function publishCompletionEvents(session) {
  const result = buildSessionResult(session);
  appendEvent({
    type: 'session_completed',
    sessionId: session.id,
    session: summarizeSession(session),
    assessment: result.assessment,
    keyFindings: result.keyFindings,
    signals: result.signals,
    outputTail: result.outputTail,
    summarizeOnExit: Boolean(session.summarizeOnExit),
  });

  if (!session.summarizeOnExit) return;
  requestModelSummary(result)
    .then((ai) => {
      appendEvent({
        type: 'session_summary_ready',
        sessionId: session.id,
        session: summarizeSession(session),
        assessment: {
          ...result.assessment,
          modelSummary: ai && !ai.error ? {
            model: ai.model,
            summary: ai.summary || '',
            cause: ai.cause || '',
            nextSteps: ai.nextSteps || [],
            importantLines: ai.importantLines || [],
            advisory: true,
          } : {
            error: ai && ai.error ? ai.error : 'AI summary unavailable',
            advisory: true,
          },
        },
        ai,
      });
    })
    .catch((err) => {
      appendEvent({
        type: 'session_summary_error',
        sessionId: session.id,
        session: summarizeSession(session),
        error: err.message,
      });
    });
}

function finishSession(session, exitCode, signal, status = 'exited') {
  if (session.status !== 'running') return;
  session.status = status;
  session.exitCode = typeof exitCode === 'number' ? exitCode : null;
  session.signal = signal || null;
  session.endedAt = nowIso();
  appendHistory({ type: 'session_exit', session: summarizeSession(session) });
  for (const res of session.subscribers) {
    res.write(`\n[session ${session.id} ${session.status}: exitCode=${session.exitCode ?? ''} signal=${session.signal || ''}]\n`);
    res.end();
  }
  session.subscribers.clear();
  publishCompletionEvents(session);
}

function shellForCommand(command) {
  if (process.platform === 'win32') {
    return command
      ? { file: 'powershell.exe', args: ['-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command] }
      : { file: 'powershell.exe', args: ['-NoLogo', '-NoProfile'] };
  }
  return command
    ? { file: process.env.SHELL || 'bash', args: ['-lc', command] }
    : { file: process.env.SHELL || 'bash', args: [] };
}

function createSession(body) {
  const command = String(body.command || '').trim();
  if (!command && !body.shell) throw new Error('command is required');

  const id = makeId(command || 'shell');
  const cwd = path.resolve(body.cwd || process.cwd());
  const usePty = body.pty !== false && Boolean(pty);
  const logFile = path.join(LOG_DIR, `session-${id}.log`);
  const shell = shellForCommand(command);
  const session = {
    id,
    name: body.name || '',
    command: command || shell.file,
    cwd,
    pid: null,
    backend: usePty ? 'pty' : 'spawn',
    status: 'running',
    exitCode: null,
    signal: null,
    createdAt: nowIso(),
    endedAt: null,
    logFile,
    bytes: 0,
    ring: [],
    subscribers: new Set(),
    proc: null,
    summarizeOnExit: Boolean(body.summarizeOnExit),
  };

  ensureDirs();
  writeSessionLogHeader(session);

  if (usePty) {
    const term = pty.spawn(shell.file, shell.args, {
      name: 'xterm-256color',
      cols: Number(body.cols) || 120,
      rows: Number(body.rows) || 30,
      cwd,
      env: { ...process.env, ...(body.env || {}), TERM: 'xterm-256color' },
    });
    session.proc = term;
    session.pid = term.pid;
    term.onData((data) => appendOutput(session, data));
    term.onExit((event) => finishSession(session, event.exitCode, event.signal));
  } else {
    const child = spawn(shell.file, shell.args, {
      cwd,
      env: { ...process.env, ...(body.env || {}) },
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    session.proc = child;
    session.pid = child.pid;
    child.stdout.on('data', (data) => appendOutput(session, data));
    child.stderr.on('data', (data) => appendOutput(session, data));
    child.on('exit', (code, signal) => finishSession(session, code, signal));
    child.on('error', (err) => {
      appendOutput(session, `\n[spawn error] ${err.message}\n`);
      finishSession(session, 1, null, 'error');
    });
  }

  sessions.set(id, session);
  appendHistory({ type: 'session_start', session: summarizeSession(session) });
  return summarizeSession(session);
}

function getSession(id) {
  const session = sessions.get(id);
  if (!session) {
    const err = new Error(`session not found: ${id}`);
    err.statusCode = 404;
    throw err;
  }
  return session;
}

function getTail(session, lines = 80) {
  if (!fs.existsSync(session.logFile)) return '';
  const text = fs.readFileSync(session.logFile, 'utf8');
  const split = text.replace(/\r\n/g, '\n').split('\n');
  const value = Number(lines);
  const count = Math.max(0, Number.isFinite(value) ? value : 80);
  if (count === 0) return '';
  return split.slice(-count).join('\n').trimEnd();
}

function normalizeKeyName(key) {
  return String(key || '').replace(/[\s_+-]/g, '').toLowerCase();
}

function sequenceForKey(key) {
  const normalized = normalizeKeyName(key);
  const sequence = KEY_SEQUENCES[normalized];
  if (!sequence) throw new Error(`unsupported key: ${key}`);
  return sequence;
}

function decodeInputBody(body) {
  if (body && body.base64) return Buffer.from(String(body.data || ''), 'base64').toString('utf8');
  return String((body && body.data) || '');
}

function writeInput(id, data, meta = {}) {
  const session = getSession(id);
  if (session.status !== 'running') throw new Error(`session is not running: ${id}`);
  const text = String(data || '');
  if (session.backend === 'pty') {
    session.proc.write(text);
  } else if (session.proc.stdin) {
    session.proc.stdin.write(text);
  }
  appendHistory({
    type: meta.type || 'session_input',
    id,
    bytes: Buffer.byteLength(text),
    ...(meta.details || {}),
  });
  return { ok: true, id, bytes: Buffer.byteLength(text) };
}

function writeKeys(id, keys) {
  const list = Array.isArray(keys) ? keys : String(keys || '').split(/[,\s]+/).filter(Boolean);
  if (!list.length) throw new Error('keys is required');
  const data = list.map(sequenceForKey).join('');
  return {
    ...writeInput(id, data, { type: 'session_keys', details: { keys: list } }),
    keys: list,
  };
}

function submitInput(id, body) {
  const text = body && body.base64
    ? Buffer.from(String(body.text || ''), 'base64').toString('utf8')
    : String((body && body.text) || '');
  const strategy = String((body && body.strategy) || 'enter');
  const clear = Boolean(body && body.clear);
  const paste = Boolean(body && body.paste);
  const submitSequence = sequenceForKey(strategy);
  const payload = [
    clear ? KEY_SEQUENCES.ctrlu : '',
    paste ? `\x1b[200~${text}\x1b[201~` : text,
    submitSequence,
  ].join('');

  return {
    ...writeInput(id, payload, {
      type: 'session_submit',
      details: {
        strategy,
        clear,
        paste,
        textBytes: Buffer.byteLength(text),
      },
    }),
    strategy,
    clear,
    paste,
    textBytes: Buffer.byteLength(text),
  };
}

function deleteSession(id) {
  const session = getSession(id);
  const logFile = session.logFile;

  // 如果正在运行，先停止
  if (session.status === 'running') {
    stopSession(id, true);
  }

  // 从内存移除
  sessions.delete(id);

  // 删除日志文件
  if (fs.existsSync(logFile)) {
    try { fs.unlinkSync(logFile); } catch (_) {}
  }

  return { ok: true, id, deletedLog: logFile };
}

function stopSession(id, force = false) {
  const session = getSession(id);
  if (session.status !== 'running') return { ok: true, session: summarizeSession(session) };

  if (session.backend === 'pty') {
    if (!force) session.proc.write('\x03');
    setTimeout(() => {
      if (session.status === 'running') session.proc.kill();
    }, force ? 0 : 1500);
    } else {
    if (process.platform === 'win32' && session.pid) {
      const args = ['/PID', String(session.pid), '/T'];
      if (force) args.push('/F');
      spawn('taskkill', args, { windowsHide: true });
    } else {
      session.proc.kill(force ? 'SIGKILL' : 'SIGTERM');
    }
  }

  appendHistory({ type: 'session_stop', id, force: Boolean(force) });
  return { ok: true, session: summarizeSession(session) };
}

function readHistory(limit = 50) {
  if (!fs.existsSync(HISTORY_FILE)) return [];
  return fs.readFileSync(HISTORY_FILE, 'utf8')
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(-Math.max(1, Number(limit) || 50))
    .map((line) => {
      try { return JSON.parse(line); } catch (_) { return { raw: line }; }
    });
}

function listLogs(limit = 30) {
  ensureDirs();
  return fs.readdirSync(LOG_DIR)
    .map((name) => {
      const abs = path.join(LOG_DIR, name);
      const stat = fs.statSync(abs);
      return {
        name,
        path: path.relative(process.cwd(), abs),
        size: stat.size,
        modifiedAt: stat.mtime.toISOString(),
      };
    })
    .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
    .slice(0, Math.max(1, Number(limit) || 30));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8');
      if (!text) return resolve({});
      try { resolve(JSON.parse(text)); } catch (err) { reject(err); }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data, null, 2));
}

function notFound(res) {
  sendJson(res, 404, { error: 'not found' });
}

async function handle(req, res) {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);
  const parts = url.pathname.split('/').filter(Boolean);

  try {
    if (req.method === 'GET' && url.pathname === '/health') {
      return sendJson(res, 200, {
        ok: true,
        pid: process.pid,
        ptyAvailable: Boolean(pty),
        sessions: sessions.size,
      });
    }

    if (req.method === 'GET' && url.pathname === '/sessions') {
      return sendJson(res, 200, Array.from(sessions.values()).map(summarizeSession));
    }

    if (req.method === 'POST' && url.pathname === '/sessions') {
      const body = await readBody(req);
      return sendJson(res, 201, createSession(body));
    }

    if (req.method === 'GET' && parts[0] === 'sessions' && parts[1]) {
      const session = getSession(parts[1]);
      if (parts.length === 2) return sendJson(res, 200, summarizeSession(session));
      if (parts[2] === 'tail') {
        return sendJson(res, 200, {
          session: summarizeSession(session),
          output: getTail(session, url.searchParams.get('lines') || 80),
        });
      }
      if (parts[2] === 'stream') {
        res.writeHead(200, {
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        });
        const initial = getTail(session, url.searchParams.get('lines') || 40);
        if (initial) res.write(`${initial}\n`);
        if (session.status !== 'running') {
          res.end();
          return;
        }
        session.subscribers.add(res);
        req.on('close', () => session.subscribers.delete(res));
        return;
      }
    }

    if (req.method === 'POST' && parts[0] === 'sessions' && parts[1] && parts[2] === 'input') {
      const body = await readBody(req);
      return sendJson(res, 200, writeInput(parts[1], decodeInputBody(body)));
    }

    if (req.method === 'POST' && parts[0] === 'sessions' && parts[1] && parts[2] === 'keys') {
      const body = await readBody(req);
      return sendJson(res, 200, writeKeys(parts[1], body.keys));
    }

    if (req.method === 'POST' && parts[0] === 'sessions' && parts[1] && parts[2] === 'submit') {
      const body = await readBody(req);
      return sendJson(res, 200, submitInput(parts[1], body));
    }

    if (req.method === 'POST' && parts[0] === 'sessions' && parts[1] && parts[2] === 'stop') {
      const body = await readBody(req);
      return sendJson(res, 200, stopSession(parts[1], body.force));
    }

    if (req.method === 'DELETE' && parts[0] === 'sessions' && parts[1]) {
      return sendJson(res, 200, deleteSession(parts[1]));
    }

    if (req.method === 'POST' && parts[0] === 'sessions' && parts[1] && parts[2] === 'resize') {
      const body = await readBody(req);
      const session = getSession(parts[1]);
      if (session.backend === 'pty' && session.status === 'running') {
        session.proc.resize(Number(body.cols) || 120, Number(body.rows) || 30);
      }
      return sendJson(res, 200, { ok: true, session: summarizeSession(session) });
    }

    if (req.method === 'GET' && url.pathname === '/history') {
      return sendJson(res, 200, readHistory(url.searchParams.get('limit') || 50));
    }

    if (req.method === 'GET' && url.pathname === '/events') {
      return sendJson(res, 200, readEvents({
        limit: url.searchParams.get('limit') || 50,
        afterId: url.searchParams.get('afterId') || '',
        sessionId: url.searchParams.get('sessionId') || '',
        type: url.searchParams.get('type') || '',
      }));
    }

    if (req.method === 'GET' && url.pathname === '/logs') {
      return sendJson(res, 200, listLogs(url.searchParams.get('limit') || 30));
    }

    if (req.method === 'POST' && url.pathname === '/shutdown') {
      sendJson(res, 200, { ok: true, pid: process.pid });
      setTimeout(() => process.exit(0), 50);
      return;
    }

    return notFound(res);
  } catch (err) {
    return sendJson(res, err.statusCode || 500, { error: err.message });
  }
}

ensureDirs();
const server = http.createServer(handle);
server.listen(PORT, HOST, () => {
  fs.writeFileSync(DAEMON_FILE, JSON.stringify({
    pid: process.pid,
    host: HOST,
    port: PORT,
    startedAt: nowIso(),
    ptyAvailable: Boolean(pty),
  }, null, 2), 'utf8');
});

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
process.on('exit', () => {
  for (const session of sessions.values()) {
    if (session.status === 'running') {
      try { stopSession(session.id, true); } catch (_) {}
    }
  }
});
