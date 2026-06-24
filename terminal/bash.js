const { execSync } = require('child_process');
const { color } = require('./utils');

/**
 * Bash - 命令执行工具
 * 安全执行系统命令，捕获输出和错误，支持超时、工作目录
 */
function bashExec(command, options = {}) {
  const { cwd = process.cwd(), timeout = 60000, shell = true } = options;
  const start = Date.now();

  try {
    const stdout = execSync(command, {
      cwd,
      encoding: 'utf-8',
      timeout,
      stdio: ['pipe', 'pipe', 'pipe'],
      shell,
    });
    return {
      success: true,
      exitCode: 0,
      stdout: stdout || '',
      stderr: '',
      duration: Date.now() - start,
    };
  } catch (err) {
    return {
      success: false,
      exitCode: err.status || 1,
      stdout: err.stdout || '',
      stderr: err.stderr || err.message || '未知错误',
      duration: Date.now() - start,
    };
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length === 0 || args[0] === '--help') {
    console.log(`
${color.bold('bash - 命令执行工具')}
${color.gray('─'.repeat(45))}
${color.cyan('用法:')}  node bash.js <命令> [选项]

${color.cyan('选项:')}
  --cwd <路径>       工作目录
  --timeout <ms>     超时时间 (默认60000ms)

${color.cyan('示例:')}
  node bash.js "npm install"
  node bash.js "python --version"
  node bash.js "dir" --cwd "D:\\projects"
`);
    process.exit(0);
  }

  let command = '';
  const options = {};
  const rawArgs = [];

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--cwd') { options.cwd = args[++i]; continue; }
    if (args[i] === '--timeout') { options.timeout = parseInt(args[++i]) || 60000; continue; }
    rawArgs.push(args[i]);
  }
  command = rawArgs.join(' ');

  console.log(color.cyan(`[BASH] ${command}`));
  const result = bashExec(command, options);

  if (result.success) {
    console.log(color.green(`[PASS] 退出码: ${result.exitCode} | 耗时: ${result.duration}ms`));
    if (result.stdout.trim()) console.log(result.stdout.trim());
  } else {
    console.log(color.red(`[FAIL] 退出码: ${result.exitCode} | 耗时: ${result.duration}ms`));
    if (result.stdout.trim()) {
      console.log(color.gray('标准输出:'));
      console.log(result.stdout.trim());
    }
    if (result.stderr.trim()) {
      console.log(color.red('错误信息:'));
      console.log(color.red(result.stderr.trim()));
    }
    process.exit(1);
  }
}

module.exports = { bashExec };
