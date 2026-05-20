"""招聘者 — CDP 页面探测。"""

from typing import Any, cast

import click

from boss_agent_cli.auth.browser import _DEFAULT_CDP_URL
from boss_agent_cli.display import console, handle_auth_errors, handle_error_output, handle_output

from rich.panel import Panel


_INSPECT_SCRIPT = r"""
() => {
	const squash = (text) => String(text || '').replace(/\s+/g, ' ').trim();
	const clip = (text, limit) => {
		const value = squash(text);
		return value.length > limit ? value.slice(0, limit) + '...' : value;
	};
	const buttonText = (root) => Array.from(root.querySelectorAll('button,a,[role="button"]'))
		.map((el) => ({
			text: clip(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title'), 80),
			tag: el.tagName,
			className: String(el.className || '').slice(0, 160),
			href: el.href || '',
		}))
		.filter((item) => item.text);

	const keywordRe = /(本科|硕士|博士|大专|毕业|大学|学院|学校|应届|经验|岁|候选人|沟通|打招呼|感兴趣|简历)/;
	const actionRe = /(打招呼|沟通|感兴趣|查看|简历|联系|交换|不合适|邀约|收藏|约聊)/;
	const nodes = Array.from(document.querySelectorAll('div,li,section,article'));
	const candidateBlocks = [];
	const seen = new Set();

	for (const [domIndex, el] of nodes.entries()) {
		const text = squash(el.innerText || el.textContent || '');
		if (text.length < 40 || text.length > 2000 || !keywordRe.test(text)) continue;
		const buttons = buttonText(el);
		if (!buttons.some((button) => actionRe.test(button.text))) continue;

		const key = text.slice(0, 240);
		if (seen.has(key)) continue;
		seen.add(key);

		candidateBlocks.push({
			index: candidateBlocks.length + 1,
			domIndex,
			tag: el.tagName,
			className: String(el.className || '').slice(0, 200),
			text: clip(text, 600),
			buttons,
		});
		if (candidateBlocks.length >= 30) break;
	}

	// 检测 recommendFrame iframe 并输出摘要
	let iframe_summary = null;
	const iframe = document.querySelector('iframe[name="recommendFrame"]')
		|| Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
	if (iframe) {
		const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
		if (doc && doc.body) {
			const cards = doc.querySelectorAll('li.card-item');
			const greetBtns = doc.querySelectorAll('.btn-greet');
			iframe_summary = {
				iframe_url: iframe.src || null,
				total_cards: cards.length,
				total_greet_btns: greetBtns.length,
				body_text_length: (doc.body.innerText || '').length,
				sample_names: Array.from(cards).slice(0, 5).map(c => {
					const n = c.querySelector('.name');
					return n ? squash(n.innerText) : null;
				}).filter(Boolean),
			};
		} else {
			iframe_summary = { iframe_url: iframe.src || null, error: 'cannot access contentDocument' };
		}
	}

	return {
		url: location.href,
		title: document.title,
		readyState: document.readyState,
		bodyTextSample: clip(document.body ? document.body.innerText : '', 1200),
		buttons: buttonText(document).slice(0, 80),
		candidateBlocks,
		iframe_summary,
	};
}
"""


def _load_cdp_tabs(cdp_url: str) -> list[dict[str, Any]]:
	import json
	import urllib.request

	list_url = cdp_url.rstrip("/") + "/json"
	try:
		with urllib.request.urlopen(list_url, timeout=3) as response:
			payload = json.load(response)
	except Exception as exc:
		raise RuntimeError(f"cannot reach CDP at {list_url}: {exc}") from exc
	if isinstance(payload, dict) and isinstance(payload.get("value"), list):
		payload = payload["value"]
	if not isinstance(payload, list):
		raise RuntimeError(f"unexpected CDP /json payload type: {type(payload).__name__}")
	return [tab for tab in payload if isinstance(tab, dict)]


