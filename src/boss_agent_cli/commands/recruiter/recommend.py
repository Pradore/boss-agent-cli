"""招聘者 — 推荐候选人采集与点击。

通过 CDP 协议连接用户的真实浏览器，在推荐候选人页面上：
- recommend-candidates: 采集候选人卡片，输出结构化 JSON
- recommend-action: 根据 geek_id 点击指定按钮
"""

from __future__ import annotations

from typing import Any, cast

import click

from boss_agent_cli.auth.browser import _DEFAULT_CDP_URL
from boss_agent_cli.commands.recruiter.inspect_page import _load_cdp_tabs, _pick_page_ws
from boss_agent_cli.display import console, handle_auth_errors, handle_error_output, handle_output

from rich.table import Table
from rich.panel import Panel


# ---------------------------------------------------------------------------
# recommend-candidates: 候选人采集 JS 脚本
# ---------------------------------------------------------------------------

_RECOMMEND_SCRIPT = r"""
(() => {
	const sq = (t) => String(t || '').replace(/\s+/g, ' ').trim();

	// 定位 recommendFrame iframe 并获取其 contentDocument
	const iframe = document.querySelector('iframe[name="recommendFrame"]')
		|| Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
	if (!iframe) return { error: 'iframe_not_found', message: 'recommendFrame iframe not found; ensure you are on the recommend page' };

	const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
	if (!doc || !doc.body) return { error: 'iframe_not_ready', message: 'iframe is still loading or cross-origin; wait a moment and retry' };

	const cards = Array.from(doc.querySelectorAll('li.card-item'));
	const limit = __LIMIT__;
	const offset = __OFFSET__;
	const candidates = [];

	for (let i = offset; i < cards.length && candidates.length < limit; i++) {
		const card = cards[i];

		// geek_id — 从 .card-inner[data-geekid] 获取
		const inner = card.querySelector('[data-geekid]');
		const geek_id = inner ? inner.getAttribute('data-geekid') : null;

		// 基本文本字段
		const name = (() => { const el = card.querySelector('.name'); return el ? sq(el.innerText) : null; })();
		const base_info = (() => { const el = card.querySelector('.base-info'); return el ? sq(el.innerText) : null; })();
		const expect = (() => { const el = card.querySelector('.expect-wrap'); return el ? sq(el.innerText) : null; })();
		const edu = (() => { const el = card.querySelector('.edu-exp'); return el ? sq(el.innerText) : null; })();
		const work = (() => { const el = card.querySelector('.work-exps'); return el ? sq(el.innerText).slice(0, 300) : null; })();

		// 标签 — 逐个提取为数组
		const tags = Array.from(card.querySelectorAll('.tag-item')).map(t => sq(t.innerText)).filter(Boolean);

		// 薪资 — 从 .salary-wrap 或卡片全文首部提取
		const salary = (() => {
			const el = card.querySelector('.salary-wrap');
			if (el) return sq(el.innerText);
			const ft = sq(card.innerText);
			const m = ft.match(/^(面议|\d+[kK\-\d]*)/);
			return m ? m[1] : null;
		})();

		// 头像 URL
		const avatar_url = (() => { const el = card.querySelector('img.avatar'); return el ? el.src : null; })();

		// 性别 — 从 svg.gender 图标解析
		const gender = (() => {
			const use = card.querySelector('svg.gender use');
			if (!use) return null;
			const href = use.getAttribute('xlink:href') || use.getAttribute('href') || '';
			if (href.includes('man')) return 'male';
			if (href.includes('woman') || href.includes('female')) return 'female';
			return null;
		})();

		// 打招呼按钮
		const greet_btn = (() => {
			const el = card.querySelector('button.btn-greet') || card.querySelector('.btn-greet');
			return el ? { text: sq(el.innerText), disabled: !!el.disabled } : null;
		})();

		candidates.push({
			index: i + 1,
			geek_id,
			name,
			base_info,
			expect,
			edu,
			work,
			tags,
			salary,
			avatar_url,
			gender,
			greet_btn,
		});
	}

	return {
		page_url: location.href,
		iframe_url: iframe.src || null,
		total_cards: cards.length,
		offset: offset,
		total_found: candidates.length,
		candidates,
	};
})()
"""


