const fs = require('fs');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');
const { color } = require('./utils');
const { loadAiConfig, redactConfig } = require('./ai');

const HOST = '127.0.0.1';
const PORT = Number(process.env.AI_TERMINAL_PORT) || 47631;
const DATA_DIR = path.join(__dirname, '.terminal');
const DAEMON_FILE = path.join(DATA_DIR, 'daemon.json');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');
const DAEMON_SCRIPT = path.join(__dirname, 'session-daemon.js');

function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

function requestJson(method, pathname, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : '';
    const req = http.request({
      host: HOST,
      port: PORT,
      method,
      path: pathname,
      headers: payload ? {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      } : {},
    }, (res) => {
      const chunks = [];
      res.setEncoding('utf8');
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const text = chunks.join('');
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (_) { data = { raw: text }; }
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(data);
        else reject(new Error(data && data.error ? data.error : `HTTP ${res.statusCode}`));
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function health() {
  return requestJson('GET', '/health');
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureDaemon() {
  try {
    return await health();
  } catch (_) {
    ensureDataDir();
    const child = spawn(process.execPath, [DAEMON_SCRIPT], {
      cwd: __dirname,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: { ...process.env, AI_TERMINAL_PORT: String(PORT) },
    });
    child.unref();
  }

  let lastErr = null;
  for (let i = 0; i < 40; i++) {
    try {
      return await health();
    } catch (err) {
      lastErr = err;
      await sleep(125);
    }
  }
  throw lastErr || new Error('session daemon failed to start');
}

function printJson(data) {
  console.log(JSON.stringify(data, null, 2));
}

function parseArgs(args) {
  const out = { rest: [] };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--cwd') { out.cwd = args[++i]; continue; }
    if (arg === '--name') { out.name = args[++i]; continue; }
    if (arg === '--lines') { out.lines = Number(args[++i]); continue; }
    if (arg === '--limit') { out.limit = Number(args[++i]); continue; }
    if (arg === '--no-pty') { out.pty = false; continue; }
    if (arg === '--json') { out.json = true; continue; }
    if (arg === '--attach') { out.attach = true; continue; }
    if (arg === '--follow') { out.follow = true; continue; }
    if (arg === '--force') { out.force = true; continue; }
    if (arg === '--enter') { out.enter = true; continue; }
    if (arg === '--stdin') { out.stdin = true; continue; }
    if (arg === '--base64') { out.base64 = true; continue; }
    if (arg === '--clear') { out.clear = true; continue; }
    if (arg === '--paste') { out.paste = true; continue; }
    if (arg === '--strategy') { out.strategy = args[++i]; continue; }
    out.rest.push(arg);
  }
  return out;
}

function commandFrom(parts) {
  return parts.join(' ').trim();
}

function showHelp() {
  console.log(`
${color.bold('session - PTY 会话和后台任务管理')}
${color.gray('─'.repeat(52))}
${color.cyan('命令:')}
  daemon                 启动或查看本地会话 daemon
  daemon stop|restart    停止或重启 daemon
  run <命令>             实时运行命令，直到命令结束
  start <命令>           后台启动长任务，返回 session id
  list                   列出会话
  tail <id>              查看会话尾部日志
  attach <id>            连接会话，转发输入并实时显示输出
  input <id> <文本>      向会话写入输入
  keys <id> <key...>     按语义发送按键，如 enter、ctrl+c、ctrl+u
  submit <id> <文本>     输入文本并提交，适合 Codex/TUI
  stop <id>              中断会话，--force 强制结束
  logs                   列出日志
  history                查看命令/会话历史
  config                 查看本地配置和模型配置

${color.cyan('示例:')}
  node session.js run "npm test"
  node session.js start "npm run dev" --name dev
  node session.js list
  node session.js tail <id> --lines 100
  node session.js attach <id>
  node session.js submit <id> "Reply only with TEST_OK."
  node session.js stop <id>
`);
}

async function startSession(args, attachAfter = false) {
  const parsed = parseArgs(args);
  const command = commandFrom(parsed.rest);
  if (!command) throw new Error('请指定命令');
  await ensureDaemon();
  const session = await requestJson('POST', '/sessions', {
    command,
    cwd: parsed.cwd || process.cwd(),
    name: parsed.name || '',
    pty: parsed.pty !== false,
  });

  if (parsed.json && !attachAfter) {
    printJson(session);
  } else {
    console.log(`${color.green('[SESSION]')} ${session.id} ${color.gray(session.backend)} pid=${session.pid}`);
    console.log(color.gray(`日志: ${session.logFile}`));
  }

  if (attachAfter || parsed.attach) {
    const final = await attachSession(session.id, { lines: 0, exitWhenDone: true });
    process.exit(typeof final.exitCode === 'number' ? final.exitCode : 0);
  }
}

async function listSessions(args) {
  const parsed = parseArgs(args);
  await ensureDaemon();
  const sessions = await requestJson('GET', '/sessions');
  if (parsed.json) return printJson(sessions);
  if (sessions.length === 0) {
    console.log(color.gray('没有会话'));
    return;
  }
  for (const s of sessions) {
    const status = s.status === 'running' ? color.green(s.status) : color.gray(s.status);
    console.log(`${s.id}  ${status}  ${s.backend}  pid=${s.pid || ''}  ${s.name || s.command}`);
  }
}

async function tailSession(args) {
  const parsed = parseArgs(args);
  const id = parsed.rest[0];
  if (!id) throw new Error('请指定 session id');
  await ensureDaemon();
  const result = await requestJson('GET', `/sessions/${encodeURIComponent(id)}/tail?lines=${parsed.lines || 80}`);
  if (parsed.json) return printJson(result);
  if (result.output) console.log(result.output);
  if (parsed.follow) await attachSession(id, { lines: 0, exitWhenDone: false });
}

async function getSession(id) {
  await ensureDaemon();
  return requestJson('GET', `/sessions/${encodeURIComponent(id)}`);
}

async function attachSession(id, options = {}) {
  await ensureDaemon();
  return new Promise((resolve, reject) => {
    const req = http.request({
      host: HOST,
      port: PORT,
      method: 'GET',
      path: `/sessions/${encodeURIComponent(id)}/stream?lines=${options.lines ?? 40}`,
    }, (res) => {
      res.setEncoding('utf8');
      res.on('data', (chunk) => process.stdout.write(chunk));
      res.on('end', async () => {
        cleanup();
        try {
          const session = await getSession(id);
          resolve(session);
        } catch (err) {
          reject(err);
        }
      });
    });

    req.on('error', reject);
    req.end();

    const stdin = process.stdin;
    const onData = async (data) => {
      const text = data.toString();
      if (text === '\x1d') {
        cleanup();
        req.destroy();
        resolve({ exitCode: 0, detached: true });
        return;
      }
      try {
        await requestJson('POST', `/sessions/${encodeURIComponent(id)}/input`, { data: text });
      } catch (err) {
        cleanup();
        reject(err);
      }
    };
    const cleanup = () => {
      stdin.off('data', onData);
      if (stdin.isTTY) stdin.setRawMode(false);
      stdin.pause();
    };

    if (stdin.isTTY) stdin.setRawMode(true);
    stdin.resume();
    stdin.on('data', onData);
    resCleanupOnExit(cleanup);
  });
}

function resCleanupOnExit(cleanup) {
  process.once('exit', cleanup);
  process.once('SIGINT', () => {
    cleanup();
    process.exit(130);
  });
}

function readStdinText() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on('data', (chunk) => chunks.push(chunk));
    process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    process.stdin.on('error', reject);
  });
}