def _pick_page_ws(tabs: list[dict[str, Any]], *, url_contains: str | None) -> tuple[str, dict[str, Any]]:
	page_tabs = [
		tab
		for tab in tabs
		if tab.get("type") == "page"
		and isinstance(tab.get("webSocketDebuggerUrl"), str)
		and not str(tab.get("url") or "").startswith(("devtools://", "about:", "view-source:"))
	]
	if url_contains:
		page_tabs = [tab for tab in page_tabs if url_contains in str(tab.get("url") or "")]
	if not page_tabs:
		raise RuntimeError("no inspectable page tab found; open the target BOSS page in CDP Chrome first")
	for tab in page_tabs:
		if "zhipin.com" in str(tab.get("url") or ""):
			return cast("str", tab["webSocketDebuggerUrl"]), tab
	return cast("str", page_tabs[0]["webSocketDebuggerUrl"]), page_tabs[0]


def inspect_cdp_page(cdp_url: str, *, url_contains: str | None = None) -> dict[str, Any]:
	import json

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, tab = _pick_page_ws(tabs, url_contains=url_contains)
	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": f"({_INSPECT_SCRIPT})()",
				"returnByValue": True,
				"awaitPromise": True,
			},
		}))
		while True:
			message = json.loads(ws.recv(timeout=30.0))
			if message.get("id") != 1:
				continue
			if message.get("error"):
				raise RuntimeError(f"CDP Runtime.evaluate error: {message['error']}")
			if message.get("result", {}).get("exceptionDetails"):
				raise RuntimeError(f"JS exception: {message['result']['exceptionDetails']}")
			result = message.get("result", {}).get("result", {})
			value = result.get("value") if isinstance(result, dict) else None
			if not isinstance(value, dict):
				raise RuntimeError("CDP inspect script did not return an object")
			value["targetTab"] = {
				"id": tab.get("id"),
				"title": tab.get("title"),
				"url": tab.get("url"),
			}
			return cast("dict[str, Any]", value)


@click.command("inspect-page")
@click.option("--cdp-url", default=None, help="Chrome CDP 地址；默认使用全局 --cdp-url 或 http://localhost:9222")
@click.option("--url-contains", default=None, help="只探测 URL 包含该片段的页面 tab")
@click.pass_context
@handle_auth_errors("recruiter-inspect-page")
def inspect_page_cmd(ctx: click.Context, cdp_url: str | None, url_contains: str | None) -> None:
	"""通过 CDP 后台探测当前页面候选人卡片和按钮（不打开 DevTools）。"""
	resolved_cdp_url = cdp_url or ctx.obj.get("cdp_url") or _DEFAULT_CDP_URL
	try:
		data = inspect_cdp_page(str(resolved_cdp_url), url_contains=url_contains)
	except RuntimeError as exc:
		handle_error_output(
			ctx,
			"recruiter-inspect-page",
			code="CDP_INSPECT_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="启动 CDP Chrome，登录并打开目标页面后重试",
		)
		return
	def _render_inspect(d: dict) -> None:
		lines = [
			f"[bold]URL:[/bold] {d.get('page_url', '-')}",
			f"[bold]Title:[/bold] {d.get('page_title', '-')}",
		]
		iframe = d.get("iframe_summary")
		if iframe:
			lines.append(f"\n[bold cyan]iframe:[/bold cyan] {iframe.get('iframe_src', '-')}")
			lines.append(f"  cards: {iframe.get('card_count', 0)}, greet buttons: {iframe.get('greet_btn_count', 0)}")
		blocks = d.get("candidateBlocks", [])
		if blocks:
			lines.append(f"\n[bold]candidateBlocks:[/bold] {len(blocks)} 个")
		panel = Panel("\n".join(lines), title="页面探测结果", border_style="cyan")
		console.print(panel)

	handle_output(
		ctx,
		"recruiter-inspect-page",
		data,
		render=_render_inspect,
		hints={"next_actions": ["把 candidateBlocks 输出发给开发者，用于确定推荐候选人页面选择器"]},
	)