def _collect_candidates(cdp_url: str, *, url_contains: str | None = None, limit: int = 30, offset: int = 0) -> dict[str, Any]:
	"""通过 CDP 采集推荐候选人卡片。"""
	import json

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, tab = _pick_page_ws(tabs, url_contains=url_contains)

	script = _RECOMMEND_SCRIPT.replace("__LIMIT__", str(int(limit))).replace("__OFFSET__", str(int(offset)))

	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": script,
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
				raise RuntimeError("CDP recommend script did not return an object")

			# JS 端可能返回错误
			if value.get("error"):
				raise RuntimeError(f"{value['error']}: {value.get('message', '')}")

			value["targetTab"] = {
				"id": tab.get("id"),
				"title": tab.get("title"),
				"url": tab.get("url"),
			}
			return cast("dict[str, Any]", value)


# ---------------------------------------------------------------------------
# recommend-refresh: 向下滚动 iframe 加载更多候选人
# ---------------------------------------------------------------------------

_REFRESH_SCRIPT = r"""
(() => {
	const iframe = document.querySelector('iframe[name="recommendFrame"]')
		|| Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
	if (!iframe) return { scrolled: false, error: 'iframe_not_found', message: 'recommendFrame iframe not found' };

	const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
	if (!doc || !doc.body) return { scrolled: false, error: 'iframe_not_ready', message: 'iframe is still loading or cross-origin' };

	const cardsBefore = doc.querySelectorAll('li.card-item').length;

	// 查找可滚动的候选人列表容器
	const scrollTarget = doc.querySelector('.recommend-card-list')
		|| doc.querySelector('.card-list')
		|| doc.querySelector('[class*="card-list"]')
		|| doc.querySelector('[class*="recommend-list"]')
		|| doc.scrollingElement
		|| doc.documentElement;

	const scrollHeightBefore = scrollTarget.scrollHeight;

	// 滚动到底部，触发懒加载
	scrollTarget.scrollTop = scrollTarget.scrollHeight;

	// 等待 2 秒让新候选人加载
	return new Promise(resolve => {
		setTimeout(() => {
			const cardsAfter = doc.querySelectorAll('li.card-item').length;
			const scrollHeightAfter = scrollTarget.scrollHeight;
			resolve({
				scrolled: true,
				method: 'scroll',
				scroll_target: scrollTarget.className || scrollTarget.tagName,
				cards_before: cardsBefore,
				cards_after: cardsAfter,
				new_cards_loaded: cardsAfter - cardsBefore,
				scroll_height_changed: scrollHeightAfter !== scrollHeightBefore,
				has_more: scrollHeightAfter > scrollHeightBefore,
			});
		}, 2000);
	});
})()
"""


def _refresh_page(cdp_url: str, *, url_contains: str | None = None) -> dict[str, Any]:
	"""通过 CDP 向下滚动推荐页面 iframe，触发懒加载获取更多候选人。"""
	import json

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, _tab = _pick_page_ws(tabs, url_contains=url_contains)

	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": _REFRESH_SCRIPT,
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
			result = message.get("result", {}).get("result", {})
			value = result.get("value") if isinstance(result, dict) else None
			if not isinstance(value, dict):
				raise RuntimeError("CDP refresh script did not return an object")
			return cast("dict[str, Any]", value)


# ---------------------------------------------------------------------------
# recommend-page-reload: 重新加载推荐 iframe
# ---------------------------------------------------------------------------