async function inputSession(args) {
  const parsed = parseArgs(args);
  const id = parsed.rest.shift();
  if (!id) throw new Error('请指定 session id');
  const data = parsed.stdin
    ? await readStdinText()
    : (parsed.base64 ? Buffer.from(parsed.rest.join(''), 'base64').toString('utf8') : parsed.rest.join(' '));
  const finalData = data + (parsed.enter ? '\r' : '');
  await ensureDaemon();
  const result = await requestJson('POST', `/sessions/${encodeURIComponent(id)}/input`, { data: finalData });
  printJson(result);
}

async function keysSession(args) {
  const parsed = parseArgs(args);
  const id = parsed.rest.shift();
  if (!id) throw new Error('请指定 session id');
  if (!parsed.rest.length) throw new Error('请指定 key，例如 enter、ctrl+c、ctrl+u');
  await ensureDaemon();
  const result = await requestJson('POST', `/sessions/${encodeURIComponent(id)}/keys`, { keys: parsed.rest });
  printJson(result);
}

async function submitSession(args) {
  const parsed = parseArgs(args);
  const id = parsed.rest.shift();
  if (!id) throw new Error('请指定 session id');
  const text = parsed.stdin
    ? await readStdinText()
    : (parsed.base64 ? Buffer.from(parsed.rest.join(''), 'base64').toString('utf8') : parsed.rest.join(' '));
  await ensureDaemon();
  const result = await requestJson('POST', `/sessions/${encodeURIComponent(id)}/submit`, {
    text,
    clear: Boolean(parsed.clear),
    paste: Boolean(parsed.paste),
    strategy: parsed.strategy || 'enter',
  });
  printJson(result);
}

