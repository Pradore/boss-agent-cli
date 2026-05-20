"""CDP iframe DOM 探测脚本 — 通过主文档访问同源 recommendFrame 的 contentDocument。"""

import json

import urllib.request

import websockets.sync.client as ws_client


def main() -> None:
    tabs = json.load(urllib.request.urlopen("http://localhost:9222/json", timeout=3))
    tab = [t for t in tabs if "recommend" in t.get("url", "")][0]
    ws_url = tab["webSocketDebuggerUrl"]
    print(f"Tab: {tab['url']}")

    with ws_client.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
        # 同源 iframe 可直接通过 contentDocument 访问，无需切换 context
        script = r"""(() => {
            const sq = t => String(t||'').replace(/\s+/g,' ').trim();

            // 找到 recommendFrame iframe
            const iframe = document.querySelector('iframe[name="recommendFrame"]')
                || Array.from(document.querySelectorAll('iframe')).find(f => f.src && f.src.includes('frame/recommend'));
            if (!iframe) return { error: 'recommendFrame iframe not found' };

            const doc = iframe.contentDocument || iframe.contentWindow.document;
            if (!doc || !doc.body) return { error: 'cannot access iframe contentDocument (cross-origin?)' };

            const cards = Array.from(doc.querySelectorAll('li.card-item'));
            return {
                iframe_url: iframe.src,
                total_cards: cards.length,
                total_greet_btns: doc.querySelectorAll('.btn-greet').length,
                body_text_len: (doc.body.innerText||'').length,
                cards: cards.slice(0,3).map((card, i) => ({
                    index: i,
                    card_cls: String(card.className||''),
                    name: (() => { const el = card.querySelector('.name'); return el ? sq(el.innerText) : null; })(),
                    base_info: (() => { const el = card.querySelector('.base-info'); return el ? sq(el.innerText) : null; })(),
                    expect: (() => { const el = card.querySelector('.expect-wrap'); return el ? sq(el.innerText) : null; })(),
                    edu: (() => { const el = card.querySelector('.edu-exp'); return el ? sq(el.innerText) : null; })(),
                    work: (() => { const el = card.querySelector('.work-exps'); return el ? sq(el.innerText).slice(0,200) : null; })(),
                    tags: (() => { const el = card.querySelector('.tags'); return el ? sq(el.innerText) : null; })(),
                    salary: (() => {
                        const ft = sq(card.innerText);
                        const m = ft.match(/^(面议|\d+[kK\-\d]*)/);
                        return m ? m[1] : null;
                    })(),
                    greet_btn: (() => {
                        const el = card.querySelector('.btn-greet');
                        return el ? { text: sq(el.innerText), tag: el.tagName, disabled: el.disabled } : null;
                    })(),
                    full_text: sq(card.innerText).slice(0,400),
                })),
            };
        })()"""

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
            m = json.loads(ws.recv(timeout=30))
            if m.get("id") == 1:
                result = m.get("result", {}).get("result", {})
                val = result.get("value")
                if val:
                    print(json.dumps(val, ensure_ascii=False, indent=2))
                else:
                    exc = m.get("result", {}).get("exceptionDetails")
                    if exc:
                        print(f"JS Exception: {json.dumps(exc, ensure_ascii=False)}")
                    else:
                        print(f"Full response: {json.dumps(m, ensure_ascii=False)[:800]}")
                break


if __name__ == "__main__":
    main()