_PAGE_REFRESH_SCRIPT = r"""
(() => {
	const iframe = document.querySelector('iframe[name="recommendFrame"]')
		|| Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
	if (!iframe) return { refreshed: false, error: 'iframe_not_found', message: 'recommendFrame iframe not found' };

	const beforeDoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
	const cardsBefore = beforeDoc && beforeDoc.body ? beforeDoc.querySelectorAll('li.card-item').length : 0;
	const beforeUrl = iframe.src || null;
	let method = 'iframe_location_reload';

	try {
		if (iframe.contentWindow && iframe.contentWindow.location) {
			iframe.contentWindow.location.reload();
		} else if (beforeUrl) {
			method = 'iframe_src_reset';
			iframe.src = beforeUrl;
		} else {
			return { refreshed: false, error: 'iframe_reload_unavailable', message: 'iframe has no reloadable target' };
		}
	} catch (err) {
		if (!beforeUrl) {
			return { refreshed: false, error: 'iframe_reload_failed', message: String(err && err.message || err) };
		}
		method = 'iframe_src_reset';
		iframe.src = beforeUrl;
	}

	const started = Date.now();
	const timeoutMs = 10000;
	const minStableMs = 3000;

	return new Promise(resolve => {
		const check = () => {
			const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
			const elapsed = Date.now() - started;
			const readyState = doc ? doc.readyState : '';
			const ready = doc && doc.body && (readyState === 'interactive' || readyState === 'complete');
			const docChanged = !!doc && doc !== beforeDoc;

			if (ready && (docChanged || elapsed >= minStableMs)) {
				const cardsAfter = doc.querySelectorAll('li.card-item').length;
				resolve({
					refreshed: true,
					method,
					iframe_url_before: beforeUrl,
					iframe_url_after: iframe.src || null,
					cards_before: cardsBefore,
					cards_after: cardsAfter,
					elapsed_ms: elapsed,
					timed_out: false,
				});
				return;
			}

			if (elapsed >= timeoutMs) {
				const cardsAfter = ready ? doc.querySelectorAll('li.card-item').length : null;
				resolve({
					refreshed: true,
					method,
					iframe_url_before: beforeUrl,
					iframe_url_after: iframe.src || null,
					cards_before: cardsBefore,
					cards_after: cardsAfter,
					elapsed_ms: elapsed,
					timed_out: true,
				});
				return;
			}

			setTimeout(check, 250);
		};
		setTimeout(check, 250);
	});
})()
"""


def _reload_recommend_page(cdp_url: str, *, url_contains: str | None = None) -> dict[str, Any]:
	"""通过 CDP 重新加载推荐 iframe，让推荐页生成新候选人列表。"""
	import json

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, _tab = _pick_page_ws(tabs, url_contains=url_contains)

	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": _PAGE_REFRESH_SCRIPT,
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
				raise RuntimeError("CDP page refresh script did not return an object")
			if value.get("error"):
				raise RuntimeError(f"{value['error']}: {value.get('message', '')}")
			return cast("dict[str, Any]", value)


def _candidate_batch_exhausted(data: dict[str, Any]) -> tuple[bool, str | None]:
	"""判断当前 offset 批次是否已经耗尽。"""
	candidates = data.get("candidates", [])
	candidate_count = len(candidates) if isinstance(candidates, list) else 0
	total_found = int(data.get("total_found", candidate_count) or 0)
	offset = int(data.get("offset", 0) or 0)
	total_cards = int(data.get("total_cards", candidate_count) or 0)
	if offset >= total_cards:
		return True, "offset_exhausted"
	if total_found == 0:
		return True, "empty_batch"
	return False, None


# ---------------------------------------------------------------------------
# recommend-action: 点击 JS 脚本（含确认机制）
# ---------------------------------------------------------------------------

