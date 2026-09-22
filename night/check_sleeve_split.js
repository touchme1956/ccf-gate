#!/usr/bin/env node
/* night/check_sleeve_split.js — 入金総額を城/網へどう割るかを実ブラウザで確かめる
 *
 * ■ なぜ要るか（実害）
 *   2026-09-22、ユーザーが総額に 100万 を入れたら **全額が網へ**行った。
 *   これは故障ではなく v9.9.167（2026-08-21 ユーザー明示指示「足りないものから順番に投資する」）の
 *   設計どおり——城 47.7% が目標 30% を 17.7pt 超過していたので取り分が 0 になった。
 *   ユーザー指示「常に網70%城30%になるように配れるような仕様にしてほしい」で
 *   `portfolio.json` の `target.sleeve_split_mode` を新設し `target`（常に目標比）を既定にした。
 *
 * ■ 判定
 *   ① mode='target' … 100万 → 城30万 / 網70万（今の姿に関係なく）
 *   ② 合計が総額にぴったり一致する（端数を寄せる規約）
 *   ③ 採らなかったほう（不足按分）の金額を画面に併記する（v9.9.52＝どちらも隠さない）
 *   ④ mode='gap' に戻すと v9.9.167 の挙動（超過側は0）へ戻る＝1語で可逆
 *   ⑤ 比率を変えると（城50/網50）追随する＝比率を書き写していない
 *
 * playwright が要るので CI には入れていない。使い方: node night/check_sleeve_split.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8795;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

let OVER = null;                      // portfolio.json を差し替えて配る（正本は触らない）
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  if (OVER && rel.endsWith('/portfolio.json')) {
    r.writeHead(200, { 'Content-Type': 'application/json' }); r.end(JSON.stringify(OVER)); return;
  }
  let f = path.join(ROOT, rel);
  if (f.endsWith('/')) f += 'index.html';
  try {
    const b = fs.readFileSync(f);
    r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript'
      : f.endsWith('.json') ? 'application/json' : 'text/html' });
    r.end(b);
  } catch (e) { r.writeHead(404); r.end('x'); }
});

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const base = JSON.parse(fs.readFileSync(path.join(ROOT, 'portfolio.json'), 'utf8'));
  const b = await chromium.launch({ executablePath: CHROME });
  const pg = await b.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  let ng = 0;
  const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

  // 総額を入れて ccfSleeveSplit() を直接読む（表示層でなく判定そのものを見る）
  const split = async (yen) => pg.evaluate(y => {
    localStorage.setItem('pf:monthly_total', String(y));
    return ccfSleeveSplit();
  }, yen);

  const load = async (over) => {
    OVER = over;
    await pg.goto('http://localhost:' + PORT + '/index.html');
    await pg.waitForTimeout(1200);
    // ⚠ Ⅵ買付順位は**クリックされるまで描かれない**ので、renderPlan の中で置かれる
    //   window.__ccfSleeveTarget もそれまで null＝mode が 'unknown' へ倒れる。
    //   初版はここで躓いた（「測っていない」が「目標比で割った」に見える経路そのもの）。
    await pg.evaluate(() => showPage(5));
    await pg.waitForTimeout(2600);            // renderPlan が portfolio.json を読み終わるまで
  };

  console.log('■ 総額の割り方（night/check_sleeve_split.js）');

  // ① 既定＝正本のまま（城30 / 網70・mode target）
  await load(null);
  let sp = await split(1000000);
  const now = sp && sp.now ? sp.now : null;
  console.log('   今の袖: ' + (now ? '城' + now.c.toFixed(1) + '% / 網' + now.n.toFixed(1) + '%' : '(読めず)')
    + '　目標 城' + (sp && sp.cPct) + ' / 網' + (sp && sp.nPct) + '　mode=' + (sp && sp.mode));
  ok(sp && sp.mode === 'fixed', '① mode=fixed（常に目標比）');
  ok(sp && sp.castle === 300000 && sp.net === 700000,
     '   100万 → 城 ' + (sp && sp.castle && sp.castle.toLocaleString()) + ' / 網 ' + (sp && sp.net && sp.net.toLocaleString()) + '（城30万/網70万が正）');
  ok(sp && (sp.castle + sp.net) === 1000000, '② 合計が総額にぴったり一致');
  ok(sp && sp.gCastle === 0, '③ 採らなかったほう（不足按分）も持っている＝画面に併記できる（城 ' + (sp && sp.gCastle) + '）');
  // ⚠ 帯は renderPlan のときの localStorage を見て描かれるので、**総額を入れてから描き直す**
  //   （split() は判定を直接呼ぶだけで画面を更新しない）。ここを飛ばすと
  //   「総額が未入力の画面」を読んで落ちる＝道具の側の誤り。
  await pg.evaluate(() => ccfSetTotalAmt({ value: '1000000' }));
  await pg.waitForTimeout(1200);
  const txt = await pg.locator('#pg5').innerText().catch(() => '');
  ok(/常に目標比/.test(txt), '   画面に「常に目標比」と出る');
  ok(/足りないほうから/.test(txt), '   画面に不足按分の金額も併記される（どちらも隠さない）');

  // ④ mode='gap' へ戻すと v9.9.167 の挙動
  const g = JSON.parse(JSON.stringify(base)); g.target.sleeve_split_mode = 'gap';
  await load(g);
  sp = await split(1000000);
  ok(sp && sp.mode === 'gap', '④ mode=gap へ戻る（1語で可逆）');
  ok(sp && sp.castle === 0 && sp.net === 1000000,
     '   城が目標超過なので 城 ¥0 / 網 ¥1,000,000＝2026-09-22 に見えた挙動を再現');

  // ⑤ 比率を変えると追随する（書き写していない）
  const h = JSON.parse(JSON.stringify(base)); h.target.shiro_castle_pct = 50; h.target.ami_net_pct = 50;
  await load(h);
  sp = await split(1000000);
  ok(sp && sp.castle === 500000 && sp.net === 500000,
     '⑤ 城50/網50 にすると 城¥500,000 / 網¥500,000＝比率を書き写していない');

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  await pg.evaluate(() => localStorage.removeItem('pf:monthly_total'));
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
