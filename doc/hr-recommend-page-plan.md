# HR 推荐候选人页面探测与后续开发计划

## 目标

当前目标是为 BOSS 直聘 HR 端新增一条可调试链路：在不打开 F12 DevTools 的情况下，通过 CDP 后台读取当前招聘者页面，提取页面标题、URL、按钮文本、疑似候选人卡片文本，为后续开发“推荐候选人采集 -> Agent 筛选 -> 点击候选人旁按钮”的功能做准备。

这个文档记录当前已经完成的改动、命令调用方式、环境要求，以及后续应该如何继续开发。

## 已完成改动

### 1. 新增 HR 页面探测命令模块

新增文件：

```text
src\boss_agent_cli\commands\recruiter\inspect_page.py
```

该模块新增了两个核心入口：

```python
inspect_cdp_page(cdp_url: str, *, url_contains: str | None = None) -> dict[str, Any]
inspect_page_cmd(ctx, cdp_url, url_contains) -> None
```

功能说明：

- 访问 CDP HTTP 接口：`<cdp-url>/json`
- 找到可探测的 `page` tab
- 优先选择 URL 中包含 `zhipin.com` 的页面
- 排除 `devtools://`、`about:`、`view-source:` 页面
- 通过 `webSocketDebuggerUrl` 连接页面 CDP WebSocket
- 执行 `Runtime.evaluate`
- 在页面上下文里扫描：
  - `location.href`
  - `document.title`
  - `document.readyState`
  - `document.body.innerText` 摘要
  - 页面上的按钮文本
  - 疑似候选人卡片文本块

探测脚本会搜索这些 DOM 节点：

```text
div, li, section, article
```

并用关键词判断疑似候选人卡片，例如：

```text
本科、硕士、博士、大专、毕业、大学、学院、学校、应届、经验、岁、候选人、沟通、打招呼、感兴趣、简历
```

同时要求卡片里出现疑似动作按钮，例如：

```text
打招呼、沟通、感兴趣、查看、简历、联系、交换、不合适、邀约、收藏、约聊
```

输出中会包含：

```json
{
  "url": "当前页面 URL",
  "title": "页面标题",
  "readyState": "页面加载状态",
  "bodyTextSample": "页面正文摘要",
  "buttons": [
    {
      "text": "按钮文本",
      "tag": "BUTTON/A/...",
      "className": "class 摘要",
      "href": "链接"
    }
  ],
  "candidateBlocks": [
    {
      "index": 1,
      "domIndex": 123,
      "tag": "DIV",
      "className": "候选块 class 摘要",
      "text": "候选块文本摘要",
      "buttons": []
    }
  ],
  "targetTab": {
    "id": "CDP tab id",
    "title": "CDP tab 标题",
    "url": "CDP tab URL"
  }
}
```

### 2. 注册为 HR 子命令

修改文件：

```text
src\boss_agent_cli\commands\register.py
```

新增导入：

```python
from boss_agent_cli.commands.recruiter import inspect_page as recruiter_inspect_page
```

新增命令注册：

```python
hr_group.add_command(recruiter_inspect_page.inspect_page_cmd, "inspect-page")
```

因此命令入口为：

```powershell
uv run boss hr inspect-page
```

### 3. 更新 schema 描述

修改文件：

```text
src\boss_agent_cli\commands\schema.py
```

在 `hr.subcommands` 中新增：

```text
inspect-page: 通过 CDP 后台探测当前页面候选人卡片和按钮（不打开 DevTools）
```

## 命令调用方式

### 1. 启动可被 CDP 连接的 Chrome

Windows 示例：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\tmp\boss-chrome
```

如果 Chrome 安装在 x86 路径：

```powershell
& "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\tmp\boss-chrome
```

### 2. 验证 CDP 是否可用

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:9222/json/version
```

返回 200 即表示 CDP 端口可访问。

### 3. 在 CDP Chrome 里手动登录并打开目标页面

需要用户本人在刚启动的 Chrome 窗口里完成：

1. 打开 BOSS 直聘页面
2. 登录招聘者账号
3. 进入推荐候选人页面

注意不要使用：

```text
view-source:https://...
```

也不要打开 F12 DevTools，因为当前环境下 F12 会触发访问限制。

### 4. 调用探测命令

默认读取全局 `--cdp-url`，如果未传则使用：

```text
http://localhost:9222
```

推荐调用：

```powershell
uv run boss --cdp-url http://localhost:9222 --json hr inspect-page
```

也可以使用命令自己的 `--cdp-url`：

```powershell
uv run boss --json hr inspect-page --cdp-url http://localhost:9222
```

如果打开了多个页面，可以用 URL 片段限制目标 tab：

