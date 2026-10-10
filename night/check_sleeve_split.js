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
 *   ⑪ 割り方 'cat'（区分の比率が最優先・2026-10-05）／⑬ 区分は ETF側の各本と個別株（v9.9.201・NASDAQ100/XLK/SMH/個別株）
 *   ⑫ 実データ（state.json＋全パック）で 注文書・◈ ETF の節・上の1行・区分の比率の表が同じことを言う
 *   ⑭ iDeCo（v9.9.202）: 自動引き落としの分は注文書で配らず、'cat' では NASDAQ100 の区分を先に買ったものとして数える
 *   ⑮ こどもNISA（v9.9.203）: 子どもの口座の自動の積立も注文書で配らない・NISA の月の計画より少なければ知らせる。
 *      2026-10-08「比率に数えて」から iDeCo と同じく bucket（NASDAQ100）の区分に数える（ccfCatBudget の pre は配列も受け、区分ごとに足す）・
 *      注文書の行の「✓ 保有へ」で口座 こどもNISA のロットを🏦保有へ足す・bucket が空なら比率の外（旧の扱い）
 *   ⑯ その他 ETF・投資信託（v9.9.204）: target.ami_other の buy の本（XLK）の区分に、目標0%の本と目標に無い本の保有も数える・
 *      区分の名前は「その他 ETF・投資信託」・設定を消せば v9.9.203 の姿（XLK だけの区分＋区分の外の「その他」の1行）
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
  // ★'cat'（2026-10-05 新設・区分の比率が最優先）も台帳が空だと材料（区分の今の%）が無いので 'cat_fallback' と名乗って gap へ倒す
  const want = (live === 'gap') ? ['gap'] : (live === 'name') ? ['name', 'gap_fallback'] : (live === 'cat') ? ['cat', 'cat_fallback'] : ['fixed'];
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
  // ⑧ 注文書の表示
  const html = await pg.evaluate(() => {
    const px = { CW: 85600, LRCX: 50000 };
    const pass = [{ nm: 'CW', t: 'CW', pos: 0 }, { nm: 'LRCX', t: 'LRCX', pos: 0 }, { nm: 'VRSK', t: 'VRSK', pos: 0 }];
    const tw = r => (r.t === 'VRSK' ? 0 : 4);
    const pxInfo = r => px[r.t] ? { jpy: px[r.t], px: px[r.t] / 150, ccy: 'USD', label: '$' + (px[r.t] / 150).toFixed(2) } : null;
    const NO = { tot: 2420000, rows: [{ t: 'IFREE-NDX', nm: 'iFreeNEXT', tw: 60, pos: 16, jpy: 5.8, fund: { navPer: 10000 }, alias: [] },
      { t: 'SMH', tw: 20, pos: 15.7, jpy: 95800, label: '1株 ¥95,800' }, { t: 'XLK', tw: 0, pos: 30, jpy: 30000 }] };
    return ccfWholeShareBody(pass, tw, pxInfo, NO, 170000);
  });
  // 2026-09-29 ユーザー指示「買付順位のNISAの文言は消して」→ 口座の文言が**出ない**ことを確かめる
  ok(html && !/NISA|つみたて|特定口座/.test(html.html) && /iFreeNEXT/.test(html.html),
     '⑧ 注文書に NISA・つみたて・特定口座の文言が出ない（行そのものは出る）');
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

  // ⑩ 席の順位で重み（v9.9.198・2026-10-05 ユーザー明示指示「門を10銘柄にして。…上位5社は比率を高めにして。」）
  //   ccfRankWeights は相対の重みを個別の按分枠へ正規化する。正本の重みは写さず、ここでは合成の数字で判定そのものを見る
  const rk = await pg.evaluate(() => {
    const L = n => Array.from({ length: n }, (_, i) => ({ t: 'S' + (i + 1) }));
    const U = [5, 5, 5, 5, 5, 3, 3, 3, 3, 3];
    return {
      full: ccfRankWeights(L(10), 20, Infinity, U),
      nine: ccfRankWeights(L(9), 20, Infinity, U),
      ex: ccfRankWeights(L(3).concat([{ t: 'EX', ex: true }]), 20, Infinity, [5, 3]),
      bad: ccfRankWeights(L(3), 20, Infinity, [5, 0, 3]), none: ccfRankWeights(L(3), 20, Infinity, null)
    };
  });
  const r2 = x => Math.round(x * 100) / 100, sum = o => r2(Object.values(o || {}).reduce((a, v) => a + v, 0));
  ok(rk.full && rk.full.mode === 'rank' && r2(rk.full.w.S1) === 2.5 && r2(rk.full.w.S5) === 2.5 && r2(rk.full.w.S6) === 1.5
     && r2(rk.full.w.S10) === 1.5 && sum(rk.full.w) === 20 && rk.full.tier.S6 === '席6位',
     '⑩ 席の順位で重み: 10社 [5×5,3×5]・個別20% → 上位5社 2.5% / 6〜10位 1.5%・合計20%（' + (rk.full && r2(rk.full.w.S1)) + ' / ' + (rk.full && r2(rk.full.w.S6)) + '）');
  ok(rk.nine && r2(rk.nine.w.S1) === 2.7 && r2(rk.nine.w.S9) === 1.62 && sum(rk.nine.w) === 20,
     '   席が埋まらない月（9社）は先頭の9個で正規化 → 2.70% / 1.62%・合計20%（' + (rk.nine && r2(rk.nine.w.S1)) + ' / ' + (rk.nine && r2(rk.nine.w.S9)) + '）');
  ok(rk.ex && rk.ex.unit.S3 === 3 && rk.ex.unit.EX === 3 && rk.ex.tier.EX === '門外例外' && sum(rk.ex.w) === 20,
     '   重みが足りない順位と按分に入る門外例外は最後の重み（S3 ' + (rk.ex && rk.ex.unit.S3) + ' / EX ' + (rk.ex && rk.ex.unit.EX) + '）');
  ok(rk.bad === null && rk.none === null, '   0以下の重み・重みなしは null（門が均等へ倒して名指しする）');
  // 保有ゼロどうしは「不足÷目標」が同点（1）——同点は目標の大きい社から（v9.9.198）。旧の「安い順」なら B だけが買われる
  const ws3 = await pg.evaluate(() => ccfWholeSharePlan([
    { k: 'A', tw: 2.7, pos: 0, jpy: 60000 }, { k: 'B', tw: 1.62, pos: 0, jpy: 30000 }], 70000, 2420000));
  ok(ws3 && ws3.buy.A && ws3.buy.A.sh === 1 && !ws3.buy.B && ws3.short.some(x => x.k === 'B'),
     '   保有ゼロの同点は目標の大きい社（A 2.7%）から1株・入金が尽きた B（1.62%）は来月（' + JSON.stringify(ws3 && ws3.buy) + '）');

  // ⑪ 区分の比率が最優先（割り方 'cat'・2026-10-05 ユーザー明示指示「買付順位のETF投資信託個別株の比率を最重要として」）
  //   合成の数字で判定そのものを見る（正本の比率・保有は写さない）
  const cat = await pg.evaluate(() => {
    // v9.9.201 から区分の鍵は任意（金額で買える区分は fund の印で決める）——3区分の c/e/f でも結果は v9.9.199 と同じでなければならない
    const K = { tot: 2440000, c: { t: 20, now: 38.2 }, e: { t: 40, now: 46.1 }, f: { t: 40, now: 15.8, fund: true } };
    const B = ccfCatBudget(K, 170000);
    const items = [
      { k: 'LRCX', g: 'c', tw: 2.7, pos: 0, jpy: 50000 }, { k: 'MCO', g: 'c', tw: 2.7, pos: 0, jpy: 80000 },
      { k: 'MSFT', g: 'c', tw: 2.7, pos: 26, jpy: 79000 }, { k: 'SMH', g: 'e', tw: 20, pos: 15.8, jpy: 95800 },
      { k: 'XLK', g: 'e', tw: 20, pos: 30.3, jpy: 39000 }, { k: 'IFREE', g: 'f', tw: 40, pos: 15.8, frac: true }];
    const P = ccfCatSharePlan(items, 170000, 2440000, K);
    // 区分が目標を下回る月: 個別10%・ETF35%・投資信託55%（投資信託だけ超過）
    const K2 = { tot: 2000000, c: { t: 20, now: 10 }, e: { t: 40, now: 35 }, f: { t: 40, now: 55, fund: true } };
    const B2 = ccfCatBudget(K2, 170000);
    const P2 = ccfCatSharePlan([
      { k: 'LRCX', g: 'c', tw: 10, pos: 5, jpy: 50000 }, { k: 'MCO', g: 'c', tw: 10, pos: 5, jpy: 80000 },
      { k: 'SMH', g: 'e', tw: 20, pos: 15, jpy: 95800 }, { k: 'IFREE', g: 'f', tw: 40, pos: 55, frac: true }], 170000, 2000000, K2);
    // 全区分がほぼ目標どおり（不足の合計が入金より小さい）→ 不足を埋めた残りを目標比で
    const B3 = ccfCatBudget({ tot: 2000000, c: { t: 20, now: 20 }, e: { t: 40, now: 40 }, f: { t: 40, now: 40 } }, 170000);
    return { B, P, B2, P2, B3 };
  });
  const bsum = o => ['c', 'e', 'f'].reduce((a, k) => a + ((o[k] && o[k].b) || 0), 0);
  ok(cat.B.c.b === 0 && cat.B.e.b === 0 && cat.B.f.b === 170000 && bsum(cat.B) === 170000,
     "⑪ 割り方 'cat': 個別38.2%・ETF46.1%（どちらも目標超過）・投資信託15.8% → 取り分 個別¥0／ETF¥0／投資信託¥170,000（" + [cat.B.c.b, cat.B.e.b, cat.B.f.b].join(' / ') + '）');
  ok(!Object.keys(cat.P.buy).length && cat.P.frac.IFREE === 170000 && cat.P.rest === 0
     && ['LRCX', 'MCO', 'SMH'].every(k => cat.P.catfull.some(x => x.k === k)),
     '   保有ゼロの LRCX・MCO や SMH 単体の不足があっても、区分が目標超過なら買わない（catfull）・全額 iFreeNEXT（' + JSON.stringify(cat.P.buy) + ' / frac ' + cat.P.frac.IFREE + '）');
  ok(cat.B2.c.b === 98956 && cat.B2.e.b === 71044 && cat.B2.f.b === 0 && bsum(cat.B2) === 170000,
     '   区分の不足で割る: 個別の不足¥234,000・ETF¥168,000・投資信託0 → ¥98,956／¥71,044／¥0（端数1円は不足の大きい区分へ）（' + [cat.B2.c.b, cat.B2.e.b, cat.B2.f.b].join(' / ') + '）');
  ok(cat.P2.buy.LRCX && cat.P2.buy.LRCX.sh === 1 && !cat.P2.buy.MCO && cat.P2.buy.SMH && cat.P2.buy.SMH.sh === 1
     && cat.P2.frac.IFREE === 24200 && cat.P2.rest === 0 && cat.P2.cat.c.spent === 50000 && cat.P2.cat.e.spent === 95800,
     '   区分の中は1株単位: 個別は LRCX 1株（MCO は残りでは買えず来月）・ETF は SMH 1株（不足は投資信託の取り分から）・端数¥24,200 は投資信託（'
     + JSON.stringify(cat.P2.buy) + ' / frac ' + cat.P2.frac.IFREE + ' / rest ' + cat.P2.rest + '）');
  ok(cat.B3.c.b === 34000 && cat.B3.e.b === 68000 && cat.B3.f.b === 68000,
     '   全区分が目標どおりなら目標比で割る（¥34,000／¥68,000／¥68,000）（' + [cat.B3.c.b, cat.B3.e.b, cat.B3.f.b].join(' / ') + '）');
  const catHtml = await pg.evaluate(() => {
    const px = { LRCX: 50000, MCO: 80000 };
    const pass = [{ nm: 'LRCX', t: 'LRCX', pos: 0 }, { nm: 'MCO', t: 'MCO', pos: 0 }];
    const pxInfo = r => px[r.t] ? { jpy: px[r.t], px: px[r.t] / 150, ccy: 'USD', label: '$' + (px[r.t] / 150).toFixed(2) } : null;
    const NO = { tot: 2440000, rows: [{ t: 'IFREE-NDX', nm: 'iFreeNEXT', tw: 40, pos: 15.8, jpy: 5.8, fund: { navPer: 10000 }, alias: ['QQQM'], alPos: 15.8 },
      { t: 'SMH', tw: 20, pos: 15.8, jpy: 95800, label: '1株 ¥95,800' }, { t: 'XLK', tw: 20, pos: 30.3, jpy: 39000, label: '1株 ¥39,000' },
      { t: 'QQQM', tw: 0, pos: 15.8, jpy: 46000, sameAs: 'IFREE-NDX' }, { t: 'GRID', tw: 0, pos: 1.2, jpy: 30000 }] };
    const K = { tot: 2440000, 'n:IFREE-NDX': { t: 40, now: 15.8, nm: 'NASDAQ100', fnm: 'iFreeNEXT NASDAQ100', fund: true, alias: ['QQQM'] },
      'n:XLK': { t: 20, now: 30.3, nm: 'XLK' }, 'n:SMH': { t: 20, now: 15.8, nm: 'SMH' }, c: { t: 20, now: 36.9, nm: '個別株' },
      _zero: { now: 1.2, nm: ['GRID'] } };
    return ccfWholeShareBody(pass, () => 2.7, pxInfo, NO, 170000, K);
  });
  const ct = catHtml.html.replace(/<[^>]+>/g, '');
  const at = s => ct.indexOf(s);
  ok(/区分の比率（いちばん先に守る）/.test(ct) && at('📈 NASDAQ100（iFreeNEXT NASDAQ100・同じ指数の QQQM を含む）') >= 0
     && at('📈 NASDAQ100') < at('◈ XLK') && at('◈ XLK') < at('◈ SMH') && at('◈ SMH') < at('🏰 個別株')
     && /その他（目標0%で持ち続けている本：GRID）/.test(ct) && /今1\.2%・売らない・新規なし/.test(ct),
     '   注文書の先頭に区分の比率（目標・今・買った後・今月の円）を NASDAQ100 → XLK → SMH → 個別株 の順に出し、目標0%で持っている本は「その他」の1行');
  ok(/区分が目標を超えているので今月なし/.test(ct) && catHtml.fund === 170000 && catHtml.castle === 0 && catHtml.etf === 0
     && (catHtml.castle + catHtml.net + catHtml.rest) === 170000,
     '   区分が目標超過で買わない本は理由を名指し・個別株＋ETF＋投資信託＋残り＝入金額（' + [catHtml.castle, catHtml.etf, catHtml.fund, catHtml.rest].join(' / ') + '）');
  // 画面: 正本を 'cat' にした門で「区分の比率が最優先」と出る（台帳が空なので注文書は無いが、割り方の1行は出る）
  await load(withMode('cat'));
  sp = await pg.evaluate(() => { window.__ccfCat = { tot: 2440000, 'n:IFREE-NDX': { t: 40, now: 15.8, nm: 'NASDAQ100', fund: true },
      'n:XLK': { t: 20, now: 30.3, nm: 'XLK' }, 'n:SMH': { t: 20, now: 15.8, nm: 'SMH' }, c: { t: 20, now: 38.2, nm: '個別株' } };
    window.__ccfNameGap = { c: 9, n: 30 }; localStorage.setItem('pf:monthly_total', '170000'); return ccfSleeveSplit(); });
  ok(sp && sp.mode === 'cat' && sp.castle === 0 && sp.net === 170000 && sp.nCastle === Math.round(170000 * 9 / 39),
     "   ccfSleeveSplit も mode='cat' で同じ取り分（個別 ¥" + (sp && sp.castle) + '）・採らなかったほう（銘柄ごとの不足から 個別 ¥' + (sp && sp.nCastle) + '）を持つ');
  sp = await pg.evaluate(() => { window.__ccfCat = null; return ccfSleeveSplit(); });
  ok(sp && sp.mode === 'cat_fallback', "   材料が無ければ 'cat_fallback' と名乗って gap へ倒す（黙って別の割り方にしない）");

  // ⑬ 4区分（v9.9.201・2026-10-06 ユーザー明示指示「NASDAQ100 40% / XLK20% / SMH20% / 個別株20%」）
  //   ETF側の目標>0 の本はそれぞれ1区分——XLK が目標を超えていても、目標を下回る SMH には SMH の不足のぶん配る
  //   （旧 v9.9.199 は XLK と SMH を「ETF」の1区分にまとめていたので、XLK の超過が SMH の不足を打ち消して ¥0 だった）
  const q4 = await pg.evaluate(() => {
    const K = { tot: 2490000, 'n:IFREE-NDX': { t: 40, now: 15.6, nm: 'NASDAQ100', fnm: 'iFreeNEXT NASDAQ100', fund: true, alias: ['QQQM'] },
      'n:XLK': { t: 20, now: 30.4, nm: 'XLK' }, 'n:SMH': { t: 20, now: 16.0, nm: 'SMH' }, c: { t: 20, now: 38.0, nm: '個別株' }, _zero: { now: 0, nm: [] } };
    const B = ccfCatBudget(K, 170000);
    const B3 = ccfCatBudget({ tot: 2490000, c: { t: 20, now: 38.0 }, e: { t: 40, now: 46.4 }, f: { t: 40, now: 15.6, fund: true } }, 170000);
    const items = [
      { k: 'LRCX', g: 'c', tw: 2.9, pos: 0, jpy: 52000 },
      { k: 'SMH', g: 'n:SMH', tw: 20, pos: 16.0, jpy: 99500 }, { k: 'XLK', g: 'n:XLK', tw: 20, pos: 30.4, jpy: 40000 },
      { k: 'IFREE', g: 'n:IFREE-NDX', tw: 40, pos: 15.6, frac: true }, { k: 'QQQM', g: 'n:IFREE-NDX', tw: 0, pos: 15.6, jpy: 47000 },
      { k: 'GRID', g: 'n:GRID', tw: 0, pos: 0, jpy: 30000 }, { k: 'ODD', g: 'n:ODD', tw: 5, pos: 0, jpy: 10000 }];
    const P = ccfCatSharePlan(items, 170000, 2490000, K);
    // SMH の不足が育った月（取り分が1株の半分以上）→ 足りない分を投資信託の取り分から借りて1株
    const K2 = { tot: 2000000, 'n:IFREE-NDX': { t: 40, now: 30, nm: 'NASDAQ100', fund: true }, 'n:XLK': { t: 20, now: 28, nm: 'XLK' },
      'n:SMH': { t: 20, now: 12, nm: 'SMH' }, c: { t: 20, now: 30, nm: '個別株' } };
    const B2 = ccfCatBudget(K2, 170000);
    const P2 = ccfCatSharePlan([{ k: 'LRCX', g: 'c', tw: 2.9, pos: 0, jpy: 52000 }, { k: 'SMH', g: 'n:SMH', tw: 20, pos: 12, jpy: 99500 },
      { k: 'XLK', g: 'n:XLK', tw: 20, pos: 28, jpy: 40000 }, { k: 'IFREE', g: 'n:IFREE-NDX', tw: 40, pos: 30, frac: true }], 170000, 2000000, K2);
    // 理由の文（注文書の HTML）
    const NO = { tot: 2490000, rows: [{ t: 'IFREE-NDX', nm: 'iFreeNEXT', tw: 40, pos: 15.6, jpy: 5.75, fund: { navPer: 10000 }, alias: ['QQQM'], alPos: 15.6 },
      { t: 'XLK', tw: 20, pos: 30.4, jpy: 40000, label: '1株 ¥40,000' }, { t: 'SMH', tw: 20, pos: 16.0, jpy: 99500, label: '1株 ¥99,500' },
      { t: 'ODD', tw: 5, pos: 0, jpy: 10000, label: '1株 ¥10,000' }] };
    const H = ccfWholeShareBody([], () => 0, () => null, NO, 170000, K);
    return { B, B3, P, B2, P2, ht: H.html.replace(/<[^>]+>/g, ''), H: { fund: H.fund, etf: H.etf, castle: H.castle, rest: H.rest } };
  });
  const k4 = ['n:IFREE-NDX', 'n:XLK', 'n:SMH', 'c'], b4 = o => k4.map(k => (o[k] && o[k].b) || 0);
  ok(q4.B['n:XLK'].b === 0 && q4.B.c.b === 0 && q4.B['n:SMH'].b === 28068 && q4.B['n:IFREE-NDX'].b === 141932
     && b4(q4.B).reduce((a, v) => a + v, 0) === 170000 && q4.B3.e.b === 0,
     '⑬ 4区分: XLK 30.4%・個別株 38.0%（目標超過）は¥0、SMH（16.0%）と NASDAQ100（15.6%）へ不足の比で ¥28,068 ／ ¥141,932（旧の ETF 1区分なら SMH の取り分は ¥' + q4.B3.e.b + '）（' + b4(q4.B).join(' / ') + '）');
  const sh = q4.P.short.find(x => x.k === 'SMH');
  ok(!q4.P.buy.SMH && sh && sh.g === 'n:SMH' && sh.rem === 28068 && q4.P.frac.IFREE === 170000 && q4.P.rest === 0
     && q4.P.catfull.some(x => x.k === 'LRCX' && x.g === 'c') && !q4.P.buy.XLK && !q4.P.buy.QQQM
     && q4.P.nocat.some(x => x.k === 'ODD') && !q4.P.nocat.some(x => x.k === 'GRID'),
     '   SMH の取り分が1株の半分に届かない月は買わず、取り分は NASDAQ100 へ（全額 ¥' + q4.P.frac.IFREE + '）・個別株は区分ごと目標超過（catfull）・区分の無い本（目標>0）は nocat で名指し・目標0%の本は黙って外す');
  ok(q4.B2['n:SMH'].b === 71385 && q4.B2['n:IFREE-NDX'].b === 98615 && q4.P2.buy.SMH && q4.P2.buy.SMH.sh === 1
     && q4.P2.frac.IFREE === 70500 && q4.P2.rest === 0 && q4.P2.cat['n:SMH'].spent === 99500 && q4.P2.cat['n:IFREE-NDX'].spent === 70500,
     '   SMH の取り分（¥71,385）が1株の半分以上の月は、足りない ¥28,115 を NASDAQ100 の取り分から借りて1株・残り ¥70,500 は NASDAQ100（'
     + JSON.stringify(q4.P2.buy) + ' / frac ' + q4.P2.frac.IFREE + ' / rest ' + q4.P2.rest + '）');
  ok(/今月のSMHの取り分 ¥28,068 が1株 ¥99,500 の半分に届かない/.test(q4.ht) && /XLK：目標に届いているので今月なし|XLK・[^：]*：目標に届いているので今月なし|・XLK[^：]*：目標に届いているので今月なし/.test(q4.ht)
     && /⚠区分が読めない/.test(q4.ht) && q4.H.fund === 170000 && q4.H.etf === 0 && (q4.H.castle + q4.H.etf + q4.H.fund + q4.H.rest) === 170000,
     '   注文書の理由: SMH は「取り分 ¥28,068 が1株の半分に届かない」・XLK は「目標に届いている」・区分の無い本は ⚠ で名指し（投資信託 ¥' + q4.H.fund + '）');

  // ⑫ 実データ（state.json の保有＋全パック）で、注文書と ◈ ETF の節が同じことを言う（2026-10-05 実測で食い違っていた:
  //    注文書は QQQM を買わないのに、裏で走る旧の組み方（mkNb）が置いた「つみたて枠を超えた分」を節が読んで「QQQM 今月 買う」と出た）
  const ST = JSON.parse(fs.readFileSync(path.join(ROOT, 'state.json'), 'utf8'));
  for (const m of ['cat', 'name']) {
    OVER = withMode(m);
    await pg.goto('http://localhost:' + PORT + '/index.html'); await pg.waitForTimeout(600);
    await pg.evaluate(st => { localStorage.clear(); for (const k in st.data) localStorage.setItem(k, st.data[k]);
      localStorage.setItem('ccf:stateSavedAt', st.savedAt); }, ST);
    await pg.reload(); await pg.waitForTimeout(1500);
    await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1800);
    await pg.evaluate(() => { localStorage.setItem('pf:monthly_total', '170000'); showPage(5); }); await pg.waitForTimeout(3200);
    const r12 = await pg.evaluate(() => {
      const OB = window.__ccfOrderNet || null;
      const sec = [...document.querySelectorAll('#pg5 .led.planrow')].filter(e => e.querySelector('.bctl'))
        .map(e => ({ t: e.querySelector('.bctl').dataset.t, buy: /今月 買う/.test(e.innerText), none: /今月なし/.test(e.innerText) }))
        .filter(x => x.buy || x.none);
      const lines = [...document.querySelectorAll('#pg5 div')].filter(d => /区分の比率が最優先・1株単位/.test(d.innerText) && d.innerText.length < 400).map(d => d.innerText);
      const rows = [...document.querySelectorAll('#pg5 .catrow')].filter(e => e.dataset.cat !== 'zero')
        .map(e => ({ g: e.dataset.cat, yen: +((e.innerText.match(/今月 ¥([\d,]+)/) || [0, '0'])[1].replace(/,/g, '')) }));
      const tot = [...document.querySelectorAll('#pg5 div')].map(d => d.innerText).find(x => /^合計 約¥/.test(x.trim()) && x.length < 200) || '';
      const CI = window.__ccfCat || {}, labs = {};
      ccfCatKeys(CI).forEach(g => { labs[g] = ccfCatLabel(CI, g, { plain: true }); });
      // 注文書の「金額で買う」の行（投資信託・暗号資産）の文——v9.9.205 で暗号資産の行が増えた
      const fr = [...document.querySelectorAll('#pg5 div.planrow')].map(e => e.innerText).filter(x => /金額で買う/.test(x));
      return { OB, sec, line: lines.length ? lines[lines.length - 1] : '', rows, tot, labs, fr };
    });
    if (m === 'cat') {
      const ord = r12.rows.map(x => x.g).join(','), ys = r12.rows.map(x => x.yen);
      // v9.9.204〜205: 区分の並びと名前は正本から（v9.9.204 でXLKの区分の名前が「その他 ETF・投資信託」、v9.9.205 で暗号資産の2区分が増えた）
      const TG = base.target, AL = new Set(Object.values(TG.ami_same_index || {}).flat().map(x => String(x).toUpperCase()));
      const want = (TG.ami_names || []).map(x => String(x).toUpperCase()).filter(k => !AL.has(k) && (+(TG.ami_weights || {})[k] || 0) > 0).map(k => 'n:' + k).concat(['c']);
      const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), names = r12.rows.map(x => r12.labs[x.g] || x.g);
      const lineY = names.map(nm => { const mm = r12.line.match(new RegExp('(?:^|／ )' + esc(nm) + ' ¥([\\d,]+)')); return mm ? +mm[1].replace(/,/g, '') : null; });
      const rest = +((r12.tot.match(/残り¥([\d,]+)/) || [0, '0'])[1].replace(/,/g, ''));
      ok(ord === want.join(',') && new RegExp('^' + names.map(nm => esc(nm) + ' ¥[\\d,]+').join(' ／ ')).test(r12.line.trim())
         && JSON.stringify(lineY) === JSON.stringify(ys) && ys.reduce((a, v) => a + v, 0) + rest >= 169900 && ys.reduce((a, v) => a + v, 0) <= 170000,
         "⑫ 割り方 'cat'（実データ）: 区分は " + names.join(' → ') + ' の' + names.length + 'つ（正本の並び）・上の1行と区分の比率の表が同じ円（' + ys.join(' / ') + (rest ? '・残り' + rest : '') + '）');
    }
    // ★暗号資産（v9.9.205）: 金額で買う行は「取引所で金額で買う（NISAの外）」——「残りの円は全部ここへ」は投資信託の行だけ
    {
      const LB = base.target.ami_labels || {}, OB0 = r12.OB || {};
      const cxs = Object.keys(OB0).filter(t => /-USD$/.test(t) && (+OB0[t] || 0) > 0);
      const cxBad = cxs.filter(t => { const tx = r12.fr.find(x => x.includes(LB[t] || t)); return !tx || !/取引所で金額で買う/.test(tx) || /残りの円は全部ここへ/.test(tx); });
      const fundRest = r12.fr.filter(x => /残りの円は全部ここへ/.test(x));
      const fundY = Object.keys(OB0).filter(t => (base.target.ami_funds || {})[t] && (+OB0[t] || 0) > 0);
      ok(!cxBad.length && fundRest.length >= (fundY.length ? 1 : 0) && fundRest.every(x => !cxs.some(t => x.includes(LB[t] || t))),
         `⑫ 割り方 '${m}'（実データ）: 暗号資産の行（${cxs.map(t => (LB[t] || t) + ' ¥' + OB0[t]).join('・') || 'なし'}）は「取引所で金額で買う」・「残りの円は全部ここへ」は投資信託の行だけ（${fundRest.length}行）`
         + (cxBad.length ? ' ／ 食い違い ' + cxBad.join('・') : ''));
    }
    const bad = r12.OB ? r12.sec.filter(x => x.buy !== ((+r12.OB[x.t] || 0) > 0)) : [{ t: '注文書の円が無い' }];
    ok(r12.sec.length >= 3 && !bad.length,
       `⑫ 割り方 '${m}'（実データ・入金17万）: ◈ ETF の節の「今月 買う」が注文書の円と一致（` +
       r12.sec.map(x => x.t + (x.buy ? '◯' : '—') + '¥' + (r12.OB ? (+r12.OB[x.t] || 0) : '?')).join(' ') + (bad.length ? ' ／ 食い違い ' + bad.map(x => x.t).join('・') : '') + '）');
  }

  // ⑭ iDeCo（v9.9.202・2026-10-06 ユーザー明示指示「それで入れて」）: 自動引き落としの分は注文書で配らず、
  //    割り方 'cat' では NASDAQ100 の区分を先に買ったものとして数える（ccfCatBudget の pre）。期待値は式から作る（数字を写さない）
  const q14 = await pg.evaluate(() => {
    const TOT = 2490000, P = 40000, T = 140000;
    const K = { tot: TOT, 'n:IFREE-NDX': { t: 40, now: 15.6, nm: 'NASDAQ100', fund: true }, 'n:XLK': { t: 20, now: 30.4, nm: 'XLK' },
      'n:SMH': { t: 20, now: 16.0, nm: 'SMH' }, c: { t: 20, now: 38.0, nm: '個別株' } };
    const Bp = ccfCatBudget(Object.assign({}, K, { pre: { g: 'n:IFREE-NDX', jpy: P } }), T);
    const B0 = ccfCatBudget(K, T), Ball = ccfCatBudget(K, T + P);      // iDeCo なしで 入金だけ／入金＋iDeCo の全体
    const Bx = ccfCatBudget(Object.assign({}, K, { pre: { g: 'n:NOPE', jpy: P } }), T);
    // iDeCo だけで NASDAQ100 の取り分を超える月（NASDAQ100 が目標超過）: NASDAQ100 は iDeCo だけ・入金は残りの区分で
    const KB = { tot: 2000000, 'n:IFREE-NDX': { t: 40, now: 45, fund: true }, 'n:XLK': { t: 20, now: 25 }, 'n:SMH': { t: 20, now: 10 }, c: { t: 20, now: 20 } };
    const Bb = ccfCatBudget(Object.assign({}, KB, { pre: { g: 'n:IFREE-NDX', jpy: P } }), T);
    const items = [{ k: 'LRCX', g: 'c', tw: 2.9, pos: 0, jpy: 52000 }, { k: 'SMH', g: 'n:SMH', tw: 20, pos: 16.0, jpy: 99500 },
      { k: 'XLK', g: 'n:XLK', tw: 20, pos: 30.4, jpy: 40000 }, { k: 'IFREE', g: 'n:IFREE-NDX', tw: 40, pos: 15.6, frac: true }];
    const Pp = ccfCatSharePlan(items, T, TOT, Object.assign({}, K, { pre: { g: 'n:IFREE-NDX', jpy: P } }));
    // 設定の読み方と、注文書が配る額
    const t0 = { ami_funds: { 'RPLUS-NDX': { name: 'x' } }, ideco: { members: [{ who: 'A', jpy: 20000 }, { who: 'B', jpy: 20000 }, { who: 'C', jpy: 0 }], fund: 'RPLUS-NDX', bucket: 'IFREE-NDX', start: '2000-01' } };
    const cPast = ccfIdecoCfg(t0), cFut = ccfIdecoCfg(Object.assign({}, t0, { ideco: Object.assign({}, t0.ideco, { start: '2999-12' }) })),
          cBad = ccfIdecoCfg(Object.assign({}, t0, { ideco: Object.assign({}, t0.ideco, { start: '2027/01' }) }));
    const keep = window.__ccfIdeco; localStorage.setItem('pf:monthly_total', '180000');
    window.__ccfIdeco = cPast; const oa1 = ccfOrderAmt(), ia1 = ccfIdecoAmt();
    window.__ccfIdeco = cFut; const oa2 = ccfOrderAmt(), ia2 = ccfIdecoAmt();
    window.__ccfIdeco = keep;
    return { TOT, P, T, Bp, B0, Ball, Bx, Bb, Pp, cPast, cFut, cBad, oa1, ia1, oa2, ia2 };
  });
  const keys14 = ['n:IFREE-NDX', 'n:XLK', 'n:SMH', 'c'];
  const baseP = q14.TOT + q14.P + q14.T;
  const sumB = o => keys14.reduce((a, k) => a + o[k].b, 0);
  // 「入金＋iDeCo」の全体を区分の不足で割った取り分と同じ（NASDAQ100 だけ iDeCo の分を引く）＝iDeCo があっても無くても区分ごとの新しいお金は同じ
  const sameAsAll = keys14.every(k => q14.Bp[k].b === q14.Ball[k].b - (k === 'n:IFREE-NDX' ? q14.P : 0));
  ok(sameAsAll && sumB(q14.Bp) === q14.T && q14.Bp['n:IFREE-NDX'].pre === q14.P,
     '⑭ iDeCo: 「入金＋iDeCo」の全体を区分の不足で割り、NASDAQ100 の取り分から iDeCo を引く（SMH ¥' + q14.Bp['n:SMH'].b + '＝iDeCo なしで18万を割ったとき ¥' + q14.Ball['n:SMH'].b
     + '・NASDAQ100 ¥' + q14.Bp['n:IFREE-NDX'].b + '＋iDeCo ¥' + q14.P.toLocaleString() + '）');
  const bb = q14.Bb, rest = ['n:XLK', 'n:SMH', 'c'];
  ok(bb['n:IFREE-NDX'].b === 0 && rest.reduce((a, k) => a + bb[k].b, 0) === q14.T && bb['n:SMH'].b > 0 && bb['n:XLK'].b === 0,
     '   iDeCo だけで NASDAQ100 の取り分を超える月（目標超過）: NASDAQ100 は iDeCo だけ・入金 ¥' + q14.T.toLocaleString() + ' は残りの区分へ（SMH ¥' + bb['n:SMH'].b + '・個別株 ¥' + bb.c.b + '）');
  ok(keys14.every(k => q14.Bx[k].b === q14.B0[k].b && q14.Bx[k].pre === 0), '   iDeCo の区分が目標に無ければ数えない（取り分は iDeCo なしで入金だけを割ったのと同じ）');
  const ndx = q14.Pp.cat['n:IFREE-NDX'], expAfter = (ndx.now * q14.TOT / 100 + q14.P + ndx.spent) / baseP * 100;
  ok(q14.Pp.pre === q14.P && ndx.pre === q14.P && Math.abs(ndx.after - expAfter) < 1e-9 && (q14.Pp.frac.IFREE + (q14.Pp.buy.SMH ? q14.Pp.buy.SMH.cost : 0) + q14.Pp.rest) === q14.T,
     '   注文書の計画は iDeCo を配らない（配るのは ¥' + q14.T.toLocaleString() + '）・NASDAQ100 の「買った後」は iDeCo を含む（' + ndx.after.toFixed(2) + '%）');
  ok(q14.cPast && q14.cPast.active && q14.cPast.jpy === 40000 && q14.cPast.members.length === 2 && q14.cFut && !q14.cFut.active && q14.cBad && !q14.cBad.active,
     '   設定: 開始月を過ぎたら有効（掛金0の名義は外す・合計 ¥' + (q14.cPast && q14.cPast.jpy) + '）・開始月の前／形の違う開始月は無効');
  ok(q14.oa1 === 140000 && q14.ia1 === 40000 && q14.oa2 === 180000 && q14.ia2 === 0,
     '   注文書が配る額: 有効なら 18万−4万＝¥' + q14.oa1.toLocaleString() + '・開始月の前は ¥' + q14.oa2.toLocaleString());
  // 実データ（state.json＋全パック）: 開始月を過ぎた設定なら注文書は入金額−iDeCo を配り iDeCo の行を出す／開始月の前なら全額
  const withIdeco = (st) => { const o = withMode('cat'); if (o.target.ideco) o.target.ideco.start = st; return o; };
  if (!base.target || !base.target.ideco) ok(true, '   ⑭ 実データ: portfolio.json に target.ideco が無い（飛ばす）');
  else for (const [st, act] of [['2000-01', true], ['2999-12', false]]) {
    OVER = withIdeco(st);
    await pg.goto('http://localhost:' + PORT + '/index.html'); await pg.waitForTimeout(600);
    await pg.evaluate(stt => { localStorage.clear(); for (const k in stt.data) localStorage.setItem(k, stt.data[k]);
      localStorage.setItem('ccf:stateSavedAt', stt.savedAt); }, ST);
    await pg.reload(); await pg.waitForTimeout(1500);
    await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1800);
    await pg.evaluate(() => { localStorage.setItem('pf:monthly_total', '180000'); showPage(5); }); await pg.waitForTimeout(3200);
    const r14 = await pg.evaluate(() => {
      const box = [...document.querySelectorAll('#pg5 div')].find(d => /📋 今月の注文書/.test(d.innerText) && /合計 約/.test(d.innerText) && d.innerText.length < 8000);
      const t = box ? box.innerText : '', m = t.match(/合計 約¥([\d,]+)/), rr = t.match(/残り¥([\d,]+)/);
      return { row: /🏦 iDeCo（自動引き落とし・注文書では買わない）/.test(t), pre: !!(window.__ccfCat && window.__ccfCat.pre),
        tot: m ? +m[1].replace(/,/g, '') : null, rest: rr ? +rr[1].replace(/,/g, '') : 0, ia: ccfIdecoAmt() };
    });
    const IA = act ? (base.target.ideco.members || []).reduce((a, x) => a + (+x.jpy || 0), 0) : 0;
    ok(r14.row === act && r14.pre === act && r14.ia === IA && r14.tot != null && r14.tot + r14.rest <= 180000 - IA && r14.tot + r14.rest >= 180000 - IA - 300,
       '⑭ 実データ・開始月 ' + st + (act ? '（有効）' : '（前）') + ': iDeCo の行 ' + (r14.row ? 'あり' : 'なし') + '・注文書の合計 ¥' + (r14.tot || 0).toLocaleString()
       + (r14.rest ? '＋残り ¥' + r14.rest.toLocaleString() : '') + '（入金18万−iDeCo ¥' + IA.toLocaleString() + '）');
  }

  // ⑮ こどもNISA（v9.9.203・2026-10-08 ユーザー明示指示「来年1月から ideco月3万 子供NISA月3万 NISA月14万で積立 これでやって」）:
  //    子どもの口座の自動の積立は注文書で配らない（入金額 − iDeCo − こどもNISA）。
  //    同日「比率に数えて」: bucket があれば iDeCo と同じく区分の比率に数える（pre は区分ごとに iDeCo と合計）。bucket が空なら比率の外。
  //    NISA の月の計画（target.nisa.monthly_jpy）より注文書で配る額が少ない月は知らせる。期待値は正本の設定から作る（数字を写さない）
  const q15 = await pg.evaluate(() => {
    const t0 = { ami_funds: {}, ideco: { members: [{ who: 'A', jpy: 15000 }, { who: 'B', jpy: 15000 }], fund: 'X', bucket: 'IFREE-NDX', start: '2000-01' },
      kodomo_nisa: { members: [{ who: '子ども', jpy: 30000 }, { who: 'Z', jpy: 0 }], fund: '', bucket: 'ifree-ndx', start: '2000-01' } };
    // 自動の積立が2つ（ccfCatBudget の pre は配列も受ける）: 同じ区分なら合計と同じ・別の区分でも合計は入金・区分の取り分を超えたら その区分は自動の積立だけ
    const TOT = 2490000, T = 140000, A = 30000, B2 = 30000;
    const K = { tot: TOT, 'n:IFREE-NDX': { t: 50, now: 15.6, fund: true }, 'n:XLK': { t: 15, now: 30.4 }, 'n:SMH': { t: 20, now: 5.0 }, c: { t: 15, now: 38.0 } };
    const one = ccfCatBudget(Object.assign({}, K, { pre: { g: 'n:IFREE-NDX', jpy: A + B2 } }), T);
    const two = ccfCatBudget(Object.assign({}, K, { pre: [{ g: 'n:IFREE-NDX', jpy: A, parts: [{ lbl: 'iDeCo', jpy: A }] }, { g: 'n:IFREE-NDX', jpy: B2, parts: [{ lbl: 'こどもNISA', jpy: B2 }] }] }), T);
    const twoP = ccfCatSharePlan([{ k: 'IFREE', g: 'n:IFREE-NDX', tw: 50, pos: 15.6, frac: true }], T, TOT,
      Object.assign({}, K, { pre: { g: 'n:IFREE-NDX', jpy: A + B2, parts: [{ lbl: 'iDeCo', jpy: A }, { lbl: 'こどもNISA', jpy: B2 }] } }));
    const diff = ccfCatBudget(Object.assign({}, K, { pre: [{ g: 'n:IFREE-NDX', jpy: A }, { g: 'n:SMH', jpy: B2 }] }), T);
    const allNP = ccfCatBudget(K, T + A + B2);                       // 自動の積立なしで「入金＋自動の積立」の全体を割ったとき
    const KB = { tot: 2000000, 'n:IFREE-NDX': { t: 50, now: 55, fund: true }, 'n:XLK': { t: 15, now: 15 }, 'n:SMH': { t: 20, now: 10 }, c: { t: 15, now: 20 } };
    const over = ccfCatBudget(Object.assign({}, KB, { pre: [{ g: 'n:IFREE-NDX', jpy: A }, { g: 'n:SMH', jpy: B2 }] }), T);
    const miss = ccfCatBudget(Object.assign({}, K, { pre: [{ g: 'n:IFREE-NDX', jpy: A }, { g: 'n:NOPE', jpy: B2 }] }), T);
    const solo = ccfCatBudget(Object.assign({}, K, { pre: { g: 'n:IFREE-NDX', jpy: A } }), T);
    const budget = { one, two, twoP: twoP.cat['n:IFREE-NDX'], diff, allNP, over, miss, solo, T, A, B2,
      partsOld: ccfPreParts({ pre: A }), partsNone: ccfPreParts({ pre: 0 }) };
    const kPast = ccfKodomoCfg(t0), kFut = ccfKodomoCfg(Object.assign({}, t0, { kodomo_nisa: Object.assign({}, t0.kodomo_nisa, { start: '2999-12' }) })),
          kBad = ccfKodomoCfg(Object.assign({}, t0, { kodomo_nisa: Object.assign({}, t0.kodomo_nisa, { start: '2027/01' }) })), kNone = ccfKodomoCfg({});
    const keepI = window.__ccfIdeco, keepK = window.__ccfKodomo, keepN = window.__ccfNisa;
    localStorage.setItem('pf:monthly_total', '200000');
    window.__ccfIdeco = ccfIdecoCfg(t0); window.__ccfKodomo = kPast;
    const both = { oa: ccfOrderAmt(), auto: ccfAutoAmt(), ka: ccfKodomoAmt(), ia: ccfIdecoAmt() };
    window.__ccfKodomo = kFut; const kfut = { oa: ccfOrderAmt(), ka: ccfKodomoAmt() };
    window.__ccfNisa = { monthly_jpy: 140000, monthly_from: '2000-01' }; const npOn = ccfNisaPlan();
    window.__ccfNisa = { monthly_jpy: 140000, monthly_from: '2999-12' }; const npOff = ccfNisaPlan();
    window.__ccfNisa = { holders: ['A'] }; const npNone = ccfNisaPlan();
    window.__ccfIdeco = keepI; window.__ccfKodomo = keepK; window.__ccfNisa = keepN;
    return { kPast, kFut, kBad, kNone, both, kfut, npOn, npOff, npNone, budget };
  });
  ok(q15.kPast && q15.kPast.active && q15.kPast.jpy === 30000 && q15.kPast.members.length === 1 && q15.kFut && !q15.kFut.active && q15.kBad && !q15.kBad.active && q15.kNone === null,
     '⑮ こどもNISA の設定: 開始月を過ぎたら有効（0円の名義は外す・合計 ¥' + (q15.kPast && q15.kPast.jpy) + '）・開始月の前／形の違う開始月は無効・設定が無ければ null');
  ok(q15.both.oa === 140000 && q15.both.auto === 60000 && q15.both.ka === 30000 && q15.both.ia === 30000 && q15.kfut.oa === 170000 && q15.kfut.ka === 0,
     '   注文書が配る額: 20万 − iDeCo 3万 − こどもNISA 3万 ＝ ¥' + q15.both.oa.toLocaleString() + '・こどもNISA が開始月の前なら ¥' + q15.kfut.oa.toLocaleString());
  ok(q15.npOn && q15.npOn.active && q15.npOn.jpy === 140000 && q15.npOff && !q15.npOff.active && q15.npNone === null,
     '   NISA の月の計画: monthly_from を過ぎたら有効・前は無効・monthly_jpy が無ければ null');
  {
    const B = q15.budget, ks = ['n:IFREE-NDX', 'n:XLK', 'n:SMH', 'c'], sum = o => ks.reduce((a, k) => a + o[k].b, 0);
    ok(q15.kPast.bucket === 'IFREE-NDX', '   設定: bucket を読む（大文字にそろえる・' + q15.kPast.bucket + '）');
    ok(ks.every(k => B.one[k].b === B.two[k].b && B.one[k].need === B.two[k].need) && B.two['n:IFREE-NDX'].pre === B.A + B.B2
       && B.two['n:IFREE-NDX'].preParts.map(p => p.lbl).join('+') === 'iDeCo+こどもNISA' && B.one['n:IFREE-NDX'].preParts.map(p => p.lbl).join('+') === 'iDeCo',
       '   pre が2つ（同じ NASDAQ100）: 取り分は合計1つ（¥' + (B.A + B.B2).toLocaleString() + '）と同じ（NASDAQ100 ¥' + B.two['n:IFREE-NDX'].b.toLocaleString() + '）・内訳 '
       + B.two['n:IFREE-NDX'].preParts.map(p => p.lbl + ' ¥' + p.jpy).join('＋') + '・内訳の無い形は iDeCo とみなす');
    ok(B.twoP.pre === B.A + B.B2 && B.twoP.preParts.length === 2, '   注文書の計画（ccfCatSharePlan）も内訳を持つ（区分の比率の表が「＋iDeCo ＋こどもNISA」と出す材料）');
    const PREd = { 'n:IFREE-NDX': B.A, 'n:SMH': B.B2 };
    ok(sum(B.diff) === B.T && ks.every(k => B.diff[k].b === B.allNP[k].b - (PREd[k] || 0)) && B.diff['n:SMH'].pre === B.B2,
       '   pre が別の区分（NASDAQ100 と SMH）: 「入金＋自動の積立」の全体を割り、それぞれの区分から引く（合計 ¥' + sum(B.diff).toLocaleString() + '＝入金・SMH ¥' + B.diff['n:SMH'].b.toLocaleString() + '）');
    ok(B.over['n:IFREE-NDX'].b === 0 && sum(B.over) === B.T && B.over['n:SMH'].b > 0 && B.over['n:IFREE-NDX'].pre === B.A && B.over['n:SMH'].pre === B.B2 && ks.every(k => B.over[k].b >= 0),
       '   NASDAQ100 が目標超過: NASDAQ100 は自動の積立だけ・入金 ¥' + B.T.toLocaleString() + ' は残りの区分へ（SMH は自分の自動の積立を引いて ¥' + B.over['n:SMH'].b.toLocaleString() + '）');
    ok(ks.every(k => B.miss[k].b === B.solo[k].b) && B.miss['n:IFREE-NDX'].pre === B.A,
       '   区分に無い pre（n:NOPE）は数えない（取り分は NASDAQ100 の分だけを数えたときと同じ）');
    ok(B.partsOld.length === 1 && B.partsOld[0].lbl === 'iDeCo' && B.partsNone.length === 0, '   表示の内訳: 古い形（pre の額だけ）は iDeCo・0円なら出さない');
  }
  // 実データ（state.json＋全パック・割り方 'cat'）: 開始月を過ぎた設定にして、注文書と区分の比率と入金額の案内を読む
  const KO = base.target && base.target.kodomo_nisa, NPN = base.target && base.target.nisa;
  if (!KO || !(base.target.ideco)) ok(true, '   ⑮ 実データ: portfolio.json に target.kodomo_nisa か target.ideco が無い（飛ばす）');
  else {
    const IA = (base.target.ideco.members || []).reduce((a, x) => a + (+x.jpy || 0), 0), KA = (KO.members || []).reduce((a, x) => a + (+x.jpy || 0), 0);
    const NPJ = NPN && +NPN.monthly_jpy > 0 ? +NPN.monthly_jpy : 0;
    const readBox = async (amt) => {
      await pg.evaluate(a => { localStorage.setItem('pf:monthly_total', String(a)); showPage(5); }, amt); await pg.waitForTimeout(3200);
      return pg.evaluate(() => {
        const box = [...document.querySelectorAll('#pg5 div')].find(d => /📋 今月の注文書/.test(d.innerText) && /合計 約/.test(d.innerText) && d.innerText.length < 8000);
        const t = box ? box.innerText : '', m = t.match(/合計 約¥([\d,]+)/), rr = t.match(/残り¥([\d,]+)/);
        const note = [...document.querySelectorAll('#pg5 .auto-note')].map(e => e.innerText).join(' ／ ');
        const C = window.__ccfCat || null, pl = C ? ccfPreList(C.pre) : [];
        const line = [...document.querySelectorAll('#pg5 div')].filter(d => /区分の比率が最優先・1株単位/.test(d.innerText) && d.innerText.length < 600).map(d => d.innerText).pop() || '';
        return { kd: /🧒 こどもNISA（子どもの口座の自動の積立・注文書では買わない）/.test(t), id: /🏦 iDeCo（自動引き落とし・注文書では買わない）/.test(t),
          tot: m ? +m[1].replace(/,/g, '') : null, rest: rr ? +rr[1].replace(/,/g, '') : 0, pre: pl.reduce((a, x) => a + (+x.jpy), 0), preN: pl.length,
          kdTxt: ((document.querySelector('#pg5 .kodomo-row') || {}).innerText || ''), ndxRow: ((document.querySelector('#pg5 .catrow[data-cat="n:IFREE-NDX"]') || {}).innerText || ''),
          line, foot: (t.match(/＋ こどもNISA[^\n]*/) || [''])[0],
          ndxNow: (C && C['n:IFREE-NDX']) ? +C['n:IFREE-NDX'].now : null, tot0: C ? +C.tot : null,
          note, warn: !!document.querySelector('#pg5 .plan-warn'), next: (document.querySelector('#pg5 .plan-next') || {}).innerText || '' };
      });
    };
    const loadReal = async (over) => {
      OVER = over;
      await pg.goto('http://localhost:' + PORT + '/index.html'); await pg.waitForTimeout(600);
      await pg.evaluate(stt => { localStorage.clear(); for (const k in stt.data) localStorage.setItem(k, stt.data[k]);
        localStorage.setItem('ccf:stateSavedAt', stt.savedAt); }, ST);
      await pg.reload(); await pg.waitForTimeout(1500);
      await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1800);
    };
    const act = (() => { const o = withMode('cat'); o.target.ideco.start = '2000-01'; o.target.kodomo_nisa.start = '2000-01';
      if (o.target.nisa) o.target.nisa.monthly_from = '2000-01'; return o; })();
    await loadReal(act);
    const T1 = NPJ ? NPJ + IA + KA : 200000, r1 = await readBox(T1);
    const want1 = T1 - IA - KA;
    // ★2026-10-08「比率に数えて」: 正本に bucket があれば iDeCo とこどもNISA の両方を区分に数える（同じ NASDAQ100 なら pre は1つに合計）
    const KIN = KO.bucket ? KA : 0, yen = v => '¥' + (+v).toLocaleString('ja-JP');
    ok(r1.kd && r1.id && r1.pre === IA + KIN && r1.tot != null && r1.tot + r1.rest <= want1 && r1.tot + r1.rest >= want1 - 300
       && r1.note.includes('注文書で配るのは ¥' + want1.toLocaleString()) && !r1.warn,
       '⑮ 実データ・有効: 入金 ¥' + T1.toLocaleString() + ' → 注文書の合計 ¥' + (r1.tot || 0).toLocaleString() + (r1.rest ? '＋残り ¥' + r1.rest.toLocaleString() : '')
       + '（入金 − iDeCo ¥' + IA.toLocaleString() + ' − こどもNISA ¥' + KA.toLocaleString() + '）・iDeCo とこどもNISA の行あり・区分に数えた分 ¥' + r1.pre.toLocaleString()
       + '（' + (KIN ? 'iDeCo＋こどもNISA' : 'iDeCo だけ') + '）・計画の警告なし');
    if (KIN) {
      ok(r1.preN === 1 && /NASDAQ100 の区分に数える/.test(r1.kdTxt) && /✓ 保有へ/.test(r1.kdTxt)
         && r1.ndxRow.includes('＋iDeCo ' + yen(IA)) && r1.ndxRow.includes('＋こどもNISA ' + yen(KA))
         && r1.line.includes('＋iDeCo ' + yen(IA)) && r1.line.includes('＋こどもNISA ' + yen(KA)) && !/比率の外/.test(r1.line) && /NASDAQ100/.test(r1.foot),
         '   こどもNISA の行「…NASDAQ100 の区分に数える・✓ 保有へ」・区分の比率の表と上の1行が「＋iDeCo ' + yen(IA) + '＋こどもNISA ' + yen(KA) + '」（' + r1.ndxRow.replace(/\s+/g, ' ').slice(0, 90) + '）');
      // 「✓ 保有へ」: 口座 こどもNISA のロットを🏦保有へ（名義は members の who）。記録した後は NASDAQ100 の区分の「今」が増え、行が「記録済み」になる
      const cl = await pg.evaluate(async () => {
        const btn = [...document.querySelectorAll('#pg5 .kodomo-row button')].find(b => /保有へ/.test(b.textContent));
        if (!btn) return { err: 'ボタンが無い' };
        const K0 = window.__ccfKodomo, upx = K0 ? +K0.upx : 0, fund = K0 ? K0.fund : '';
        btn.click(); await new Promise(r => setTimeout(r, 4500));
        const P = JSON.parse(localStorage.getItem('pf:portfolio') || '{}'), row = (P.positions || []).find(x => String(x.t || '').toUpperCase() === fund);
        const ym = ccfTradeToday().slice(0, 7), lots = ((row && row.bdLots) || []).filter(l => l.acct === 'こどもNISA' && String(l.bd || '').slice(0, 7) === ym);
        const C = window.__ccfCat || null;
        return { upx, fund, lots, kdTxt: ((document.querySelector('#pg5 .kodomo-row') || {}).innerText || ''),
          ndxNow: (C && C['n:IFREE-NDX']) ? +C['n:IFREE-NDX'].now : null, tot: C ? +C.tot : null };
      });
      const lot = (cl.lots || [])[0], sh = cl.upx > 0 ? Math.floor(KA / cl.upx) : 0;
      const dHeld = (cl.ndxNow != null && r1.ndxNow != null) ? cl.ndxNow * cl.tot / 100 - r1.ndxNow * r1.tot0 / 100 : NaN, vLot = sh * cl.upx;
      ok(!cl.err && cl.lots.length === (KO.members || []).filter(x => +x.jpy > 0).length && !!lot && lot.who === (KO.members[0] || {}).who && lot.jpy === KA && lot.sh === sh
         && /記録済み/.test(cl.kdTxt) && Math.abs(dHeld - vLot) < 2,
         '   「✓ 保有へ」: ' + (cl.err || ('口座 こどもNISA のロット ' + (lot ? lot.who + '・' + yen(lot.jpy) + '・' + lot.sh + '口' : 'なし') + '・NASDAQ100 の区分の保有 +' + yen(Math.round(dHeld))
         + '（ロットの評価 ' + yen(Math.round(vLot)) + '）・行が「記録済み」')));
    }
    if (NPJ) {
      const T2 = NPJ + IA + KA - 30000, r2 = await readBox(T2);
      ok(r2.warn && r2.note.includes('計画どおりなら入金額は ¥' + (NPJ + IA + KA).toLocaleString()),
         '   入金 ¥' + T2.toLocaleString() + '（計画より3万少ない）→ 「計画どおりなら入金額は ¥' + (NPJ + IA + KA).toLocaleString() + '」と知らせる');
    }
    // bucket を空にすると比率の外（旧 v9.9.203 の扱い）: pre は iDeCo だけ・行は「家族の区分の比率には数えない」・上の1行は「（自動・比率の外）」
    if (KO.bucket) {
      const outC = JSON.parse(JSON.stringify(act)); delete outC.target.kodomo_nisa.bucket;
      await loadReal(outC);
      const r4 = await readBox(T1);
      ok(r4.pre === IA && /家族の区分の比率には数えない/.test(r4.kdTxt) && !/保有へ/.test(r4.kdTxt) && /こどもNISA ¥[\d,]+（自動・比率の外）/.test(r4.line)
         && !r4.ndxRow.includes('こどもNISA') && r4.tot + r4.rest <= want1 && r4.tot + r4.rest >= want1 - 300,
         '   bucket を消すと比率の外: 区分に数えるのは iDeCo ¥' + r4.pre.toLocaleString() + ' だけ・行「家族の区分の比率には数えない」・注文書の合計は同じ（¥' + (r4.tot || 0).toLocaleString() + '）');
    }
    // 開始月の前（正本の start のまま）: 行は出さず、案内に「いつから・その月からの入金額」を出す
    const pre = withMode('cat'); pre.target.ideco.start = '2999-12'; pre.target.kodomo_nisa.start = '2999-12'; if (pre.target.nisa) pre.target.nisa.monthly_from = '2999-12';
    await loadReal(pre);
    const r3 = await readBox(170000);
    ok(!r3.kd && !r3.id && r3.pre === 0 && /こどもNISA（[^）]*）は 2999-12 から/.test(r3.note) && (!NPJ || r3.next.includes('2999-12 からの入金額 ¥' + (NPJ + IA + KA).toLocaleString())),
       '   開始月の前: 行なし・入金額を全部配る・案内「' + (r3.next || r3.note).slice(0, 80) + '」');
  }

  // ⑯ その他 ETF・投資信託（v9.9.204・2026-10-09 ユーザー明示指示「QQQ50% SMH20% 個別株15% その他ETF投資信託15%に変更して」）:
  //   target.ami_other の buy の本の区分に、目標0%で持っている本と目標に無い本（drop）の保有を数える。同じ指数の本（QQQM）は数えない
  {
    await pg.goto('http://localhost:' + PORT + '/index.html'); await pg.waitForTimeout(600);
    const q16 = await pg.evaluate(() => {
      localStorage.clear();   // 台帳（pf:portfolio）を空にして、下の合成の保有（portfolio.json の形）だけを読ませる
      const mk = (other) => ({ asof: '2026-10-09', positions: [
          { ticker: 'IFREE-NDX', value_jpy: 300000, sleeve: '網' }, { ticker: 'QQQM', value_jpy: 100000, sleeve: '網' },
          { ticker: 'XLK', value_jpy: 150000, sleeve: '網' }, { ticker: 'SMH', value_jpy: 150000, sleeve: '網' },
          { ticker: 'GRID', value_jpy: 50000, sleeve: '網' }, { ticker: 'GLDM', value_jpy: 50000, sleeve: '網' },
          { ticker: 'MSFT', value_jpy: 200000, sleeve: '城' }],
        target: { ami_net_pct: 85, ami_names: ['IFREE-NDX', 'QQQM', 'XLK', 'SMH', 'GRID'],
          ami_weights: { 'IFREE-NDX': 50, QQQM: 0, XLK: 15, SMH: 20, GRID: 0 }, ami_same_index: { 'IFREE-NDX': ['QQQM'] },
          ...(other ? { ami_other: other } : {}) } });
      const on = ccfNetRows(null, mk({ buy: 'XLK', label: 'その他 ETF・投資信託' })), off = ccfNetRows(null, mk(null)), bad = ccfNetRows(null, mk({ buy: 'GRID' }));
      const x = (r, t) => r.rows.find(y => y.t === t);
      const lab = ccfCatLabel({ 'n:XLK': { t: 15, nm: 'その他 ETF・投資信託', other: { buy: 'XLK', members: ['GRID', 'GLDM'] } } }, 'n:XLK', { full: true });
      const labP = ccfCatLabel({ 'n:XLK': { t: 15, nm: 'その他 ETF・投資信託', other: { buy: 'XLK', members: [] } } }, 'n:XLK', { plain: true });
      return { onX: x(on, 'XLK'), offX: x(off, 'XLK'), onI: x(on, 'IFREE-NDX'), onG: x(on, 'GRID'), onDrop: on.drop, offDrop: off.drop, other: on.other,
        badO: bad.other, badX: x(bad, 'XLK'), badG: x(bad, 'GRID'), lab, labP };
    });
    const r1 = v => Math.round(v * 10) / 10;
    ok(r1(q16.onX.pos) === 25 && q16.onX.oth.join(',') === 'GRID,GLDM' && r1(q16.onX.othPos) === 10 && q16.onX.otherBuy && r1(q16.offX.pos) === 15
       && q16.onG.otherOf === 'XLK' && q16.onDrop.length === 1 && q16.onDrop[0].t === 'GLDM' && q16.onDrop[0].otherOf === 'XLK' && !q16.offDrop[0].otherOf
       && r1(q16.onI.pos) === 40 && r1(q16.other.pos) === 25 && q16.other.label === 'その他 ETF・投資信託',
       '⑯ その他 ETF・投資信託: XLK の保有% 15 → ' + r1(q16.onX.pos) + '（目標0%の GRID 5 と目標に無い GLDM 5 を数える）・NASDAQ100 は同じ指数の QQQM だけ（' + r1(q16.onI.pos) + '%）・設定が無ければ 15 のまま');
    ok(q16.badO && /買う本（GRID）が ETF の目標/.test(q16.badO.err || '') && r1(q16.badX.pos) === 15 && !q16.badG.otherOf,
       '   買う本が目標>0 の本でなければ数えず名指し（' + ((q16.badO && q16.badO.err) || '').slice(0, 40) + '…）');
    ok(q16.lab === '◈ その他 ETF・投資信託（今は XLK で買う・GRID・GLDM を含む）' && q16.labP === 'その他 ETF・投資信託',
       '   区分の名前: 表「' + q16.lab + '」・文の中「' + q16.labP + '」');
    // 実データ（state.json＋全パック・割り方 'cat'）に GRID を3株足して: 区分の比率の表・上の1行・材料（__ccfCat）が その他 として数える
    const ST2 = JSON.parse(JSON.stringify(ST)), P2 = JSON.parse(ST2.data['pf:portfolio'] || '{"positions":[]}');
    P2.positions.push({ t: 'GRID', nm: 'GRID', sleeve: 'net', kind: 'ETF', sh: 3, ccy: 'USD', npx: 179.79, bpx: 179.79, bjpy: 80000 });
    ST2.data['pf:portfolio'] = JSON.stringify(P2);
    const load16 = async (over) => {
      OVER = over;
      await pg.goto('http://localhost:' + PORT + '/index.html'); await pg.waitForTimeout(600);
      await pg.evaluate(stt => { localStorage.clear(); for (const k in stt.data) localStorage.setItem(k, stt.data[k]);
        localStorage.setItem('ccf:stateSavedAt', stt.savedAt); }, ST2);
      await pg.reload(); await pg.waitForTimeout(1500);
      await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1800);
      await pg.evaluate(() => { localStorage.setItem('pf:monthly_total', '170000'); showPage(5); }); await pg.waitForTimeout(3200);
      return pg.evaluate(() => {
        const C = window.__ccfCat || {};
        const rowTxt = ((document.querySelector('#pg5 .catrow[data-cat="n:XLK"]') || {}).innerText || '');
        const zero = ((document.querySelector('#pg5 .catrow[data-cat="zero"]') || {}).innerText || '');
        const line = [...document.querySelectorAll('#pg5 div')].filter(d => /区分の比率が最優先・1株単位/.test(d.innerText) && d.innerText.length < 600).map(d => d.innerText).pop() || '';
        return { x: C['n:XLK'] || null, z: C._zero || null, tot: +C.tot || 0, rowTxt, zero, line, keys: ccfCatKeys(C) };
      });
    };
    const ao = withMode('cat');
    const w16 = await load16(ao);
    const noAo = withMode('cat'); delete noAo.target.ami_other;
    const w16off = await load16(noAo);
    const gridPct = w16off.z && w16off.z.nm.includes('GRID') ? w16off.z.now : NaN;
    ok(!!ao.target.ami_other && w16.x && w16.x.nm === ao.target.ami_other.label && w16.x.other && w16.x.other.members.includes('GRID')
       && Math.abs(w16.x.now - (w16off.x.now + gridPct)) < 0.05 && w16.z && w16.z.now === 0 && !w16.zero
       && /その他 ETF・投資信託（今は XLK で買う・GRID を含む）/.test(w16.rowTxt) && /^NASDAQ100 ¥[\d,]+ ／ その他 ETF・投資信託 ¥[\d,]+ ／ SMH ¥[\d,]+/.test(w16.line.trim()) && / ／ 個別株 ¥[\d,]+/.test(w16.line),
       '⑯ 実データ＋GRID 3株: その他の区分の今 ' + (w16.x ? w16.x.now.toFixed(1) : '?') + '%＝XLK ' + (w16off.x ? w16off.x.now.toFixed(1) : '?') + '%＋GRID ' + (+gridPct).toFixed(1)
       + '%・区分の外の「その他」の行なし・表「' + w16.rowTxt.split('\n')[0].slice(0, 40) + '」・上の1行「' + w16.line.trim().slice(0, 60) + '」');
    ok(w16off.x && w16off.x.nm === 'XLK' && !w16off.x.other && /その他（目標0%で持ち続けている本：GRID）/.test(w16off.zero),
       '   ami_other を消すと v9.9.203 の姿: XLK は自分だけの区分・GRID は区分の外の「その他（目標0%…）」の1行');
  }

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  await pg.evaluate(() => localStorage.removeItem('pf:monthly_total'));
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
