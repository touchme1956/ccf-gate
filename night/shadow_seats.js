#!/usr/bin/env node
/* night/shadow_seats.js — 席の数（CCF_SEATS）を変えたら、今月の注文書と1年の積立がどう変わるか（影の計測・読むだけ）
 *
 * ■ なぜ要るか
 *   2026-10-05 ユーザーの問い「4社から10社に増やす案は？」。席の数は score_all で「誰が席に入るか」までは
 *   出せるが、**実際に何を何株買うか**は門の注文書（ccfWholeSharePlan・1株単位・不足÷目標の大きい順、同じなら安い順）が
 *   決めるので、端末の計算では出ない。席を変えると目標％（個別÷社数）が変わり、買う順番と個別/ETFの割れ方まで動く。
 *
 * ■ 何をするか
 *   index.html を**配信のときだけ**書き換えて（`var CCF_SEATS=N;`）門を実ブラウザで開く。正本のファイルには触らない。
 *   全パックを一括取込 → 🛒買付順位を描く → 門が自分で作った注文書（ccfWholeSharePlan の引数と結果）を読む。
 *   さらに同じ関数で12か月を回す（価格・為替は一定・毎月同額・残った円は翌月の入金へ・売らない）。
 *   保有は state.json（門が repo から読む）、価格は out/dashboard.json。
 *   **判定には使わない**——Ω・四関門・席・配分・売却規律のどれも変えない。
 *
 * 使い方: NODE_PATH=$(npm root -g) node night/shadow_seats.js [--seats 4,7,10] [--monthly 170000] [--out FILE]
 *   --seats   比べる席の数（既定: いまの CCF_SEATS と 10）
 *   --monthly 毎月の入金額（既定: state.json の pf:monthly_total → pf:monthly の順に読む。無ければ止まる）
 *   --out     結果の書き先（既定: out/shadow_seats.json）
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8812;
const EXE = fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined;

const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const html0 = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const mNow = html0.match(/var CCF_SEATS=(\d+);/);
if (!mNow) { console.error('✗ index.html に var CCF_SEATS が見つからない＝席を差し替えられない'); process.exit(1); }
const NOW = +mNow[1];
const SEATS_LIST = (arg('--seats') ? arg('--seats').split(',').map(Number) : [NOW, 10])
  .filter((v, i, a) => v > 0 && a.indexOf(v) === i);
let MONTHLY = +arg('--monthly') || 0, MONTHLY_SRC = '--monthly';
if (!MONTHLY) {
  try {
    const st = JSON.parse(fs.readFileSync(path.join(ROOT, 'state.json'), 'utf8')).data || {};
    for (const k of ['pf:monthly_total', 'pf:monthly']) if (+st[k] > 0) { MONTHLY = +st[k]; MONTHLY_SRC = 'state.json ' + k; break; }
  } catch (e) {}
}
if (!MONTHLY) { console.error('✗ 毎月の入金額が読めない（--monthly で渡す）'); process.exit(1); }
const OUT = arg('--out') || path.join(ROOT, 'out', 'shadow_seats.json');

let SEATS = NOW;
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  let f = path.join(ROOT, rel); if (f.endsWith('/')) f += 'index.html';
  try {
    let b = fs.readFileSync(f);
    if (f === path.join(ROOT, 'index.html')) b = Buffer.from(b.toString('utf8').replace(/var CCF_SEATS=\d+;/, 'var CCF_SEATS=' + SEATS + ';'), 'utf8');
    r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.json') ? 'application/json'
      : f.endsWith('.css') ? 'text/css' : f.endsWith('.svg') ? 'image/svg+xml' : 'text/html' });
    r.end(b);
  } catch (e) { r.writeHead(404); r.end('x'); }
});

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const b = await chromium.launch(EXE ? { executablePath: EXE } : {});
  const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = []; p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
  await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(2500);
  // ⭳ 全パック一括取込（check_gate_parity と同じ。台帳が空だと買付順位は何も描かない）
  await p.evaluate(() => { const t = document.getElementById('tab3'); if (t) t.click(); });
  await p.waitForTimeout(600);
  await p.evaluate(() => (typeof ccfImportAllPacks === 'function' ? ccfImportAllPacks() : null));
  let prev = -1, stable = 0;
  for (let i = 0; i < 90; i++) {
    await p.waitForTimeout(2000);
    const n = await p.evaluate(() => { let c = 0; for (let i = 0; i < localStorage.length; i++) if (localStorage.key(i).startsWith('g7:')) c++; return c; });
    if (n === prev) { if (++stable >= 3) break; } else { stable = 0; prev = n; }
  }
  console.log(`■ 席の数を変えたら（night/shadow_seats.js・影の計測）  台帳 ${prev}件 / 入金 ¥${MONTHLY.toLocaleString()}（${MONTHLY_SRC}）`);

  const out = { asof: new Date().toISOString(), monthly: MONTHLY, monthly_src: MONTHLY_SRC, seats_now: NOW, runs: {} };
  let bad = 0;
  for (const N of SEATS_LIST) {
    SEATS = N;
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2500);
    // 門が自分で呼ぶ ccfWholeSharePlan の引数を写し取る（計算は門の関数そのもの＝二重実装しない）
    await p.evaluate((m) => {
      localStorage.setItem('pf:monthly_total', String(m));
      const orig = window.ccfWholeSharePlan; window.__wspOrig = orig;
      window.ccfWholeSharePlan = function (items, T, TOT) { window.__cap = JSON.parse(JSON.stringify({ items, T, TOT })); return orig(items, T, TOT); };
      // 行の鍵 C{i} は ccfWholeShareBody の pass の添字なので、名前は pass そのものから読む
      const ob = window.ccfWholeShareBody;
      window.ccfWholeShareBody = function (pass, ...rest) { window.__pass = (pass || []).map(r => String(r.t || r.nm || '')); return ob(pass, ...rest); };
    }, MONTHLY);
    await p.evaluate(() => { const t = document.getElementById('tab5'); if (t) t.click(); });
    let blind = null;
    for (let i = 0; i < 40; i++) {     // 眠っている関門（pending/stale）が届くまで待つ
      await p.waitForTimeout(1000);
      blind = await p.evaluate(() => (window.__ccfBuyBlind || null));
      if (Array.isArray(blind) && !blind.length) break;
      await p.evaluate(() => { const t = document.getElementById('tab5'); if (t) t.click(); });
    }
    await p.waitForTimeout(2500);
    const run = await p.evaluate(({ M }) => {
      const cap = window.__cap || null, buy = window.__ccfBuyList || null;
      if (!cap) return { seats: CCF_SEATS, buy, cap: null };
      const label = {}, pass = window.__pass || [];
      const box = [...document.querySelectorAll('#pg5 div')].find(d => /📋 今月の注文書/.test(d.innerText) && /合計 約/.test(d.innerText) && d.innerText.length < 5000);
      cap.items.forEach(it => { if (it.k[0] === 'C') label[it.k] = pass[+it.k.slice(1)] || it.k; });
      const items = cap.items.map(x => Object.assign({}, x));
      let TOT = cap.TOT; const H = {}; items.forEach(it => H[it.k] = (+it.pos || 0) * TOT / 100);
      const start_pct = +items.filter(it => it.k[0] === 'C').reduce((a, it) => a + (+it.pos || 0), 0).toFixed(1);
      let carry = 0; const months = [];
      for (let m = 1; m <= 12; m++) {
        items.forEach(it => it.pos = 100 * H[it.k] / TOT);
        const T = M + carry, P = window.__wspOrig(items, T, TOT);
        let spent = 0, cs = 0, ns = 0; const got = [];
        items.forEach(it => {
          const bb = P.buy[it.k]; if (bb) { H[it.k] += bb.cost; spent += bb.cost; if (it.k[0] === 'C') { cs += bb.cost; got.push((label[it.k] || it.k) + '×' + bb.sh); } else { ns += bb.cost; got.push('ETF' + it.k + '×' + bb.sh); } }
          const fy = P.frac[it.k]; if (fy) { H[it.k] += fy; spent += fy; ns += fy; }
        });
        carry = T - spent; TOT += spent;
        const castle = items.filter(it => it.k[0] === 'C').reduce((a, it) => a + H[it.k], 0);
        months.push({ m, castle_yen: Math.round(cs), etf_yen: Math.round(ns), castle_pct: +(100 * castle / TOT).toFixed(1), castle_bought: got.filter(x => !/^ETF/.test(x)).join(' ') });
      }
      const end = items.filter(it => it.k[0] === 'C').map(it => ({ t: label[it.k] || it.k, target_pct: +(+it.tw).toFixed(2),
        pct: +(100 * H[it.k] / TOT).toFixed(2), shares: it.jpy > 0 ? Math.round(H[it.k] / it.jpy) : null }));
      return { seats: CCF_SEATS, buy, order_text: box ? box.innerText : null, start_pct, months, end, tot0: Math.round(cap.TOT) };
    }, { M: MONTHLY });
    if (run.seats !== N) { bad++; console.log(`  ✗ 席 ${N}: 門の CCF_SEATS が ${run.seats}（差し替えが効いていない）`); continue; }
    // 関門が眠ったまま描いた注文書は「測れなかった」であって結果ではない（check_gate_parity と同じ・ルール7）
    if (!Array.isArray(blind) || blind.length) { bad++; console.log(`  ✗ 席 ${N}: 関門が眠ったまま（${Array.isArray(blind) ? blind.join(' / ') : '未公開'}）＝測れなかった`); continue; }
    if (!run.months) { bad++; console.log(`  ✗ 席 ${N}: 注文書の計算を読めなかった`); continue; }
    out.runs[N] = run;
    const y1 = run.months.reduce((a, x) => a + x.castle_yen, 0), e1 = run.months.reduce((a, x) => a + x.etf_yen, 0);
    const pk = run.months.reduce((a, x) => (x.castle_pct > a.castle_pct ? x : a), run.months[0]);
    console.log(`\n■ 席 ${N}: 投下可 ${run.buy.length}社（${run.buy.join(' ')}）／目標 各${run.end[0] ? run.end[0].target_pct : '?'}%`);
    console.log(`  今月  個別 ¥${run.months[0].castle_yen.toLocaleString()}（${run.months[0].castle_bought || 'なし'}） ／ ETF ¥${run.months[0].etf_yen.toLocaleString()}`);
    console.log(`  1年   個別 ¥${y1.toLocaleString()} ／ ETF ¥${e1.toLocaleString()}　個別の比率 ${run.start_pct}%（いま）→ ${run.months[0].castle_pct}%（1か月後）→ 最大 ${pk.castle_pct}%（${pk.m}か月後）→ ${run.months[11].castle_pct}%（12か月後）`);
    console.log('  12か月後の個別: ' + run.end.map(x => `${x.t} ${x.shares}株 ${x.pct}%`).join(' / '));
  }
  out.pageerrors = errs;
  fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
  console.log(`\n  pageerror ${errs.length}件　書き出し ${path.relative(ROOT, OUT)}`);
  await b.close(); srv.close();
  process.exit(bad || errs.length ? 1 : 0);
})();
