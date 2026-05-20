# 推荐候选人页面 DOM 探测报告

## 探测时间
2026-05-20 15:37 ~ 16:10

## 环境
- Chrome 145.0.7632.6，CDP `--remote-debugging-port=9222`
- 页面 URL: `https://www.zhipin.com/web/chat/recommend`
- 已登录招聘者账号

---

## 🔴 关键发现：候选人内容在 iframe 里

### 页面结构

```
https://www.zhipin.com/web/chat/recommend          ← 主文档（外壳）
  ├─ #wrap .wrap-v2                                ← 只有导航和侧边栏
  │    ├─ .side-wrap（左侧菜单）
  │    ├─ .nav-wrap（顶部导航）
  │    └─ ...
  └─ <iframe name="recommendFrame">                ← ⭐ 候选人全在这里
       src="https://www.zhipin.com/web/frame/recommend/?jobid=...&version=9996"
       尺寸: 872x642
       同源: zhipin.com（可通过 contentDocument 直接访问）
```

### 主文档（外壳）内容

主文档只有**导航栏和侧边栏**，没有任何候选人信息。

### iframe 内容（`recommendFrame`）— 已完整验证 ✅

通过 CDP `Page.getFrameTree` 确认 iframe 结构：

| 属性 | 值 |
|------|-----|
| frame name | `recommendFrame` |
| frame ID | 每次刷新会变 |
| URL | `https://www.zhipin.com/web/frame/recommend/?jobid=...&status=0&...&version=9996` |
| origin | `https://www.zhipin.com`（同源） |

---

## ✅ 已确认的 DOM 结构

### iframe 内部的 CSS class 清单（已验证）

| class | 元素 | 数量 | 作用 |
|-------|------|------|------|
| `.card-list` | UL | 1 | 候选人列表容器 |
| `.card-item` | LI | 16 | 单个候选人卡片 |
| `.card-inner` | DIV | 15 | 卡片内层容器 |
| `.candidate-card-wrap` | DIV | 15 | 卡片外层包裹 |
| `.name` | SPAN | 15 | 候选人姓名 |
| `.name-wrap` | DIV | 15 | 姓名 + 基础信息行 |
| `.base-info` | DIV | 15 | 年龄、应届/经验、学历、活跃度 |
| `.expect-wrap` | DIV | 15 | 期望城市 + 期望岗位 |
| `.edu-exp` | DIV | 15 | 学校 + 专业 + 学历 |
| `.work-exps` | DIV | 11 | 工作/实习经历（时间线） |
| `.tags` | DIV | 15 | 标签（如 QS前500、专业前1%） |
| `.tag-item` | SPAN | 39 | 单个标签 |
| `.btn-greet` | BUTTON | 15 | ⭐ "打招呼"按钮 |
| `.btn-doc` | SPAN | 15 | 打招呼按钮内的文本 span |
| `.button-list` | DIV | 15 | 按钮容器 |
| `.empty-work-exp` | SPAN | 4 | "未填写工作经历"提示 |
| `.timeline-item` | DIV | 18 | 工作经历时间线条目 |

### 单个候选人卡片的 DOM 层级

```
li.card-item
  └─ div.card-inner
       └─ div.candidate-card-wrap
            ├─ [薪资文本, 如 "面议"]
            ├─ div.name-wrap
            │    ├─ span.name           → "王佳旭"
            │    └─ div.base-info       → "25岁 27年应届生 硕士 刚刚活跃"
            ├─ div.expect-wrap          → "期望 北京 算法工程师"
            ├─ div.edu-exp              → "中国科学院大学 资源与环境 硕士"
            ├─ div.tags-wrap
            │    └─ div.tags
            │         └─ span.tag-item  → "QS前500院校"、"专业前1%"
            ├─ div.work-exps
            │    └─ div.timeline-item × N → "2025.11 2026.03 美团 全栈工程师"
            └─ div.button-list
                 └─ button.btn.btn-greet → "打招呼"
```

### 提取到的真实候选人数据样例

```json
{
  "name": "王佳旭",
  "base_info": "25岁 27年应届生 硕士 刚刚活跃",
  "expect": "期望 北京 算法工程师",
  "edu": "中国科学院大学 资源与环境 硕士",
  "work": "2025.11 2026.03 美团· Beam-小美 Agent 团队 全栈工程师",
  "tags": "QS前500院校 专业前1%",
  "salary": "面议",
  "greet_btn": { "text": "打招呼", "tag": "BUTTON", "disabled": false }
}
```

---

## 访问 iframe 的正确方法

### ❌ 方法一：Runtime.enable + contextId（不推荐）

```
Runtime.enable → 收集 executionContextCreated 事件 → 找到 iframe 的 contextId → Runtime.evaluate + contextId
```

**问题**：iframe 的 execution context 在页面交互中会被频繁销毁重建，`contextId` 不稳定，经常出现 `Cannot find context with specified id` 错误。

### ✅ 方法二：主文档 contentDocument 访问（推荐）

由于 iframe 与主文档**同源**（都是 `zhipin.com`），可以在主文档上下文中直接通过 `contentDocument` 访问 iframe 内容：

