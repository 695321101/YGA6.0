const fs = require('fs');
const path = require('path');
const { color } = require('./utils');

const LOG_DIR = path.join(__dirname, '.terminal', 'logs');

function stripAnsi(text) {
  return String(text || '')
    .replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b[=>]/g, '');
}

function ensureLogDir() {
  fs.mkdirSync(LOG_DIR, { recursive: true });
}

function parseArgs(args) {
  const out = { rest: [] };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--limit') { out.limit = Number(args[++i]); continue; }
    if (arg === '--lines') { out.lines = Number(args[++i]); continue; }
    if (arg === '--raw') { out.raw = true; continue; }
    if (arg === '--json') { out.json = true; continue; }
    out.rest.push(arg);
  }
  return out;
}

function listLogs(limit = 30) {
  ensureLogDir();
  return fs.readdirSync(LOG_DIR)
    .map((name) => {
      const abs = path.join(LOG_DIR, name);
      const stat = fs.statSync(abs);
      return {
        name,
        path: path.relative(process.cwd(), abs),
        absPath: abs,
        size: stat.size,
        modifiedAt: stat.mtime.toISOString(),
      };
    })
    .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
    .slice(0, Math.max(1, Number(limit) || 30));
}

function resolveLog(input) {
  ensureLogDir();
  if (!input || input === 'latest') {
    const latest = listLogs(1)[0];
    if (!latest) throw new Error('没有日志文件');
    return latest.absPath;
  }

  const direct = path.resolve(input);
  if (fs.existsSync(direct)) return direct;

  const byName = path.join(LOG_DIR, input);
  if (fs.existsSync(byName)) return byName;

  const matches = listLogs(200).filter((log) => log.name.includes(input));
  if (matches.length === 1) return matches[0].absPath;
  if (matches.length > 1) {
    throw new Error(`匹配到多个日志，请更精确: ${matches.map((m) => m.name).join(', ')}`);
  }

  throw new Error(`日志不存在: ${input}`);
}

function readLog(input, lines, raw) {
  const file = resolveLog(input);
  let text = fs.readFileSync(file, 'utf8');
  if (!raw) text = stripAnsi(text);
  const split = text.replace(/\r\n/g, '\n').split('\n');
  const count = Number(lines);
  return {
    file,
    output: Number.isFinite(count) && count > 0 ? split.slice(-count).join('\n').trimEnd() : split.join('\n').trimEnd(),
  };
}

function searchLogs(pattern, limit = 50, raw = false) {
  if (!pattern) throw new Error('请指定搜索内容');
  const regex = new RegExp(pattern, 'i');
  const results = [];
  for (const log of listLogs(300)) {
    const text = fs.readFileSync(log.absPath, 'utf8').replace(/\r\n/g, '\n');
    const lines = text.split('\n');
    lines.forEach((line, index) => {
      const display = raw ? line : stripAnsi(line);
      if (regex.test(display)) {
        results.push({
          file: log.path,
          line: index + 1,
          text: display.trim(),
        });
      }
    });
    if (results.length >= limit) return results.slice(0, limit);
  }
  return results.slice(0, limit);
}

function showHelp() {
  console.log(`
${color.bold('logs - 日志浏览器')}
${color.gray('─'.repeat(40))}
${color.cyan('命令:')}
  list                 列出日志
  latest               查看最新日志
  read <日志名>         读取日志
  search <关键词>       搜索日志

${color.cyan('示例:')}
  node logs.js list
  node logs.js latest --lines 80
  node logs.js read session-xxx.log --lines 100
  node logs.js search "NameError"
`);
}

function printJson(data) {
  console.log(JSON.stringify(data, null, 2));
}

function main() {
  const args = process.argv.slice(2);
  const cmd = args.shift();

  if (!cmd || cmd === 'help' || cmd === '--help') {
    showHelp();
    return;
  }

  const parsed = parseArgs(args);
  if (cmd === 'list') {
    const logs = listLogs(parsed.limit || 30);
    if (parsed.json) return printJson(logs.map(({ absPath, ...rest }) => rest));
    for (const log of logs) {
      console.log(`${log.modifiedAt}  ${String(log.size).padStart(8)}  ${log.path}`);
    }
    return;
  }

  if (cmd === 'latest' || cmd === 'read') {
    const result = readLog(cmd === 'latest' ? 'latest' : parsed.rest[0], parsed.lines, parsed.raw);
    if (parsed.json) return printJson(result);
    console.log(color.gray(result.file));
    if (result.output) console.log(result.output);
    return;
  }

  if (cmd === 'search') {
    const results = searchLogs(parsed.rest.join(' '), parsed.limit || 50, parsed.raw);
    if (parsed.json) return printJson(results);
    for (const item of results) {
      console.log(`${item.file}:${item.line} ${item.text}`);
    }
    return;
  }

  throw new Error(`未知命令: ${cmd}`);
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.log(color.red(err.message));
    process.exit(1);
  }
}

module.exports = { listLogs, readLog, searchLogs };
