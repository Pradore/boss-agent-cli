# boss hr recommend-candidates 命令文档

## 概述

`recommend-candidates` 通过 CDP（Chrome DevTools Protocol）连接用户的真实浏览器，自动采集 BOSS 直聘推荐候选人页面上的所有候选人卡片信息，输出结构化 JSON。

该命令**不使用 Playwright/Patchright**，而是通过原始 CDP 协议直接与用户已登录的 Chrome 浏览器通信，不会触发额外的浏览器窗口。

## 前置条件

1. **启动 CDP Chrome**：
   ```bash
   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\tmp\boss-chrome
   ```

2. **登录 BOSS 直聘**：在 CDP Chrome 中手动登录。

3. **打开推荐页面**：导航至 `https://www.zhipin.com/web/chat/recommend`。

## 用法

```bash
boss hr recommend-candidates [--cdp-url URL] [--url-contains FRAGMENT] [--limit N] [--offset N] [--refresh]
```

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--cdp-url` | string | `http://localhost:9222` | Chrome CDP 调试端口地址。如果 Chrome 在远程机器或非默认端口，需手动指定 |
| `--url-contains` | string | _(无)_ | 仅探测 URL 包含该片段的页面 Tab。当浏览器打开了多个 Tab 时，用于精确定位目标页面。例如 `--url-contains recommend` |
| `--limit` | int | `30` | 最多采集多少个候选人卡片。页面通常展示 16 个，设置更大值不会出错 |
| `--offset` | int | `0` | 跳过前 N 个候选人卡片，用于翻页采集。例如第一批 `--limit 5`，第二批 `--limit 5 --offset 5` |
| `--refresh` | flag | _(关闭)_ | 先向下滚动 iframe 加载更多候选人；如果目标 `offset` 批次仍为空，则刷新推荐 iframe 并从 `offset=0` 采集刷新后的新列表 |

### 全局参数

| 参数 | 说明 |
|------|------|
| `--json` | 以纯 JSON 格式输出（推荐用于程序调用 / Agent 消费） |
| `--role recruiter` | 指定为招聘者模式（使用 `boss hr` 子命令时自动切换） |

## 输出字段说明

```json
{
  "ok": true,
  "command": "recruiter-recommend-candidates",
  "data": {
    "page_url": "https://www.zhipin.com/web/chat/recommend",
    "iframe_url": "https://www.zhipin.com/web/frame/recommend/?jobid=null&...",
    "total_cards": 16,
    "offset": 0,
    "total_found": 16,
    "candidates": [
      {
        "index": 1,
        "geek_id": "bc9a76ca58b750950nd_3967F1ZX",
        "name": "王佳旭",
        "base_info": "25岁 27年应届生 硕士 刚刚活跃",
        "expect": "期望 北京 算法工程师",
        "edu": "中国科学院大学 资源与环境 硕士",
        "work": "2025.11 2026.03 美团· Beam-小美 Agent 团队 全栈工程师",
        "tags": ["QS前500院校", "专业前1%"],
        "salary": "面议",
        "avatar_url": "https://img.bosszhipin.com/...",
        "gender": "male",
        "greet_btn": {
          "text": "打招呼",
          "disabled": false
        }
      }
    ],
    "targetTab": {
      "id": "E3F8...",
      "title": "BOSS直聘-推荐候选人",
      "url": "https://www.zhipin.com/web/chat/recommend"
    }
  }
}
```

### 候选人字段详解

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | int | 从 1 开始的序号 |
| `geek_id` | string \| null | 候选人加密唯一ID（来自 `data-geekid` 属性），用于 `recommend-action` 命令 |
| `name` | string \| null | 候选人姓名 |
| `base_info` | string \| null | 基本信息（年龄、应届/社招、学历、活跃度），如 `"25岁 27年应届生 硕士 刚刚活跃"` |
| `expect` | string \| null | 期望城市和岗位，如 `"期望 北京 算法工程师"` |
| `edu` | string \| null | 学历信息（学校、专业、学位），如 `"中国科学院大学 资源与环境 硕士"` |
| `work` | string \| null | 工作/实习经历（截取前 300 字符），如 `"2025.11 2026.03 美团 工程师"`。未填写则为 `null` |
| `tags` | string[] | 标签数组，如 `["QS前500院校", "专业前1%"]`。无标签时为空数组 `[]` |
| `salary` | string \| null | 薪资期望，如 `"面议"`、`"15-25K"` |
| `avatar_url` | string \| null | 头像图片 URL |
| `gender` | string \| null | 性别：`"male"` / `"female"` / `null`（未知） |
| `greet_btn` | object \| null | 打招呼按钮状态。`text`：按钮文字；`disabled`：是否已禁用（已打过招呼） |

