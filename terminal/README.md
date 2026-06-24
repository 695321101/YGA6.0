# AI 终端

这是从原本的本地运行终端复制出来的 AI 友好版本。当前第一版重点不是直接接大模型 API，而是先把命令输出变成适合 Codex/AI 消化的结构化结果。

## 常用命令

显示工具列表：

```powershell
npm start
```

执行普通命令：

```powershell
node bash.js "npm test"
```

或通过统一入口：

```powershell
node index.js bash "npm test"
```

执行 AI 友好命令，默认输出 JSON：

```powershell
node ai.js exec "npm test"
```

调用已配置的模型生成诊断摘要：

```powershell
node ai.js exec "npm test" --llm
```

通过统一入口调用：

```powershell
node index.js ai exec "npm test" --tail 80
```

在人类可读模式下查看摘要：

```powershell
node ai.js exec "python script.py" --pretty
```

查看模型配置是否可用，不会输出 API Key：

```powershell
node ai.js config
```

交互终端中可以直接使用模型摘要命令：

```text
ai npm test
```

## 实时会话

实时运行命令：

```powershell
node session.js run "npm test"
```

后台启动长期任务：

```powershell
node session.js start "npm run dev" --name dev
```

查看、连接、中断会话：

```powershell
node session.js daemon
node session.js daemon restart
node session.js list
node session.js tail <session-id> --lines 100
node session.js attach <session-id>
node session.js submit <session-id> "Reply only with TEST_OK."
node session.js keys <session-id> ctrl+c
node session.js stop <session-id>
```

`attach` 会转发键盘输入到 PTY 会话。按 `Ctrl+]` 可以从 attach 中脱离，不会停止后台任务。

对 Codex、vim、REPL 这类 TUI/交互程序，优先用 `submit` 和 `keys`：

- `submit`：写入文本并用 Enter 提交；确认目标 TUI 支持 `Ctrl+U` 清行时，再加 `--clear`。
- `keys`：发送语义按键，例如 `enter`、`tab`、`escape`、`ctrl+c`、`ctrl+u`、`up`、`down`。
- `input`：保留给需要原始字节的低层场景。

如果 TUI 尾部显示 `esc to interrupt`，先执行：

```powershell
node session.js keys <session-id> escape
```

再调用 `submit`。这比重复发送 Enter 更稳定。

交互终端里也可以直接用：

```text
stream npm test
start npm run dev
sessions
tail <session-id>
attach <session-id>
stop <session-id>
```

## 日志浏览

```powershell
node logs.js list
node logs.js latest --lines 80
node logs.js read session-xxx.log --lines 120
node logs.js search "NameError"
```

日志浏览器默认会清理 ANSI/OSC 控制序列，减少模型和人阅读时的噪音。

## 模型配置

本项目会读取 `.ai-terminal.local.json` 或 `.env.local`，这两个文件已被 Git 忽略。

JSON 配置格式参考 `.ai-terminal.example.json`：

```json
{
  "api_base": "https://example.com/v1",
  "api_key": "sk-...",
  "proxy_url": "",
  "proxy_hosts": [],
  "model": "model-name"
}
```

也可以用环境变量：

```powershell
$env:AI_API_BASE="https://example.com/v1"
$env:AI_API_KEY="sk-..."
$env:AI_MODEL="model-name"
```

## 输出策略

`ai.js` 会返回：

- `summary`：一句话总结命令结果
- `ai`：模型生成的诊断摘要，只有使用 `--llm` 或交互终端 `ai` 命令时才会出现
- `keyFindings`：错误、警告、文件行号、测试失败等关键信号
- `stdoutTail` / `stderrTail`：裁剪后的尾部输出
- `rawLogFile`：完整日志路径

完整日志默认保存到 `.terminal/logs/`，该目录不会进入 Git。

## 后续方向

当前模型摘要只把结构化结果、关键错误和尾部日志发给模型，不会默认发送完整原始日志。完整日志仍保存在本地，只有需要深挖时再读取。