```powershell
uv run boss --cdp-url http://localhost:9222 --json hr inspect-page --url-contains zhipin.com
```

或指定推荐页面 URL 里的关键片段：

```powershell
uv run boss --cdp-url http://localhost:9222 --json hr inspect-page --url-contains recommend
```

### 5. 如何使用输出

重点看输出里的：

```text
data.candidateBlocks
data.buttons
data.targetTab.url
```

如果 `candidateBlocks` 能识别到推荐候选人卡片，把这段 JSON 交给开发者继续分析 selector 和字段结构。

如果 `candidateBlocks` 为空，但 `bodyTextSample` 或 `buttons` 有内容，说明需要调整关键词或页面 selector。

如果 `targetTab.url` 是 `view-source:`、`about:blank`、`devtools://`，说明当前选中的不是正常业务页面，需要回到 CDP Chrome 打开真实 BOSS 页面。

## 当前未完成项

由于环境还没有配置好，本轮没有继续完成以下工作：

1. 没有运行完整测试。
2. 没有补 `tests\test_recruiter_commands.py` 的 `inspect-page` 单元测试。
3. 没有基于真实推荐候选人页面输出调整精确 selector。
4. 没有实现 `hr recommend-candidates` 采集命令。
5. 没有实现 `hr recommend-action <action_token>` 点击命令。

## 后续开发计划

### 阶段一：让 inspect-page 稳定可用

待环境可用后先执行：

```powershell
uv run boss --cdp-url http://localhost:9222 --json hr inspect-page
```

确认输出是否包含推荐候选人卡片。如果输出为空，优先调整：

- `_INSPECT_SCRIPT` 中的 `keywordRe`
- `_INSPECT_SCRIPT` 中的 `actionRe`
- 扫描节点范围：`div,li,section,article`
- 文本长度阈值

建议补测试：

- `inspect_cdp_page` 成功返回时命令输出 JSON envelope
- CDP 不可达时输出 `CDP_INSPECT_FAILED`
- `--url-contains` 参数能传入底层函数

### 阶段二：实现推荐候选人采集命令

建议新增命令：

```powershell
boss hr recommend-candidates --limit 30
```

职责：

- 读取当前推荐候选人页面
- 提取候选人卡片
- 解析学校、学历、毕业年份、专业、经验、城市、期望岗位等字段
- 输出结构化 JSON
- 为每个候选人生成 `action_token`

建议输出：

```json
{
  "candidates": [
    {
      "action_token": "rec_001_xxx",
      "index": 1,
      "name": "候选人名",
      "school": "学校",
      "degree": "本科",
      "graduate_year": "2025",
      "major": "专业",
      "card_text": "原始卡片文本",
      "buttons": ["打招呼", "不合适"]
    }
  ]
}
```

### 阶段三：实现 Agent 筛选后的点击命令

建议新增命令：

```powershell
boss hr recommend-action <action_token>
```

职责：

- 根据 `action_token` 找到上次采集的候选人记录
- 重新定位当前页面上的候选人卡片
- 校验卡片文本或候选人 ID 是否匹配
- 点击指定按钮
- 读取 toast、按钮状态或页面变化确认结果
- 输出结构化成功/失败 JSON

不要让采集命令直接自动点击。推荐保持两段式：

```text
采集候选人 -> Agent 筛选 -> 显式点击 action_token
```

这样可以降低误点风险。

### 阶段四：强化成功确认

第一版可以通过页面变化或 toast 判断。更稳定的版本可以继续加入：

- 监听 fetch/XHR 返回
- 监听 WebSocket 事件
- 检查按钮文案变化
- 检查候选人卡片状态变化

## 推荐技术路线

优先级如下：

```text
已有 HTTP API > 浏览器 fetch > 页面 Vue/React 方法 > DOM 点击模拟
```

对于推荐候选人页面，建议先用 `inspect-page` 判断页面是否已经把候选人数据渲染在 DOM 中。

如果 DOM 中有完整数据，先走 DOM 文本采集。

如果 DOM 文本不完整，再观察页面接口，尝试通过浏览器 fetch 或已有 HTTP client 获取。

如果点击按钮涉及前端状态、弹窗或风控，则参考现有 HR `reply` / `request-resume` 的做法，让前端组件代劳，并通过页面状态或网络事件确认成功。

## 注意事项

- 不要打开 F12；当前页面会因为 DevTools 可视化界面触发访问限制。
- 不要使用 `view-source:` 页面；它只能看到初始 HTML，看不到动态候选人卡片。
- `inspect-page` 是只读命令，不会点击页面按钮。
- 真正点击按钮的功能必须单独做，并且要有确认机制。
- 输出里可能包含候选人页面文本，后续记录和分享时注意隐私。
