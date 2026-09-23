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

  // ★検査は**正本の既定値を写さない**。mode を明示して両方の挙動を固定し、
  //   「今どちらが選ばれているか」は portfolio.json から読んで**報告するだけ**にする。
  //   ⚠初版は既定を 'target' と書き写していたので、2026-09-22 に正本を 'gap' へ戻した瞬間に
  //     4件が落ちた——コードは正しいのに検査だけが古い値で鳴る、この台帳が繰り返し踏んだ型。
  const withMode = (m) => { const o = JSON.parse(JSON.stringify(base)); o.target.sleeve_split_mode = m; return o; };

  // ① mode='target' … 今の姿に関係なく常に目標比
  await load(withMode('target'));
  let sp = await split(1000000);
  const now = sp && sp.now ? sp.now : null;
  console.log('   今の袖: ' + (now ? '城' + now.c.toFixed(1) + '% / 網' + now.n.toFixed(1) + '%' : '(読めず)')
    + '　目標 城' + (sp && sp.cPct) + ' / 網' + (sp && sp.nPct));
  ok(sp && sp.mode === 'fixed', "① mode='target' → fixed（常に目標比）");
  // ⚠ 期待値も**正本の比率から作る**（初版は 30/70 を書き写しており、v9.9.188 で 20/80 へ変えた瞬間に鳴った）
  const wantC = sp ? Math.round(1000000 * sp.cPct / (sp.cPct + sp.nPct)) : NaN;
  ok(sp && sp.castle === wantC && sp.net === 1000000 - wantC,
     '   100万 → 城 ' + (sp && sp.castle && sp.castle.toLocaleString()) + ' / 網 ' + (sp && sp.net && sp.net.toLocaleString())
     + '（目標比 ' + (sp && sp.cPct) + ':' + (sp && sp.nPct) + ' なら 城' + (isFinite(wantC) ? wantC.toLocaleString() : '?') + 'が正）');
  ok(sp && (sp.castle + sp.net) === 1000000, '   合計が総額にぴったり一致');
  await pg.evaluate(() => ccfSetTotalAmt({ value: '1000000' }));
  await pg.waitForTimeout(1200);
  let txt = await pg.locator('#pg5').innerText().catch(() => '');
  ok(/常に目標比/.test(txt), '   画面に「常に目標比」と出る');
  ok(/足りないほうから/.test(txt), '   採らなかったほう（不足按分）も併記＝どちらも隠さない');

  // ② mode='gap' … 不足側に厚く（超過側は0）
  await load(withMode('gap'));
  sp = await split(1000000);
  ok(sp && sp.mode === 'gap', "② mode='gap' → 不足側に厚く");
  ok(sp && sp.castle === 0 && sp.net === 1000000,
     '   城が目標超過なので 城 ¥0 / 網 ¥1,000,000（2026-09-22 に見えた挙動）');
  ok(sp && (sp.castle + sp.net) === 1000000, '   合計が総額にぴったり一致');
  await pg.evaluate(() => ccfSetTotalAmt({ value: '1000000' }));
  await pg.waitForTimeout(1200);
  txt = await pg.locator('#pg5').innerText().catch(() => '');
  ok(/足りないほうから/.test(txt), '   画面に「足りないほうから」と出る');
  ok(/目標比/.test(txt), '   採らなかったほう（目標比）も併記＝どちらも隠さない');

  // ③ 城が目標を下回れば gap でも城へ配る＝恒久的に0ではない
  const under = JSON.parse(JSON.stringify(base));
  under.target.sleeve_split_mode = 'gap';
  under.target.shiro_castle_pct = 80; under.target.ami_net_pct = 20;   // 城を大きく不足させる
  await load(under);
  sp = await split(1000000);
  ok(sp && sp.castle > 0 && sp.net === 0,
     '③ 城が目標を下回ると gap でも城へ配る（城 ¥' + (sp && sp.castle && sp.castle.toLocaleString()) + '）＝恒久的に0ではない');

  // ④ 比率を変えると追随する（書き写していない）
  await load(Object.assign(withMode('target'), { target: Object.assign({}, base.target, { sleeve_split_mode: 'target', shiro_castle_pct: 50, ami_net_pct: 50 }) }));
  sp = await split(1000000);
  ok(sp && sp.castle === 500000 && sp.net === 500000,
     '④ 城50/網50 にすると 城¥500,000 / 網¥500,000＝比率を書き写していない');

  // ⑤ 正本がいまどちらを選んでいるかは**読んで報告するだけ**（期待値を書き写さない）
  const live = String((base.target && base.target.sleeve_split_mode) || 'target').toLowerCase();
  await load(null);
  sp = await split(1000000);
  const want = (live === 'gap') ? 'gap' : 'fixed';
  ok(sp && sp.mode === want,
     "⑤ 正本(portfolio.json)の mode='" + live + "' が門にそのまま効いている（判定 " + (sp && sp.mode) + '）'
     + ' → 城 ¥' + (sp && sp.castle && sp.castle.toLocaleString()) + ' / 網 ¥' + (sp && sp.net && sp.net.toLocaleString()));

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  await pg.evaluate(() => localStorage.removeItem('pf:monthly_total'));
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
