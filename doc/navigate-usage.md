# boss hr navigate 命令文档

## 概述

`navigate` 通过 CDP（Chrome DevTools Protocol）将当前浏览器 Tab 导航到指定 URL。用于在不同 BOSS 直聘页面之间切换，无需用户手动操作浏览器。

典型场景：Agent 在推荐页面完成打招呼后，自动切换到沟通页面查看消息。

## 前置条件

- Chrome 已通过 `--remote-debugging-port=9222` 启动
- 浏览器中至少有一个已打开的页面 Tab

## 用法

```bash
boss hr navigate <url> [--cdp-url URL] [--url-contains FRAGMENT] [--wait SECONDS]
```

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `url` | string | ✅ 是 | — | 目标页面 URL |
| `--cdp-url` | string | 否 | `http://localhost:9222` | Chrome CDP 调试端口地址 |
| `--url-contains` | string | 否 | _(无)_ | 指定要导航的 Tab（当多个 Tab 打开时定位目标 Tab） |
| `--wait` | float | 否 | `2.0` | 导航后等待页面加载的秒数 |

## 输出字段说明

```json
{
  "ok": true,
  "command": "recruiter-navigate",
  "data": {
    "navigated_to": "https://www.zhipin.com/web/chat/index",
    "page_url": "https://www.zhipin.com/web/chat/index",
    "page_title": "BOSS直聘-沟通",
    "ready_state": "complete",
    "previous_url": "https://www.zhipin.com/web/chat/recommend",
    "targetTab": {
      "id": "E3F8...",
      "title": "BOSS直聘-推荐候选人",
      "url": "https://www.zhipin.com/web/chat/recommend"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `navigated_to` | 请求导航的目标 URL |
| `page_url` | 导航完成后的实际 URL（可能因重定向与 `navigated_to` 不同） |
| `page_title` | 导航后的页面标题 |
| `ready_state` | 页面加载状态：`loading` / `interactive` / `complete` |
| `previous_url` | 导航前的页面 URL |
| `targetTab` | 被导航的 Tab 信息（导航前快照） |

## 常用页面 URL

| 页面 | URL |
|------|-----|
| 推荐候选人 | `https://www.zhipin.com/web/chat/recommend` |
| 沟通列表 | `https://www.zhipin.com/web/chat/index` |
| 职位管理 | `https://www.zhipin.com/web/boss/job/manage` |
| 候选人管理 | `https://www.zhipin.com/web/boss/talent` |

## 使用示例

### 切换到沟通页面

```bash
boss --json hr navigate https://www.zhipin.com/web/chat/index
```

### 切换到推荐页面

```bash
boss --json hr navigate https://www.zhipin.com/web/chat/recommend
```

### 慢速网络下等待更长时间

```bash
boss --json hr navigate https://www.zhipin.com/web/chat/index --wait 5
```

### 指定 Tab（多 Tab 场景）

```bash
# 只导航当前在 recommend 页面的那个 Tab
boss --json hr navigate https://www.zhipin.com/web/chat/index --url-contains recommend
```

### 在 Agent 工作流中使用

```bash
# 1. 切换到推荐页面
boss --json hr navigate https://www.zhipin.com/web/chat/recommend
# 等待 iframe 加载
sleep 3

# 2. 采集候选人
boss --json hr recommend-candidates --limit 5

# 3. 打招呼
boss --json hr recommend-action <geek_id>

# 4. 切换到沟通页面确认
boss --json hr navigate https://www.zhipin.com/web/chat/index
```

## 错误处理

| 错误码 | 含义 | 解决方式 |
|--------|------|---------|
| `CDP_NAVIGATE_FAILED` | CDP 连接失败或导航异常 | 检查 Chrome 是否仍在运行 |
| 消息含 `navigation failed` | URL 无效或网络不可达 | 检查 URL 拼写和网络连接 |
| 消息含 `no inspectable page tab` | 无可用 Tab | 在 Chrome 中至少打开一个页面 |

## 注意事项

- 导航会**替换当前 Tab 的页面**，不会打开新 Tab
- `--wait` 参数控制导航后等待时间。如果后续命令（如 `recommend-candidates`）报告 `iframe_not_ready`，可增大此值
- `ready_state` 为 `complete` 表示主文档加载完成，但 iframe 可能仍在加载中
- 导航后 `targetTab` 中的 URL 和 title 是**导航前**的快照，`page_url` 和 `page_title` 才是导航后的值