# ---------------------------------------------------------------------------
# CDP 页面导航
# ---------------------------------------------------------------------------

def navigate_cdp_page(
	cdp_url: str,
	url: str,
	*,
	url_contains: str | None = None,
	wait_seconds: float = 2.0,
) -> dict[str, Any]:
	"""通过 CDP Page.navigate 切换当前 Tab 的 URL，等待加载完成。"""
	import json
	import time

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, tab = _pick_page_ws(tabs, url_contains=url_contains)

	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		# 发送导航命令
		ws.send(json.dumps({
			"id": 1,
			"method": "Page.navigate",
			"params": {"url": url},
		}))
		while True:
			message = json.loads(ws.recv(timeout=30.0))
			if message.get("id") != 1:
				continue
			if message.get("error"):
				raise RuntimeError(f"CDP Page.navigate error: {message['error']}")
			nav_result = message.get("result", {})
			if nav_result.get("errorText"):
				raise RuntimeError(f"navigation failed: {nav_result['errorText']}")
			break

		# 等待页面加载
		time.sleep(wait_seconds)

		# 获取导航后的页面信息
		ws.send(json.dumps({
			"id": 2,
			"method": "Runtime.evaluate",
			"params": {
				"expression": "({url: location.href, title: document.title, readyState: document.readyState})",
				"returnByValue": True,
			},
		}))
		page_info: dict[str, Any] = {}
		while True:
			message = json.loads(ws.recv(timeout=10.0))
			if message.get("id") != 2:
				continue
			page_info = message.get("result", {}).get("result", {}).get("value", {})
			break

	return {
		"navigated_to": url,
		"page_url": page_info.get("url", url),
		"page_title": page_info.get("title", ""),
		"ready_state": page_info.get("readyState", ""),
		"previous_url": tab.get("url", ""),
		"targetTab": {
			"id": tab.get("id"),
			"title": tab.get("title"),
			"url": tab.get("url"),
		},
	}


@click.command("navigate")
@click.argument("url")
@click.option("--cdp-url", default=None, help="Chrome CDP 地址；默认使用全局 --cdp-url 或 http://localhost:9222")
@click.option("--url-contains", default=None, help="只探测 URL 包含该片段的页面 tab")
@click.option("--wait", default=2.0, type=float, help="导航后等待页面加载的秒数（默认 2.0）")
@click.pass_context
@handle_auth_errors("recruiter-navigate")
def navigate_cmd(ctx: click.Context, url: str, cdp_url: str | None, url_contains: str | None, wait: float) -> None:
	"""通过 CDP 将当前页面导航到指定 URL。"""
	resolved_cdp_url = cdp_url or ctx.obj.get("cdp_url") or _DEFAULT_CDP_URL
	try:
		data = navigate_cdp_page(str(resolved_cdp_url), url, url_contains=url_contains, wait_seconds=wait)
	except RuntimeError as exc:
		handle_error_output(
			ctx,
			"recruiter-navigate",
			code="CDP_NAVIGATE_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="确认 CDP Chrome 仍在运行且有可用的页面 Tab",
		)
		return
	def _render_navigate(d: dict) -> None:
		lines = [
			f"[bold]之前:[/bold] {d.get('previous_url', '-')}",
			f"[bold]当前:[/bold] {d.get('page_url', '-')}",
			f"[bold]标题:[/bold] {d.get('page_title', '-')}",
			f"[bold]状态:[/bold] {d.get('ready_state', '-')}",
		]
		panel = Panel("\n".join(lines), title="✅ 页面导航完成", border_style="green")
		console.print(panel)

	handle_output(
		ctx,
		"recruiter-navigate",
		data,
		render=_render_navigate,
		hints={"next_actions": [
			"boss hr recommend-candidates — 采集推荐候选人",
			"boss hr inspect-page — 探测页面内容",
		]},
	)


__all__ = ["inspect_cdp_page", "inspect_page_cmd", "navigate_cdp_page", "navigate_cmd"]
