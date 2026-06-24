const color = {
  red: (t) => `\x1b[31m${t}\x1b[0m`,
  green: (t) => `\x1b[32m${t}\x1b[0m`,
  yellow: (t) => `\x1b[33m${t}\x1b[0m`,
  cyan: (t) => `\x1b[36m${t}\x1b[0m`,
  gray: (t) => `\x1b[90m${t}\x1b[0m`,
  bold: (t) => `\x1b[1m${t}\x1b[0m`,
  magenta: (t) => `\x1b[35m${t}\x1b[0m`,
};

// ========== ANSI 清除 ==========
function stripAnsi(text) {
  return String(text || '')
    .replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b[=>]/g, '');
}

// ========== 行处理 ==========
function splitLines(text) {
  return String(text || '').replace(/\r\n/g, '\n').split('\n').filter((line) => line.length > 0);
}

function tailLines(lines, limit = 40) {
  const count = Math.max(0, Number(limit) || 0);
  if (count === 0) return '';
  return lines.slice(-count).join('\n');
}

// ========== 命令历史管理 ==========
class CommandHistory {
  constructor(maxSize = 100) {
    this.maxSize = maxSize;
    this.history = [];
    this.index = -1;
  }

  add(cmd) {
    if (!cmd || cmd === this.history[this.history.length - 1]) return;
    this.history.push(cmd);
    if (this.history.length > this.maxSize) this.history.shift();
    this.index = this.history.length;
  }

  up() {
    if (this.history.length === 0) return null;
    this.index = Math.max(0, this.index - 1);
    return this.history[this.index];
  }

  down() {
    if (this.history.length === 0) return null;
    this.index = Math.min(this.history.length, this.index + 1);
    return this.index === this.history.length ? '' : this.history[this.index];
  }

  reset() {
    this.index = this.history.length;
  }
}

module.exports = { color, stripAnsi, splitLines, tailLines, CommandHistory };
