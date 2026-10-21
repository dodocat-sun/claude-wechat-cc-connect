# Claude 接入微信：cc-connect 实用模板

把电脑上的 Claude Code 接到个人微信。电脑保持开机后，可以直接在微信里让 Claude 查看项目、改代码和执行已授权的任务，不需要公网 IP。

本项目还带一个可选状态栏，回复末尾可以显示：

```text
模型：Claude Opus 5.5 · 推理：HIGH · 上下文：25.6%
耗时：173.3秒 · 额度剩余：五小时 26% · 本周 69%
```

## 流程

原来：

```text
人在电脑前 → 打开 Claude Code → 输入任务
```

接入后：

```text
微信发消息 → cc-connect 转发 → 本机 Claude Code 执行 → 微信收到结果
```

## 准备

- 已安装并登录 Claude Code
- 已安装 Node.js 18 或更高版本
- 手机微信可以扫码
- 建议先准备一个只用于工作的目录

状态栏不是必需的。模型、推理、上下文和耗时直接来自 Claude Code；额度信息需要 macOS 上已经登录 Claude 的 [CodexBar](https://github.com/steipete/CodexBar)。没有 CodexBar 时，连接仍可正常使用，只会显示“额度暂不可读”。

## 1. 安装 cc-connect

```bash
npm install -g cc-connect
cc-connect --version
```

## 2. 下载这个模板

```bash
git clone https://github.com/dodocat-sun/claude-wechat-cc-connect.git
cd claude-wechat-cc-connect
chmod +x claude-status.py
```

## 3. 创建配置

```bash
mkdir -p ~/.cc-connect
cp config.example.toml ~/.cc-connect/config.toml
```

打开 `~/.cc-connect/config.toml`，只需要修改两个地方：

- `work_dir`：Claude 可以工作的项目目录。
- `cmd`：本项目中 `claude-status.py` 的绝对路径。

不需要状态栏时，删除 `cmd` 这一行，并把 `reply_footer` 改为 `true`，使用 cc-connect 自带的简版状态。

## 4. 微信扫码绑定

```bash
cc-connect weixin setup --project claude-wechat
```

用手机微信扫码并确认。命令会把连接凭据写入本机 `~/.cc-connect/config.toml`。

绑定后请检查 `allow_from`，确保只允许你自己的微信账号使用。不要设置为 `*`，也不要把绑定后的真实配置上传到 GitHub。

## 5. 启动

先在前台试运行：

```bash
cc-connect
```

然后在微信里给机器人发一条消息。确认能够回复后，按 `Ctrl+C` 退出前台，再安装后台服务：

```bash
cc-connect daemon install
cc-connect daemon status
```

以后常用命令：

```bash
cc-connect daemon status
cc-connect daemon logs -f
cc-connect daemon restart
```

## 推理强度

模板默认使用 `high`。微信里可用以下命令查询或切换：

```text
/reasoning
/reasoning low
/reasoning medium
/reasoning high
/reasoning max
```

切换后 cc-connect 会重新开始 Claude 会话。服务重启后会恢复配置文件中的默认值。

## 安全提醒

- 默认使用 `mode = "default"`，Claude 执行有风险的操作时仍会请求允许。
- 不要公开 `~/.cc-connect/config.toml`、日志、会话文件和微信 Token。
- `allow_from` 只保留自己的微信 ID。
- 不建议一开始使用 `yolo` / `bypassPermissions`。
- 工作目录尽量单独设置，不要直接给整个用户目录。
- 电脑关机、休眠或 cc-connect 停止后，微信端就不能继续调用 Claude。

## 状态栏如何工作

`claude-status.py` 是 Claude Code 输出流的轻量适配器，只在一次正常回复结束时追加状态：

- 模型：本轮实际模型。
- 推理：本轮实际推理强度。
- 上下文：本轮最后一次模型调用使用量占上下文窗口的比例。
- 耗时：Claude Code 返回的本轮耗时。
- 额度：CodexBar 返回的五小时和本周剩余比例，缓存 120 秒。

它只用 Python 标准库，不读取微信 Token，不保存 Claude Cookie。状态缓存只含百分比和更新时间。

## 自检

```bash
python3 -m unittest -v test_status.py
```

## 常见问题

### 微信收不到回复

先运行：

```bash
cc-connect daemon status
cc-connect daemon logs -f
```

确认服务正在运行、`allow_from` 是自己的微信 ID，并在服务启动后先发一条普通消息完成首次会话关联。

### 状态栏显示“额度暂不可读”

不影响 Claude 回复。macOS 用户可打开 CodexBar，确认其中 Claude 额度能正常显示；其他系统默认没有这项额度来源。

### 不想显示状态栏

从配置删除 `cmd`，并把 `[display]` 中 `reply_footer` 改成 `true`，然后重启 cc-connect。

## 说明

这是 cc-connect 的使用模板和可选状态适配器，不是 cc-connect 的分支。cc-connect 的安装和微信能力以其[官方项目](https://github.com/chenhg5/cc-connect)为准。

## License

MIT