```javascript
const iframe = document.querySelector('iframe[name="recommendFrame"]');
const doc = iframe.contentDocument;
const cards = doc.querySelectorAll('li.card-item');
```

**优点**：无需切换 context，无需 Runtime.enable，一个 `Runtime.evaluate` 调用就够。

---

## 对现有代码的影响

### 需要修改

1. **`inspect_page.py`** 和 **`recommend.py`** 中的 JS 脚本需要：
   - 检测页面是否有 `recommendFrame` iframe
   - 如果有，通过 `iframe.contentDocument` 在 iframe 内操作
   - 使用精确的 selector（`.card-item`、`.name`、`.btn-greet`）替代通用关键词匹配

2. **`recommend.py`** 的采集脚本需要：
   - 用 `.name` 取姓名，`.base-info` 取基础信息
   - 用 `.edu-exp` 取学历，`.expect-wrap` 取期望
   - 用 `.work-exps` 取工作经历，`.tags` 取标签
   - 点击 `button.btn-greet` 执行打招呼

---

## CDP 操作指南：如何通过 CDP 爬取网页元素

### 前置条件

1. 以 CDP 模式启动 Chrome：
   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\tmp\boss-chrome
   ```

2. 验证 CDP 可用：
   ```powershell
   Invoke-WebRequest -UseBasicParsing http://localhost:9222/json/version
   ```

### 步骤一：获取目标 tab

```python
import json, urllib.request
tabs = json.load(urllib.request.urlopen("http://localhost:9222/json", timeout=3))
# 每个 tab 返回: { id, url, title, type, webSocketDebuggerUrl }
tab = [t for t in tabs if "关键词" in t.get("url", "")][0]
ws_url = tab["webSocketDebuggerUrl"]  # ws://localhost:9222/devtools/page/XXX
```

### 步骤二：建立 WebSocket 连接

```python
import websockets.sync.client as ws_client
with ws_client.connect(ws_url, max_size=8*1024*1024) as ws:
    # 所有 CDP 命令通过此 WebSocket 发送/接收
    ...
```

### 步骤三：在页面中执行 JS（Runtime.evaluate）

```python
ws.send(json.dumps({
    "id": 1,
    "method": "Runtime.evaluate",
    "params": {
        "expression": "(() => { /* JS 代码 */ })()",
        "returnByValue": True,      # 返回 JS 对象的 JSON 值
        "awaitPromise": True,        # 如果返回 Promise，等待 resolve
    },
}))
# 接收结果
while True:
    msg = json.loads(ws.recv(timeout=30))
    if msg.get("id") == 1:
        value = msg["result"]["result"]["value"]  # JS 返回值
        break
```

### 步骤四：处理 iframe（同源场景）

如果目标内容在 iframe 内，且 iframe 与主页面同源，直接在主文档中访问：

```javascript
// 在 Runtime.evaluate 的 JS 中
const iframe = document.querySelector('iframe[name="recommendFrame"]');
const doc = iframe.contentDocument;  // 同源可访问
const elements = doc.querySelectorAll('.card-item');
```

### 步骤五：查看页面的 Frame 树（可选）

```python
ws.send(json.dumps({"id": 2, "method": "Page.getFrameTree"}))
# 返回: { frameTree: { frame: {...}, childFrames: [{frame: {...}}, ...] } }
```

### 步骤六：探测未知页面的 DOM 结构

推荐的探测脚本模板：

```javascript
(() => {
    const sq = t => String(t||'').replace(/\s+/g,' ').trim();

    // 1. 扫描所有 class，按关键词过滤
    const classMap = {};
    for (const el of document.querySelectorAll('*')) {
        const cls = String(el.className||'');
        if (typeof cls !== 'string') continue;
        cls.split(/\s+/).forEach(c => {
            if (c && /你的关键词/.test(c.toLowerCase())) {
                if (!classMap[c]) classMap[c] = {
                    tag: el.tagName,
                    count: 0,
                    sample: sq(el.innerText||'').slice(0,100)
                };
                classMap[c].count++;
            }
        });
    }

    // 2. 扫描所有按钮
    const buttons = Array.from(document.querySelectorAll('button,a,[role=button]'))
        .map(b => ({
            text: sq(b.innerText||''),
            cls: String(b.className||'').slice(0,100)
        }))
        .filter(b => b.text);

    return { classes: classMap, buttons };
})()
```

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 扫不到元素 | 内容在 iframe 里 | 用 `Page.getFrameTree` 查看 + `contentDocument` 访问 |
| `Cannot find context` | iframe context 已过期 | 用同源 `contentDocument` 替代 `contextId` |
| `returnByValue` 返回空 | JS 返回了不可序列化的对象 | 确保返回纯 JSON 兼容对象 |
| 按钮点击无效 | 元素被遮挡或需要事件冒泡 | 用 `el.dispatchEvent(new MouseEvent('click', {bubbles:true}))` |

### 探测脚本

完整可运行的探测脚本位于 `scripts/probe_recommend_iframe.py`。
