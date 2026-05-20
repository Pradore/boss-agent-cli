# boss hr recommend-action 命令文档

## 概述

`recommend-action` 根据候选人的 `geek_id`，在推荐页面上精确定位目标候选人卡片并点击"打招呼"按钮。

该命令采用**两段式安全流程**：先用 `recommend-candidates` 采集并筛选候选人，再用 `recommend-action` 执行操作，避免误操作。

## 前置条件

1. CDP Chrome 已启动并登录 BOSS 直聘（同 `recommend-candidates`）。
2. 浏览器已打开推荐候选人页面（`/web/chat/recommend`）。
3. 已通过 `recommend-candidates` 命令获取目标候选人的 `geek_id`。

## 用法

```bash
boss hr recommend-action <geek_id> [--button TEXT] [--cdp-url URL] [--url-contains FRAGMENT]
```

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `geek_id` | string | ✅ 是 | — | 候选人加密ID，从 `recommend-candidates` 输出的 `geek_id` 字段复制 |
| `--button` | string | 否 | `"打招呼"` | 要点击的按钮文本。默认为"打招呼"，也可指定其他按钮文本 |
| `--cdp-url` | string | 否 | `http://localhost:9222` | Chrome CDP 调试端口地址 |
| `--url-contains` | string | 否 | _(无)_ | 仅探测 URL 包含该片段的页面 Tab |

### geek_id 格式

`geek_id` 是 BOSS 直聘为每个候选人生成的加密标识符，格式如：

```
bc9a76ca58b750950nd_3967F1ZX
```

- 由字母、数字、下划线组成
- 每个候选人唯一且稳定
- 存储在页面 DOM 的 `data-geekid` 属性中

## 输出字段说明

### 成功时
```json
{
  "ok": true,
  "command": "recruiter-recommend-action",
  "data": {
    "clicked": true,
    "geek_id": "bc9a76ca58b750950nd_3967F1ZX",
    "candidate_name": "王佳旭",
    "button_text": "打招呼",
    "confirmation": {
      "button_changed": true,
      "old_button_text": "打招呼",
      "new_button_text": "已沟通",
      "disabled_changed": true,
      "toast_detected": null,
      "confidence": "high"
    },
    "targetTab": { ... }
  }
}
```

### 确认机制字段详解

点击按钮后，命令会等待 300ms 并检查页面变化，输出确认信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| `clicked` | bool | 是否成功执行了点击 |
| `geek_id` | string | 被操作的候选人 ID |
| `candidate_name` | string \| null | 候选人姓名（用于人工核对） |
| `button_text` | string | 点击时的按钮文本 |
| `confirmation.button_changed` | bool | 按钮文本是否发生变化（如"打招呼"→"已沟通"） |
| `confirmation.old_button_text` | string | 点击前的按钮文本 |
| `confirmation.new_button_text` | string | 点击后的按钮文本 |
| `confirmation.disabled_changed` | bool | 按钮 disabled 状态是否变化 |
| `confirmation.toast_detected` | string \| null | 是否检测到 toast 提示消息 |
| `confirmation.confidence` | string | 操作确认置信度：`"high"`（有明确变化信号）或 `"medium"`（无变化但点击已执行） |

### confidence 判定逻辑

| 条件 | confidence |
|------|-----------|
| 按钮文本变化 **或** disabled 状态变化 **或** 检测到 toast | `high` |
| 以上均无变化 | `medium` |

> **注意**：`medium` 不代表操作失败，可能是页面响应延迟。建议用 `recommend-candidates` 重新采集确认状态。

## 使用示例

### 基本打招呼
```bash
# 使用默认按钮文本"打招呼"
boss --json hr recommend-action bc9a76ca58b750950nd_3967F1ZX
```

### 指定按钮文本
```bash
boss --json hr recommend-action bc9a76ca58b750950nd_3967F1ZX --button "感兴趣"
```

### 完整工作流
```bash
# 1. 采集候选人
boss --json hr recommend-candidates > candidates.json

# 2. 查看候选人列表（使用 jq 过滤）
cat candidates.json | jq '.data.candidates[] | {name, geek_id, edu, tags}'

# 3. 筛选后对目标候选人打招呼
boss --json hr recommend-action bc9a76ca58b750950nd_3967F1ZX

# 4. 确认操作结果
boss --json hr recommend-candidates
```

### 批量打招呼（脚本示例）
```bash
# 对所有含 "QS前100" 标签且未禁用的候选人打招呼
boss --json hr recommend-candidates \
  | jq -r '.data.candidates[] | select(.tags[]? == "QS前100院校") | select(.greet_btn.disabled == false) | .geek_id' \
  | while read gid; do
      echo "打招呼: $gid"
      boss --json hr recommend-action "$gid"
      sleep 2  # 避免操作过快被检测
    done
```

## 错误处理

| 错误码 | 含义 | 解决方式 |
|--------|------|---------|
| `CDP_ACTION_FAILED` | CDP 连接失败或 JS 执行异常 | 检查 Chrome 是否仍在运行 |
| `IFRAME_NOT_FOUND` | 推荐页面的 iframe 不存在 | 确保浏览器已导航至推荐页面 |
| `IFRAME_NOT_READY` | iframe 仍在加载中 | 等待几秒后重试 |
| `CANDIDATE_NOT_FOUND` | 指定 geek_id 的候选人不在当前页面上 | 用 `recommend-candidates` 重新采集获取最新 geek_id |
| `BUTTON_NOT_FOUND` | 指定文本的按钮在卡片内未找到 | 检查 `--button` 文本是否正确，错误中会返回 `available_buttons` 列表 |
| `BUTTON_DISABLED` | 按钮已被禁用（已打过招呼） | 该候选人已被操作过，无需再次点击 |

## 安全设计

1. **geek_id 防注入**：传入的 `geek_id` 在 JS 端使用 `CSS.escape()` 转义后再拼接到选择器中，防止 CSS 选择器注入攻击。

2. **两段式流程**：采集和操作分离为两个命令，用户/Agent 必须先看到候选人信息再决定操作，避免盲目点击。

3. **确认机制**：点击后自动检测按钮状态变化和 toast 消息，提供操作结果的置信度评估。

4. **精确定位**：使用 `data-geekid` 属性精确定位候选人，而非依赖 DOM 位置索引，即使页面发生部分刷新也不会误操作其他候选人。

## 技术原理

1. 通过 CDP WebSocket 连接到目标 Tab
2. 在页面上下文中注入 JS 脚本
3. JS 脚本定位 `<iframe name="recommendFrame">` 的 `contentDocument`
4. 使用 `[data-geekid="xxx"]` CSS 选择器精确找到目标候选人卡片
5. 定位卡片内的 `button.btn-greet` 按钮并调用 `.click()`
6. 等待 300ms 后检查按钮文本变化、disabled 状态、toast 消息
7. 返回操作结果和确认信息