_ACTION_SCRIPT = r"""
((args) => {
	const sq = (t) => String(t || '').replace(/\s+/g, ' ').trim();

	// 定位 recommendFrame iframe
	const iframe = document.querySelector('iframe[name="recommendFrame"]')
		|| Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
	if (!iframe) return { clicked: false, error: 'iframe_not_found', message: 'recommendFrame iframe not found' };

	const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
	if (!doc || !doc.body) return { clicked: false, error: 'iframe_not_ready', message: 'iframe is still loading or cross-origin; wait a moment and retry' };

	// 通过 data-geekid 精确定位候选人卡片（CSS.escape 防注入）
	const geekId = args.geekId;
	const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(geekId) : geekId.replace(/["\\]/g, '\\$&');
	const inner = doc.querySelector('[data-geekid="' + escaped + '"]');
	if (!inner) {
		return { clicked: false, error: 'candidate_not_found', message: 'no card with geekid=' + geekId + ' found; re-run recommend-candidates' };
	}
	const card = inner.closest('li.card-item') || inner;

	// 定位目标按钮
	const buttonText = args.buttonText || '打招呼';
	let btn = card.querySelector('button.btn-greet');
	if (!btn || (buttonText !== '打招呼' && !sq(btn.innerText).includes(buttonText))) {
		// 回退：在卡片内按文本匹配
		const allBtns = Array.from(card.querySelectorAll('button'));
		btn = allBtns.find(b => sq(b.innerText).includes(buttonText));
	}

	if (!btn) {
		const available = Array.from(card.querySelectorAll('button')).map(b => sq(b.innerText)).filter(Boolean);
		return { clicked: false, error: 'button_not_found', message: 'no button matching "' + buttonText + '"', available_buttons: available };
	}

	if (btn.disabled) {
		return { clicked: false, error: 'button_disabled', message: 'button "' + sq(btn.innerText) + '" is already disabled (may have been clicked)' };
	}

	const candidateName = (() => { const el = card.querySelector('.name'); return el ? sq(el.innerText) : null; })();
	const beforeText = sq(btn.innerText);
	const beforeDisabled = btn.disabled;

	// 执行点击
	btn.click();

	// 等待 300ms 后检查变化
	return new Promise((resolve) => {
		setTimeout(() => {
			const afterText = sq(btn.innerText);
			const afterDisabled = btn.disabled || false;

			// 检查 toast（在 iframe 文档和主文档中都查找）
			const toastSelectors = ['.toast', '.el-message', '.ant-message', '[class*="toast"]', '[class*="Toast"]', '[class*="notice"]', '[class*="Notice"]'];
			let toastText = '';
			for (const d of [doc, document]) {
				for (const sel of toastSelectors) {
					const toastEl = d.querySelector(sel);
					if (toastEl) {
						const t = sq(toastEl.innerText).slice(0, 200);
						if (t) { toastText = t; break; }
					}
				}
				if (toastText) break;
			}

			const buttonChanged = afterText !== beforeText;
			const disabledChanged = afterDisabled !== beforeDisabled;
			const confidence = (buttonChanged || disabledChanged || toastText) ? 'high' : 'medium';

			resolve({
				clicked: true,
				geek_id: geekId,
				candidate_name: candidateName,
				button_text: beforeText,
				confirmation: {
					button_changed: buttonChanged,
					old_button_text: beforeText,
					new_button_text: afterText,
					disabled_changed: disabledChanged,
					toast_detected: toastText || null,
					confidence,
				},
			});
		}, 300);
	});
})
"""


