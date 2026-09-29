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
  // ★'name'（2026-09-25 新設・銘柄ごとの不足から）は台帳が空のこの検査では材料（銘柄の不足）が無いので
  //   門は 'gap_fallback' と**名乗って** gap へ倒す＝どちらも「正本の name が効いている」の正しい姿
  const want = (live === 'gap') ? ['gap'] : (live === 'name') ? ['name', 'gap_fallback'] : ['fixed'];
  ok(sp && want.includes(sp.mode),
     "⑤ 正本(portfolio.json)の mode='" + live + "' が門にそのまま効いている（判定 " + (sp && sp.mode) + '）'
     + ' → 城 ¥' + (sp && sp.castle && sp.castle.toLocaleString()) + ' / 網 ¥' + (sp && sp.net && sp.net.toLocaleString()));

  // ⑥ mode='name' … 銘柄ごとの不足の合計の比で割る（材料を与えて判定そのものを見る）
  await load(withMode('name'));
  sp = await pg.evaluate(() => { window.__ccfNameGap = { c: 1, n: 3 }; localStorage.setItem('pf:monthly_total', '1000000'); return ccfSleeveSplit(); });
  ok(sp && sp.mode === 'name' && sp.castle === 250000 && sp.net === 750000,
     "⑥ mode='name' → 銘柄の不足 個別1:ETF3 なら 城¥250,000 / 網¥750,000（判定 " + (sp && sp.mode) + ' / 城 ¥' + (sp && sp.castle && sp.castle.toLocaleString()) + '）');
  sp = await pg.evaluate(() => { window.__ccfNameGap = undefined; return ccfSleeveSplit(); });
  ok(sp && sp.mode === 'gap_fallback', "   材料が無ければ 'gap_fallback' と名乗って gap へ倒す（黙って別の割り方にしない）");

  // ⑦ 1株単位の注文（v9.9.196・2026-09-29）: 合成の数字で判定そのものを見る
  //   総資産 242万・入金17万。CW/LRCX/TDG は保有0・目標4%、MSFT は目標4%に対し26%、SMH は目標20%に対し15.7%、
  //   iFreeNEXT（金額で買える）は目標60%。期待: 不足÷目標の大きい CW・LRCX を1株ずつ（安い LRCX が先）、
  //   SMH は残りが1株に届かず来月、TDG は1株(17.7万)が入金より高い、残り ¥34,400 は全部 iFreeNEXT、現金は残さない
  const ws = await pg.evaluate(() => ccfWholeSharePlan([
    { k: 'CW', tw: 4, pos: 0, jpy: 85600 }, { k: 'LRCX', tw: 4, pos: 0, jpy: 50000 },
    { k: 'TDG', tw: 4, pos: 0, jpy: 177000 }, { k: 'MSFT', tw: 4, pos: 26, jpy: 79000 },
    { k: 'SMH', tw: 20, pos: 15.7, jpy: 95800 }, { k: 'IFREE', tw: 60, pos: 16, frac: true }], 170000, 2420000));
  ok(ws && ws.buy.CW && ws.buy.CW.sh === 1 && ws.buy.LRCX && ws.buy.LRCX.sh === 1 && !ws.buy.MSFT && !ws.buy.SMH,
     '⑦ 1株単位: 保有0の CW・LRCX を1株ずつ・目標超過の MSFT は買わない（' + JSON.stringify(ws && ws.buy) + '）');
  ok(ws && ws.big.some(x => x.k === 'TDG') && ws.short.some(x => x.k === 'SMH'),
     '   TDG は「1株が入金より高い」・SMH は「今月は先の銘柄で尽きた」と名指し');
  ok(ws && ws.frac.IFREE === 34400 && ws.rest === 0,
     '   残り ¥34,400 は全部 iFreeNEXT へ・現金は残さない（frac ' + (ws && ws.frac.IFREE) + ' / rest ' + (ws && ws.rest) + '）');
  const ws2 = await pg.evaluate(() => ccfWholeSharePlan([
    { k: 'A', tw: 4, pos: 3.9, jpy: 50000 }, { k: 'F', tw: 60, pos: 70, frac: true }], 170000, 2420000));
  ok(ws2 && !ws2.buy.A && ws2.wait.some(x => x.k === 'A') && ws2.frac.F === 170000,
     '   不足が1株の半分未満なら待つ・投資信託が目標超過でも残りの円はそこへ（現金で残さない）');
  // ⑧ 注文書の表示: 口座（NISA のどの枠か）と「特定口座では買わない」が出る
  const html = await pg.evaluate(() => {
    const px = { CW: 85600, LRCX: 50000 };
    const pass = [{ nm: 'CW', t: 'CW', pos: 0 }, { nm: 'LRCX', t: 'LRCX', pos: 0 }, { nm: 'VRSK', t: 'VRSK', pos: 0 }];
    const tw = r => (r.t === 'VRSK' ? 0 : 4);
    const pxInfo = r => px[r.t] ? { jpy: px[r.t], px: px[r.t] / 150, ccy: 'USD', label: '$' + (px[r.t] / 150).toFixed(2) } : null;
    const NO = { tot: 2420000, rows: [{ t: 'IFREE-NDX', nm: 'iFreeNEXT', tw: 60, pos: 16, jpy: 5.8, fund: { navPer: 10000 }, alias: [] },
      { t: 'SMH', tw: 20, pos: 15.7, jpy: 95800, label: '1株 ¥95,800' }, { t: 'XLK', tw: 0, pos: 30, jpy: 30000 }] };
    return ccfWholeShareBody(pass, tw, pxInfo, NO, 170000);
  });
  ok(html && /NISA成長/.test(html.html) && /NISAつみたて/.test(html.html) && /特定口座では買わない/.test(html.html),
     '⑧ 注文書に口座（NISA成長／NISAつみたて）と「特定口座では買わない」が出る');
  ok(html && !/VRSK/.test(html.html) && /XLK：目標0%/.test(html.html.replace(/<[^>]+>/g, '')),
     '   目標0%の門外例外（VRSK）は出さない・目標0%の ETF は「目標0%（売らない）」とまとめる');
  ok(html && (html.castle + html.net + html.rest) === 170000,
     '   個別＋ETF＋残り＝入金額にぴったり（個別 ' + (html && html.castle) + ' / ETF ' + (html && html.net) + ' / 残り ' + (html && html.rest) + '）');
  // ⑨ 門外例外の出口条件（watch_exceptions の exit_stop）が立った社は今月の注文から外す（売りではない）
  const stop = await pg.evaluate(() => {
    const keep = window.__ccfExWatch;
    window.__ccfExWatch = { CW: { t: 'CW', exit_stop: true, intcov_ttm: 1.8, exit_intcov_min: 2, asof: '2026-06-27' } };
    const pxInfo = r => ({ jpy: 85600, px: 570, ccy: 'USD', label: '$570' });
    const o = ccfWholeShareBody([{ nm: 'CW', t: 'CW', pos: 0 }], () => 4, pxInfo,
      { tot: 2420000, rows: [{ t: 'IFREE-NDX', nm: 'iFreeNEXT', tw: 60, pos: 16, jpy: 5.8, fund: { navPer: 10000 }, alias: [] }] }, 170000);
    window.__ccfExWatch = keep; return o;
  });
  ok(stop && stop.castle === 0 && /出口条件/.test(stop.html) && stop.net === 170000,
     '⑨ 出口条件の線を割った社は注文から外し、名指しする（個別 ' + (stop && stop.castle) + ' / ETF ' + (stop && stop.net) + '）');

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  await pg.evaluate(() => localStorage.removeItem('pf:monthly_total'));
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