### 批次和刷新字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_cards` | int | 当前 iframe DOM 中的候选人卡片总数 |
| `offset` | int | 本次采集跳过的卡片数量；页面刷新后重新采集时会回到 `0` |
| `total_found` | int | 本批实际返回的候选人数 |
| `refresh_result` | object \| null | 传入 `--refresh` 时的滚动加载结果，包含 `new_cards_loaded`、`has_more` 等字段 |
| `page_refresh_result` | object \| null | 仅当 `--refresh` 后目标批次仍为空时出现，表示已重新加载推荐 iframe 并采集新列表 |

`--refresh` 在滚动后仍无候选人时会额外返回：

```json
{
  "refresh_result": {
    "scrolled": true,
    "new_cards_loaded": 0,
    "has_more": false
  },
  "page_refresh_result": {
    "triggered": true,
    "reason": "offset_exhausted",
    "previous_offset": 16,
    "previous_total_cards": 16,
    "collected_after_refresh": 5
  }
}
```

## 使用示例

### 基本采集
```bash
boss --json hr recommend-candidates
```

### 限制数量
```bash
boss --json hr recommend-candidates --limit 5
```

### 指定 CDP 端口
```bash
boss --json hr recommend-candidates --cdp-url http://192.168.1.100:9222
```

### 翻页采集
```bash
# 第一批（前 5 人）
boss --json hr recommend-candidates --limit 5

# 第二批（跳过前 5 人）
boss --json hr recommend-candidates --limit 5 --offset 5

# 第三批（跳过前 10 人）
boss --json hr recommend-candidates --limit 5 --offset 10
```

### 刷新推荐列表
```bash
# 向下滚动加载更多候选人
boss --json hr recommend-candidates --limit 5 --refresh

# 滚动后配合 offset 采集新加载的候选人
boss --json hr recommend-candidates --limit 5 --offset 10 --refresh

# 当前 DOM 候选人已处理完：先滚动，仍无新人时刷新推荐 iframe 并从新列表采集
boss --json hr recommend-candidates --limit 5 --offset 16 --refresh
```

当 `--refresh` 触发页面刷新后，输出中的 `offset` 会回到 `0`，表示本批候选人来自刷新后的新推荐列表。调用方应继续用候选人的 `geek_id` 去重，避免重复筛选或重复打招呼。

### 配合 recommend-action 使用
```bash
# 第一步：采集候选人列表
boss --json hr recommend-candidates

# 第二步：从输出中选择目标候选人的 geek_id，执行打招呼
boss --json hr recommend-action bc9a76ca58b750950nd_3967F1ZX
```

## 错误处理

| 错误码 | 含义 | 解决方式 |
|--------|------|---------|
| `CDP_RECOMMEND_FAILED` | CDP 连接失败或 JS 执行异常 | 检查 Chrome 是否以 `--remote-debugging-port` 启动 |
| 错误消息含 `iframe_not_found` | 推荐页面未打开或 iframe 不存在 | 确保浏览器已导航至推荐候选人页面 |
| 错误消息含 `iframe_not_ready` | iframe 仍在加载中 | 等待几秒后重试 |

## 技术原理

1. 通过 HTTP GET 请求 `http://localhost:9222/json` 获取 CDP Tab 列表
2. 通过 WebSocket 连接到目标 Tab 的调试端点
3. 使用 `Runtime.evaluate` 在页面上下文中注入 JS 脚本
4. JS 脚本定位 `<iframe name="recommendFrame">` 并通过同源 `contentDocument` 访问 iframe 内容
5. 使用精确 CSS 选择器（`li.card-item`、`.name`、`.base-info` 等）提取候选人数据
6. 结果通过 CDP 返回到 CLI 输出
