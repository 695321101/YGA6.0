const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const http = require('http');
const https = require('https');
const { spawnSync } = require('child_process');
const { color } = require('./utils');

const DEFAULT_TIMEOUT = 60000;
const DEFAULT_TAIL_LINES = 40;
const DEFAULT_MAX_BUFFER = 20 * 1024 * 1024;
const DEFAULT_LLM_TIMEOUT = 30000;
const LOG_DIR = path.join(__dirname, '.terminal', 'logs');
const LOCAL_CONFIG_FILE = path.join(__dirname, '.ai-terminal.local.json');
const LOCAL_ENV_FILE = path.join(__dirname, '.env.local');

function stripAnsi(text) {
  return String(text || '')
    .replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b[=>]/g, '');
}

function parseEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const env = {};
  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

function readJsonFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
  } catch (err) {
    throw new Error(`配置文件解析失败: ${filePath} - ${err.message}`);
  }
}

function parseList(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  return String(value).split(',').map((item) => item.trim()).filter(Boolean);
}

function getConfigValue(sources, keys) {
  for (const source of sources) {
    for (const key of keys) {
      if (source[key] !== undefined && source[key] !== null && source[key] !== '') {
        return source[key];
      }
    }
  }
  return '';
}

function loadAiConfig() {
  const jsonConfig = readJsonFile(LOCAL_CONFIG_FILE);
  const fileEnv = parseEnvFile(LOCAL_ENV_FILE);
  const explicitEnv = {
    AI_API_BASE: process.env.AI_API_BASE,
    AI_API_KEY: process.env.AI_API_KEY,
    AI_MODEL: process.env.AI_MODEL,
    AI_PROXY_URL: process.env.AI_PROXY_URL,
    AI_PROXY_HOSTS: process.env.AI_PROXY_HOSTS,
    AI_LLM_TIMEOUT: process.env.AI_LLM_TIMEOUT,
  };
  const genericEnv = {
    OPENAI_BASE_URL: process.env.OPENAI_BASE_URL,
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    OPENAI_MODEL: process.env.OPENAI_MODEL,
    HTTPS_PROXY: process.env.HTTPS_PROXY,
    HTTP_PROXY: process.env.HTTP_PROXY,
  };
  const sources = [explicitEnv, fileEnv, jsonConfig, genericEnv];
  const config = {
    apiBase: getConfigValue(sources, ['AI_API_BASE', 'OPENAI_BASE_URL', 'api_base', 'apiBase']),
    apiKey: getConfigValue(sources, ['AI_API_KEY', 'OPENAI_API_KEY', 'api_key', 'apiKey']),
    model: getConfigValue(sources, ['AI_MODEL', 'OPENAI_MODEL', 'model']),
    proxyUrl: getConfigValue(sources, ['AI_PROXY_URL', 'HTTPS_PROXY', 'HTTP_PROXY', 'proxy_url', 'proxyUrl']),
    proxyHosts: parseList(getConfigValue(sources, ['AI_PROXY_HOSTS', 'proxy_hosts', 'proxyHosts'])),
    llmTimeout: Number(getConfigValue(sources, ['AI_LLM_TIMEOUT', 'llm_timeout', 'llmTimeout'])) || DEFAULT_LLM_TIMEOUT,
  };
  config.configured = Boolean(config.apiBase && config.apiKey && config.model);
  config.sources = {
    json: fs.existsSync(LOCAL_CONFIG_FILE),
    envLocal: fs.existsSync(LOCAL_ENV_FILE),
  };
  return config;
}

function redactConfig(config) {
  return {
    configured: config.configured,
    apiBase: config.apiBase || null,
    model: config.model || null,
    hasApiKey: Boolean(config.apiKey),
    proxyUrl: config.proxyUrl ? '[configured]' : '',
    proxyHosts: config.proxyHosts || [],
    llmTimeout: config.llmTimeout,
    sources: config.sources,
  };
}