async function stopSessionCli(args) {
  const parsed = parseArgs(args);
  const id = parsed.rest[0];
  if (!id) throw new Error('请指定 session id');
  await ensureDaemon();
  const result = await requestJson('POST', `/sessions/${encodeURIComponent(id)}/stop`, { force: parsed.force });
  printJson(result);
}

async function stopDaemon() {
  try {
    return await requestJson('POST', '/shutdown', {});
  } catch (err) {
    if (fs.existsSync(DAEMON_FILE)) {
      try {
        const info = JSON.parse(fs.readFileSync(DAEMON_FILE, 'utf8').replace(/^\uFEFF/, ''));
        if (info.pid) {
          process.kill(info.pid);
          return { ok: true, pid: info.pid, fallback: true };
        }
      } catch (_) {
        // Fall through to the original error.
      }
    }
    return { ok: false, error: err.message };
  }
}

async function listLogs(args) {
  const parsed = parseArgs(args);
  await ensureDaemon();
  const logs = await requestJson('GET', `/logs?limit=${parsed.limit || 30}`);
  if (parsed.json) return printJson(logs);
  for (const log of logs) {
    console.log(`${log.modifiedAt}  ${String(log.size).padStart(8)}  ${log.path}`);
  }
}

async function showHistory(args) {
  const parsed = parseArgs(args);
  await ensureDaemon();
  const events = await requestJson('GET', `/history?limit=${parsed.limit || 50}`);
  if (parsed.json) return printJson(events);
  for (const event of events) {
    const label = event.type || 'event';
    const session = event.session ? event.session.id : event.id || '';
    const command = event.session ? event.session.command : '';
    console.log(`${event.time}  ${label.padEnd(14)} ${session} ${command}`);
  }
}

function readLocalConfig() {
  if (!fs.existsSync(CONFIG_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8').replace(/^\uFEFF/, ''));
  } catch (_) {
    return {};
  }
}

function writeLocalConfig(config) {
  ensureDataDir();
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
}

function showConfig(args) {
  const parsed = parseArgs(args);
  const command = parsed.rest[0];
  const key = parsed.rest[1];
  const value = parsed.rest.slice(2).join(' ');
  const config = readLocalConfig();

  if (command === 'set') {
    if (!key) throw new Error('config set 需要 key');
    config[key] = value;
    writeLocalConfig(config);
  }

  const output = {
    session: {
      host: HOST,
      port: PORT,
      daemonFile: DAEMON_FILE,
      localConfig: config,
    },
    ai: redactConfig(loadAiConfig()),
  };
  printJson(output);
}

async function main() {
  const args = process.argv.slice(2);
  const cmd = args.shift();

  if (!cmd || cmd === 'help' || cmd === '--help') {
    showHelp();
    return;
  }

  switch (cmd) {
    case 'daemon':
      if (args[0] === 'stop') {
        printJson(await stopDaemon());
      } else if (args[0] === 'restart') {
        await stopDaemon();
        await sleep(250);
        printJson(await ensureDaemon());
      } else {
        printJson(await ensureDaemon());
      }
      break;
    case 'run':
    case 'stream':
      await startSession(args, true);
      break;
    case 'start':
      await startSession(args, false);
      break;
    case 'list':
    case 'sessions':
      await listSessions(args);
      break;
    case 'tail':
      await tailSession(args);
      break;
    case 'attach': {
      const parsed = parseArgs(args);
      const id = parsed.rest[0];
      if (!id) throw new Error('请指定 session id');
      await attachSession(id, { lines: parsed.lines || 40 });
      break;
    }
    case 'input':
      await inputSession(args);
      break;
    case 'keys':
      await keysSession(args);
      break;
    case 'submit':
      await submitSession(args);
      break;
    case 'stop':
      await stopSessionCli(args);
      break;
    case 'logs':
      await listLogs(args);
      break;
    case 'history':
      await showHistory(args);
      break;
    case 'config':
      showConfig(args);
      break;
    default:
      throw new Error(`未知命令: ${cmd}`);
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.log(color.red(err.stack || err.message));
    process.exit(1);
  });
}

module.exports = {
  ensureDaemon,
  requestJson,
};