def _execute_action(
	cdp_url: str,
	*,
	geek_id: str,
	button_text: str = "打招呼",
	url_contains: str | None = None,
) -> dict[str, Any]:
	"""通过 CDP 在候选人卡片上点击指定按钮。"""
	import json

	import websockets.sync.client as ws_client

	tabs = _load_cdp_tabs(cdp_url)
	target_ws, tab = _pick_page_ws(tabs, url_contains=url_contains)

	with ws_client.connect(target_ws, max_size=8 * 1024 * 1024) as ws:
		args_json = json.dumps({
			"geekId": geek_id,
			"buttonText": button_text,
		})
		ws.send(json.dumps({
			"id": 1,
			"method": "Runtime.evaluate",
			"params": {
				"expression": f"({_ACTION_SCRIPT})({args_json})",
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
				raise RuntimeError("CDP action script did not return an object")
			value["targetTab"] = {
				"id": tab.get("id"),
				"title": tab.get("title"),
				"url": tab.get("url"),
			}
			return cast("dict[str, Any]", value)


# ---------------------------------------------------------------------------
# Click 命令：recommend-candidates
# ---------------------------------------------------------------------------

@click.command("recommend-candidates")
@click.option("--cdp-url", default=None, help="Chrome CDP 地址；默认使用全局 --cdp-url 或 http://localhost:9222")
@click.option("--url-contains", default=None, help="只探测 URL 包含该片段的页面 tab")
@click.option("--limit", default=30, type=int, help="最多采集多少个候选人卡片（默认 30）")
@click.option("--offset", default=0, type=int, help="跳过前 N 个候选人卡片，用于翻页采集（默认 0）")
@click.option("--refresh", "do_refresh", is_flag=True, default=False, help="先滚动加载；目标批次仍为空时刷新推荐页")
@click.pass_context
@handle_auth_errors("recruiter-recommend-candidates")
def recommend_candidates_cmd(ctx: click.Context, cdp_url: str | None, url_contains: str | None, limit: int, offset: int, do_refresh: bool) -> None:
	"""通过 CDP 采集推荐页面候选人卡片（iframe 内），输出结构化 JSON。"""
	resolved_cdp_url = cdp_url or ctx.obj.get("cdp_url") or _DEFAULT_CDP_URL
	try:
		if do_refresh:
			refresh_result = _refresh_page(str(resolved_cdp_url), url_contains=url_contains)
		else:
			refresh_result = None
		data = _collect_candidates(str(resolved_cdp_url), url_contains=url_contains, limit=limit, offset=offset)
		if refresh_result is not None:
			data["refresh_result"] = refresh_result
		if do_refresh:
			exhausted, reason = _candidate_batch_exhausted(data)
			if exhausted:
				page_refresh_result = _reload_recommend_page(str(resolved_cdp_url), url_contains=url_contains)
				page_refresh_result.update({
					"triggered": True,
					"reason": reason,
					"previous_offset": data.get("offset"),
					"previous_total_cards": data.get("total_cards"),
					"previous_total_found": data.get("total_found"),
				})
				data = _collect_candidates(str(resolved_cdp_url), url_contains=url_contains, limit=limit, offset=0)
				data["refresh_result"] = refresh_result
				page_refresh_result["collected_after_refresh"] = data.get("total_found")
				page_refresh_result["total_cards_after_collect"] = data.get("total_cards")
				data["page_refresh_result"] = page_refresh_result
	except RuntimeError as exc:
		handle_error_output(
			ctx,
			"recruiter-recommend-candidates",
			code="CDP_RECOMMEND_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="启动 CDP Chrome，登录并打开推荐候选人页面后重试",
		)
		return
	def _render_candidates(d: dict) -> None:
		candidates = d.get("candidates", [])

		# 显示滚动加载结果
		refresh = d.get("refresh_result")
		if refresh:
			if refresh.get("scrolled"):
				new_loaded = refresh.get("new_cards_loaded", 0)
				console.print(f"[green]✓ 已向下滚动 (新加载 {new_loaded} 人)[/green]")
			else:
				console.print(f"[yellow]⚠ 滚动未成功: {refresh.get('message', '')}[/yellow]")

		page_refresh = d.get("page_refresh_result")
		if page_refresh:
			if page_refresh.get("refreshed"):
				found_after = page_refresh.get("collected_after_refresh", d.get("total_found", 0))
				console.print(f"[green]✓ 已刷新推荐页 (新列表采集 {found_after} 人)[/green]")
			else:
				console.print(f"[yellow]⚠ 推荐页刷新未成功: {page_refresh.get('message', '')}[/yellow]")

		if not candidates:
			console.print("[yellow]no candidates found[/yellow]")
			return

		total_cards = d.get('total_cards', len(candidates))
		offset_val = d.get('offset', 0)
		found = d.get('total_found', len(candidates))
		if offset_val > 0:
			table = Table(title=f"推荐候选人 (本批 {found} 人 / 跳过前 {offset_val} / 页面共 {total_cards} 人)", show_lines=True)
		else:
			table = Table(title=f"推荐候选人 ({found} 人 / 页面共 {total_cards} 人)", show_lines=True)
		table.add_column("#", style="dim", width=3)
		table.add_column("姓名", style="bold cyan", max_width=10)
		table.add_column("性别", width=4)
		table.add_column("基本信息", max_width=28)
		table.add_column("学历", style="green", max_width=28)
		table.add_column("期望", style="blue", max_width=20)
		table.add_column("薪资", style="yellow", max_width=10)
		table.add_column("标签", max_width=16)
		table.add_column("状态", width=8)

		for c in candidates:
			gender_icon = {"male": "♂", "female": "♀"}.get(c.get("gender", ""), "-")
			tags_str = ", ".join(c.get("tags", [])) or "-"
			btn = c.get("greet_btn")
			if btn:
				status = f"[dim]{btn['text']}[/dim]" if btn.get("disabled") else f"[green]{btn['text']}[/green]"
			else:
				status = "-"
			table.add_row(
				str(c.get("index", "")),
				c.get("name", "-"),
				gender_icon,
				c.get("base_info", "-"),
				c.get("edu", "-"),
				c.get("expect", "-"),
				c.get("salary", "-"),
				tags_str,
				status,
			)

		console.print(table)
		console.print("  [dim]使用 boss hr recommend-action <geek_id> 对候选人打招呼[/dim]")

	handle_output(
		ctx,
		"recruiter-recommend-candidates",
		data,
		render=_render_candidates,
		hints={"next_actions": [
			"筛选候选人后使用 boss hr recommend-action <geek_id> 执行打招呼",
			"boss hr recommend-candidates --offset N — 跳过前 N 人，采集下一批",
			"boss hr recommend-candidates --refresh — 先滚动，耗尽时刷新推荐页获取新候选人",
			"boss hr inspect-page — 查看页面详细探测结果",
		]},
	)


# ---------------------------------------------------------------------------
# Click 命令：recommend-action
# ---------------------------------------------------------------------------

@click.command("recommend-action")
@click.argument("geek_id")
@click.option("--button", default="打招呼", help="要点击的按钮文本（默认 打招呼）")
@click.option("--cdp-url", default=None, help="Chrome CDP 地址；默认使用全局 --cdp-url 或 http://localhost:9222")
@click.option("--url-contains", default=None, help="只探测 URL 包含该片段的页面 tab")
@click.pass_context
@handle_auth_errors("recruiter-recommend-action")
def recommend_action_cmd(
	ctx: click.Context,
	geek_id: str,
	button: str,
	cdp_url: str | None,
	url_contains: str | None,
) -> None:
	"""根据 geek_id 在候选人卡片上点击指定按钮。

	geek_id 由 recommend-candidates 命令输出。
	两段式流程：先采集、再点击，降低误操作风险。
	"""
	resolved_cdp_url = cdp_url or ctx.obj.get("cdp_url") or _DEFAULT_CDP_URL
	try:
		data = _execute_action(
			str(resolved_cdp_url),
			geek_id=geek_id,
			button_text=button,
			url_contains=url_contains,
		)
	except RuntimeError as exc:
		handle_error_output(
			ctx,
			"recruiter-recommend-action",
			code="CDP_ACTION_FAILED",
			message=str(exc),
			recoverable=True,
			recovery_action="确认 CDP Chrome 仍在运行且推荐候选人页面已打开",
		)
		return

	if not data.get("clicked"):
		error_code = data.get("error", "ACTION_FAILED")
		handle_error_output(
			ctx,
			"recruiter-recommend-action",
			code=error_code.upper(),
			message=data.get("message", "操作未成功"),
			recoverable=True,
			recovery_action="使用 boss hr recommend-candidates 重新采集后再试",
			hints={"available_buttons": data.get("available_buttons")} if data.get("available_buttons") else None,
		)
		return

	def _render_action(d: dict) -> None:
		conf = d.get("confirmation", {})
		confidence = conf.get("confidence", "unknown")
		conf_color = {"high": "green", "medium": "yellow"}.get(confidence, "red")

		lines = [
			f"[bold cyan]候选人:[/bold cyan] {d.get('candidate_name', '-')}",
			f"[bold]geek_id:[/bold] {d.get('geek_id', '-')}",
			f"[bold]按钮:[/bold] {conf.get('old_button_text', '-')} → {conf.get('new_button_text', '-')}",
			f"[bold]置信度:[/bold] [{conf_color}]{confidence}[/{conf_color}]",
		]
		if conf.get("toast_detected"):
			lines.append(f"[bold]提示:[/bold] {conf['toast_detected']}")

		panel = Panel("\n".join(lines), title="✅ 操作成功", border_style="green")
		console.print(panel)

	handle_output(
		ctx,
		"recruiter-recommend-action",
		data,
		render=_render_action,
		hints={"next_actions": [
			"boss hr recommend-candidates — 重新采集查看最新状态",
			"boss hr chat — 查看沟通列表确认操作结果",
		]},
	)


__all__ = [
	"recommend_candidates_cmd",
	"recommend_action_cmd",
	"_collect_candidates",
	"_refresh_page",
	"_reload_recommend_page",
	"_execute_action",
]