function normalizeNewlines(text) {
  return stripAnsi(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function splitLines(text) {
  const normalized = normalizeNewlines(text);
  if (!normalized) return [];
  const lines = normalized.split('\n');
  if (lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function tailLines(lines, limit) {
  const value = Number(limit);
  const count = Math.max(0, Number.isFinite(value) ? value : DEFAULT_TAIL_LINES);
  if (count === 0) return '';
  return lines.slice(-count).join('\n').trimEnd();
}

function classifyLine(line) {
  const text = line.trim();
  if (!text) return null;

  const patterns = [
    { level: 'error', regex: /\b(error|failed|failure|fatal|exception|traceback|panic|segmentation fault)\b/i },
    { level: 'error', regex: /\b[A-Za-z_]*Error\b/ },
    { level: 'warning', regex: /\b(warn|warning|deprecated)\b/i },
    { level: 'npm', regex: /\bnpm ERR!|\bERR_PNPM|\bELIFECYCLE\b/i },
    { level: 'test', regex: /\b(assertion|expected|received|FAILED|FAIL|Tests?:|Suites?:)\b/i },
    { level: 'file', regex: /([A-Za-z]:)?[^<>"|?*\s]+\.(js|jsx|ts|tsx|py|java|c|cpp|go|rs|json|css|html|md|yml|yaml):\d+(:\d+)?/i },
    { level: 'file', regex: /File ".+\.(js|jsx|ts|tsx|py|java|c|cpp|go|rs)", line \d+/i },
  ];

  for (const pattern of patterns) {
    if (pattern.regex.test(text)) return pattern.level;
  }

  return null;
}

function collectFindings(stdoutLines, stderrLines, limit = 20) {
  const findings = [];

  function scan(lines, stream) {
    lines.forEach((line, index) => {
      const level = classifyLine(line);
      if (!level) return;
      findings.push({
        stream,
        line: index + 1,
        level,
        text: line.trim().slice(0, 500),
      });
    });
  }

  scan(stderrLines, 'stderr');
  scan(stdoutLines, 'stdout');

  const seen = new Set();
  return findings.filter((finding) => {
    const key = `${finding.stream}:${finding.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, limit);
}

function makeTimestamp(date = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join('') + '-' + [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('');
}

function ensureLogDir() {
  fs.mkdirSync(LOG_DIR, { recursive: true });
}

function writeLog(command, cwd, result) {
  ensureLogDir();
  const hash = crypto.createHash('sha1').update(`${cwd}\n${command}`).digest('hex').slice(0, 8);
  const fileName = `${makeTimestamp()}-${process.pid}-${hash}.log`;
  const absPath = path.join(LOG_DIR, fileName);
  const relPath = path.relative(process.cwd(), absPath);
  const content = [
    `command: ${command}`,
    `cwd: ${cwd}`,
    `success: ${result.success}`,
    `exitCode: ${result.exitCode}`,
    `durationMs: ${result.durationMs}`,
    `signal: ${result.signal || ''}`,
    '',
    '--- stdout ---',
    result.stdout || '',
    '',
    '--- stderr ---',
    result.stderr || '',
  ].join('\n');

  fs.writeFileSync(absPath, content, 'utf8');
  return relPath;
}

function buildSummary(command, result, stdoutLines, stderrLines, findings) {
  const lineCount = stdoutLines.length + stderrLines.length;
  if (result.success) {
    if (findings.length > 0) {
      return `命令成功，退出码 0，但输出中检测到 ${findings.length} 条需要关注的信号。`;
    }
    return `命令成功，退出码 0，共输出 ${lineCount} 行。`;
  }

  const primary = findings.find((finding) => (
    finding.level === 'error' && !/traceback|exception/i.test(finding.text)
  )) || findings.find((finding) => finding.level === 'error') || findings[0];
  const primaryText = primary ? `主要信号：${primary.text}` : '未提取到明确错误行，请查看尾部日志。';
  return `命令失败，退出码 ${result.exitCode}，共输出 ${lineCount} 行。${primaryText}`;
}

function buildChatUrl(apiBase) {
  const trimmed = String(apiBase || '').replace(/\/+$/, '');
  if (trimmed.endsWith('/chat/completions')) return trimmed;
  return `${trimmed}/chat/completions`;
}

function buildModelPrompt(result) {
  return JSON.stringify({
    command: result.command,
    cwd: result.cwd,
    success: result.success,
    exitCode: result.exitCode,
    durationMs: result.durationMs,
    timedOut: result.timedOut,
    localSummary: result.summary,
    keyFindings: result.keyFindings,
    signals: result.signals,
    stdoutTail: result.stdoutTail,
    stderrTail: result.stderrTail,
    rawLogFile: result.rawLogFile,
  }, null, 2);
}

function parseJsonish(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch (_) {
    const match = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (!match) return null;
    try {
      return JSON.parse(match[1].trim());
    } catch (__) {
      return null;
    }
  }
}

function postJson(url, payload, headers, timeoutMs) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const client = target.protocol === 'http:' ? http : https;
    const body = JSON.stringify(payload);
    const request = client.request({
      method: 'POST',
      hostname: target.hostname,
      port: target.port || undefined,
      path: `${target.pathname}${target.search}`,
      headers: {
        ...headers,
        'Content-Length': Buffer.byteLength(body),
      },
    }, (response) => {
      const chunks = [];
      response.setEncoding('utf8');
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        resolve({
          ok: response.statusCode >= 200 && response.statusCode < 300,
          status: response.statusCode,
          body: chunks.join(''),
        });
      });
    });

    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error('AI API 请求超时'));
    });
    request.on('error', reject);
    request.write(body);
    request.end();
  });
}

async function requestModelSummary(result, options = {}) {
  const config = options.config || loadAiConfig();
  if (!config.configured) {
    return {
      enabled: false,
      error: 'AI API 未配置，请设置 AI_API_BASE、AI_API_KEY、AI_MODEL 或 .ai-terminal.local.json。',
    };
  }

  const timeout = Number(options.llmTimeout) || config.llmTimeout;

  try {
    const response = await postJson(
      buildChatUrl(config.apiBase),
      {
        model: config.model,
        temperature: 0.2,
        max_tokens: 700,
        messages: [
          {
            role: 'system',
            content: [
              '你是一个本地 AI 终端的输出整理器。',
              '只根据用户提供的命令结果回答，不要编造不存在的日志。',
              '请用简洁中文输出 JSON，字段为 summary、cause、next_steps、important_lines。',
              'summary 用一句话说明结果；cause 写最可能原因；next_steps 是 1 到 4 条可执行步骤；important_lines 只摘取最关键日志。',
            ].join('\n'),
          },
          {
            role: 'user',
            content: buildModelPrompt(result),
          },
        ],
      },
      {
        Authorization: `Bearer ${config.apiKey}`,
        'Content-Type': 'application/json',
      },
      timeout,
    );

    if (!response.ok) {
      return {
        enabled: true,
        model: config.model,
        error: `AI API 请求失败: HTTP ${response.status}`,
        details: response.body.slice(0, 1000),
      };
    }

    const data = JSON.parse(response.body);
    const content = data.choices && data.choices[0] && data.choices[0].message
      ? data.choices[0].message.content
      : '';
    const parsed = parseJsonish(content);

    return {
      enabled: true,
      model: config.model,
      summary: parsed && parsed.summary ? parsed.summary : content.trim(),
      cause: parsed && parsed.cause ? parsed.cause : '',
      nextSteps: parsed && Array.isArray(parsed.next_steps) ? parsed.next_steps : [],
      importantLines: parsed && Array.isArray(parsed.important_lines) ? parsed.important_lines : [],
      raw: content.trim(),
    };
  } catch (err) {
    return {
      enabled: true,
      model: config.model,
      error: `AI API 请求异常: ${err.message}`,
    };
  }
}

function runAiExec(command, options = {}) {
  const cwd = path.resolve(options.cwd || process.cwd());
  const timeout = Number(options.timeout) || DEFAULT_TIMEOUT;
  const tailValue = Number(options.tail);
  const tail = Math.max(0, Number.isFinite(tailValue) ? tailValue : DEFAULT_TAIL_LINES);
  const start = Date.now();

  const child = spawnSync(command, {
    cwd,
    shell: true,
    encoding: 'utf8',
    timeout,
    maxBuffer: Number(options.maxBuffer) || DEFAULT_MAX_BUFFER,
    windowsHide: true,
  });

  const stdout = child.stdout || '';
  const stderr = child.error && !child.stderr ? String(child.error.message || child.error) : (child.stderr || '');
  const exitCode = typeof child.status === 'number' ? child.status : 1;
  const timedOut = child.error && child.error.code === 'ETIMEDOUT';
  const success = !child.error && exitCode === 0;
  const durationMs = Date.now() - start;
  const stdoutLines = splitLines(stdout);
  const stderrLines = splitLines(stderr);
  const findings = collectFindings(stdoutLines, stderrLines);
  const result = {
    success,
    exitCode: timedOut ? 124 : exitCode,
    durationMs,
    signal: child.signal || null,
    timedOut: Boolean(timedOut),
    stdout,
    stderr,
  };

  const structured = {
    schemaVersion: 1,
    command,
    cwd,
    success: result.success,
    exitCode: result.exitCode,
    durationMs: result.durationMs,
    timedOut: result.timedOut,
    summary: buildSummary(command, result, stdoutLines, stderrLines, findings),
    keyFindings: findings,
    signals: {
      stdoutLines: stdoutLines.length,
      stderrLines: stderrLines.length,
      totalLines: stdoutLines.length + stderrLines.length,
      omittedStdoutLines: Math.max(0, stdoutLines.length - tail),
      omittedStderrLines: Math.max(0, stderrLines.length - tail),
    },
    stdoutTail: tailLines(stdoutLines, tail),
    stderrTail: tailLines(stderrLines, tail),
    rawLogFile: null,
    ai: null,
  };

  if (options.log !== false) {
    structured.rawLogFile = writeLog(command, cwd, result);
  }

  return structured;
}

async function runAiExecWithModel(command, options = {}) {
  const result = runAiExec(command, options);
  result.ai = await requestModelSummary(result, options);
  return result;
}

function printJson(result) {
  console.log(JSON.stringify(result, null, 2));
}

function printPretty(result) {
  const status = result.success ? color.green('[PASS]') : color.red('[FAIL]');
  console.log(`${status} ${color.bold(result.summary)}`);
  console.log(color.gray(`退出码: ${result.exitCode} | 耗时: ${result.durationMs}ms | 日志: ${result.rawLogFile || '未保存'}`));

  if (result.ai && result.ai.enabled) {
    console.log(color.magenta('\nAI 摘要:'));
    if (result.ai.error) {
      console.log(color.yellow(result.ai.error));
      if (result.ai.details) console.log(color.gray(result.ai.details));
    } else {
      if (result.ai.summary) console.log(result.ai.summary);
      if (result.ai.cause) console.log(color.gray(`原因: ${result.ai.cause}`));
      if (result.ai.nextSteps && result.ai.nextSteps.length > 0) {
        console.log(color.gray('建议:'));
        for (const step of result.ai.nextSteps) console.log(`  - ${step}`);
      }
    }
  }

  if (result.keyFindings.length > 0) {
    console.log(color.cyan('\n关键信号:'));
    for (const item of result.keyFindings.slice(0, 10)) {
      console.log(`  ${item.stream}:${item.line} [${item.level}] ${item.text}`);
    }
  }

  if (result.stderrTail) {
    console.log(color.red('\nstderr 尾部:'));
    console.log(result.stderrTail);
  }

  if (result.stdoutTail) {
    console.log(color.gray('\nstdout 尾部:'));
    console.log(result.stdoutTail);
  }
}

function showHelp() {
  console.log(`
${color.bold('ai - AI 友好命令执行器')}
${color.gray('─'.repeat(45))}
${color.cyan('用法:')}  node ai.js exec <命令> [选项]

${color.cyan('选项:')}
  --cwd <路径>       工作目录
  --timeout <ms>     超时时间，默认 60000
  --tail <行数>      stdout/stderr 尾部保留行数，默认 40
  --llm             调用已配置的模型生成诊断摘要
  --pretty           输出人类可读摘要
  --no-log           不保存完整日志

${color.cyan('示例:')}
  node ai.js exec "npm test"
  node ai.js exec "npm test" --llm
  node ai.js exec "python correct_code.py" --pretty
  node index.js ai exec "npm test" --tail 80
  node ai.js config
`);
}

function parseCliArgs(args) {
  const options = {};
  const commandParts = [];
  let pretty = false;
  let useLlm = false;

  const rest = args[0] === 'exec' ? args.slice(1) : args;
  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i];
    if (arg === '--cwd') { options.cwd = rest[++i]; continue; }
    if (arg === '--timeout') { options.timeout = parseInt(rest[++i], 10); continue; }
    if (arg === '--tail') { options.tail = parseInt(rest[++i], 10); continue; }
    if (arg === '--llm') { useLlm = true; continue; }
    if (arg === '--no-llm') { useLlm = false; continue; }
    if (arg === '--pretty') { pretty = true; continue; }
    if (arg === '--no-log') { options.log = false; continue; }
    commandParts.push(arg);
  }

  return { command: commandParts.join(' '), options, pretty, useLlm };
}

if (require.main === module) {
  main().catch((err) => {
    console.log(color.red(err.stack || err.message));
    process.exit(1);
  });
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0 || args[0] === '--help' || args[0] === 'help') {
    showHelp();
    process.exit(0);
  }

  if (args[0] === 'config') {
    printJson(redactConfig(loadAiConfig()));
    process.exit(0);
  }

  const { command, options, pretty, useLlm } = parseCliArgs(args);
  if (!command) {
    console.log(color.red('请指定要执行的命令'));
    process.exit(1);
  }

  const result = useLlm ? await runAiExecWithModel(command, options) : runAiExec(command, options);
  if (pretty) printPretty(result);
  else printJson(result);
  process.exit(result.success ? 0 : 1);
}

module.exports = {
  loadAiConfig,
  redactConfig,
  requestModelSummary,
  runAiExec,
  runAiExecWithModel,
  printJson,
  printPretty,
};
