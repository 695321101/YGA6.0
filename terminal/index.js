const fs = require('fs');
const path = require('path');
const { color } = require('./utils');

/**
 * 本地工具集 - 统一入口
 * 参考 Claude Code 工具设计，提供本地开发所需的全部工具
 */

const TOOLS_DIR = __dirname;

const TOOLS = {
  bash:    { file: 'bash.js',       desc: '命令执行 - 安全执行系统命令', main: 'main' },
  ai:      { file: 'ai.js',         desc: 'AI友好执行 - 结构化摘要、关键错误、完整日志', main: 'main' },
  session: { file: 'session.js',    desc: 'PTY会话 - 流式输出、后台任务、中断、历史日志', main: 'main' },
  logs:    { file: 'logs.js',       desc: '日志浏览 - 列表、读取、搜索终端日志', main: 'main' },
};

function showToolList() {
  console.log(`
${color.bold('本地工具集 v1.0.0')}
${color.gray('参考 Claude Code 设计的本地开发工具')}
${color.gray('═'.repeat(55))}

${color.cyan('可用工具:')}
`);
  for (const [name, tool] of Object.entries(TOOLS)) {
    const filePath = path.join(TOOLS_DIR, tool.file);
    const exists = fs.existsSync(filePath);
    const status = exists ? color.green('[OK]') : color.red('[缺失]');
    console.log(`  ${status} ${color.bold(name.padEnd(10))} ${tool.desc}`);
  }

  console.log(`
${color.cyan('使用方式:')}
  node index.js <工具名> [参数...]
  node index.js <工具名> --help

${color.cyan('示例:')}
  node index.js bash "npm install"
  node index.js ai exec "npm test"
  node index.js ai exec "npm test" --tail 80
  node index.js session run "npm test"
  node index.js session start "npm run dev" --name dev
  node index.js logs list
  node index.js logs latest --lines 80

${color.cyan('也可以直接调用单个工具:')}
  node bash.js "echo hello"
  node ai.js exec "npm test"
  node session.js list
  node logs.js search "error"
`);
}

// 直接调用工具（复用进程，避免 spawn 开销）
function invokeTool(toolFile, toolArgs) {
  // 模拟 process.argv 供子工具使用
  const oldArgv = process.argv;
  process.argv = [process.execPath, toolFile, ...toolArgs];

  try {
    const mod = require(toolFile);
    if (typeof mod.main === 'function') {
      mod.main();
    }
  } catch (err) {
    console.log(color.red(`执行失败: ${err.message}`));
    process.exit(err.status || 1);
  } finally {
    process.argv = oldArgv;
  }
}

// CLI 入口
const args = process.argv.slice(2);

if (args.length === 0 || args[0] === '--help' || args[0] === 'help') {
  showToolList();
  process.exit(0);
}

if (args[0] === '--check') {
  console.log(color.bold('工具完整性检查:'));
  let allOk = true;
  for (const [name, tool] of Object.entries(TOOLS)) {
    const filePath = path.join(TOOLS_DIR, tool.file);
    const exists = fs.existsSync(filePath);
    if (!exists) allOk = false;
    const status = exists ? color.green('OK') : color.red('缺失');
    console.log(`  [${status}] ${name} -> ${tool.file}`);
    if (exists) {
      try {
        require(filePath);
        console.log(`        ${color.green('模块加载正常')}`);
      } catch (err) {
        allOk = false;
        console.log(`        ${color.red('模块加载失败: ' + err.message)}`);
      }
    }
  }
  console.log(allOk ? color.green('\n所有工具检查通过') : color.red('\n部分工具存在问题'));
  process.exit(allOk ? 0 : 1);
}

const toolName = args[0];
const toolArgs = args.slice(1);

if (!TOOLS[toolName]) {
  console.log(color.red(`[ERROR] 未知工具: ${toolName}`));
  console.log(color.yellow(`可用工具: ${Object.keys(TOOLS).join(', ')}`));
  process.exit(1);
}

const toolFile = path.join(TOOLS_DIR, TOOLS[toolName].file);
if (!fs.existsSync(toolFile)) {
  console.log(color.red(`[ERROR] 工具文件缺失: ${toolFile}`));
  process.exit(1);
}

// 直接调用，替代 spawn 方式
invokeTool(toolFile, toolArgs);
