#!/usr/bin/env node
/* night/check_fund_trade.js — 🏦保有の「＋ 買った／− 売った」で投資信託を記録できるかを実ブラウザで確かめる
 *
 * ■ なぜ要るか
 *   2026-10-05 ユーザー明示指示「投資信託を購入した際に保有から入力できるように変更して」。
 *   旧の記入欄は**株数×ドルの単価**しか受けず、iFreeNEXT を「＋ 新しい銘柄」から入れると
 *   **個別株・ドル建て**の行ができた（評価額が 口数×単価×ドル円 に化け、区分の比率でも個別株に数えられる）。
 *
 * ■ 判定
 *   ① 持っていない投資信託（portfolio.json の target.ami_funds）が銘柄の一覧に出る
 *   ② 選ぶと欄が 買付金額（円）・基準価額（1万口あたり）・口数 に切り替わり、株の欄は隠れる・口座はつみたて投資枠
 *      基準価額は盤（out/dashboard.json）の値が入っている
 *   ③ 金額だけで記録 → 口数＝金額÷(基準価額÷1万口) の切り捨て・袖 net・円・種類「投資信託」・取得額＝払った円・
 *      ロットに口座と名義・評価額≈口数×1口あたりの円
 *   ④ 口数を入れて買い増し → 口数と取得額が足し上がる
 *   ⑤ 口数で一部売却 → 残りの口数・取得額の按分・売却記録（受取額は 口数×基準価額 の見積もり）
 *   ⑥ 金額が空なら記録しない（理由を言う）
 *   ⑦ 株の欄は従来どおり（MSFT を選ぶと株数・ドルの単価・成長投資枠）
 *   ⑧ 旧の罠（個別株・ドル建ての IFREE-NDX 行）には足さずに直し方を言う
 *   ⑨ 買付順位の「＋円」で作った行も種類が「投資信託」になる
 *   ⑩ 🏦保有の一覧が「口・基準価額」と「投資信託・門の裁きではない」を出す／盤が基準価額（/万口）を出す
 *   ⑪ 携帯の幅（320/360/390px）で記入欄がはみ出さない
 *   ⑫ pageerror が出ない
 *   ⑬ iDeCo の本（ami_funds の account:'iDeCo'）を選ぶと口座の既定が iDeCo・ロットに口座 iDeCo が残る（v9.9.202）
 *   ⑭ こどもNISA（2026-10-08「比率に数えて」）: 口座に「こどもNISA」・名義に target.kodomo_nisa の名義が出る・記録したロットに両方が残る
 *   ★基準価額・1万口・投資信託の名前は**正本から読む**（書き写さない）。
 *
 * playwright が要るので CI には入れていない。使い方: NODE_PATH=$(npm root -g) node night/check_fund_trade.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8797;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  let f = path.join(ROOT, rel);
  if (f.endsWith('/')) f += 'index.html';
  try {
    const b = fs.readFileSync(f);
    r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript'
      : f.endsWith('.json') ? 'application/json' : f.endsWith('.css') ? 'text/css'
      : f.endsWith('.jpg') ? 'image/jpeg' : f.endsWith('.png') ? 'image/png' : f.endsWith('.svg') ? 'image/svg+xml' : 'text/html' });
    r.end(b);
  } catch (e) { r.writeHead(404); r.end('x'); }
});

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const PJ = JSON.parse(fs.readFileSync(path.join(ROOT, 'portfolio.json'), 'utf8'));
  const FKEY = Object.keys(PJ.target.ami_funds || {})[0];
  const FUND = PJ.target.ami_funds[FKEY];
  const NPER = +FUND.navPer || 10000;
  const DQ = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/dashboard.json'), 'utf8')).quotes[FKEY];
  const NAV = +DQ.nav > 0 ? +DQ.nav : +DQ.px * NPER, UPX = NAV / NPER;
  const HOLD1 = ((PJ.target.nisa || {}).holders || [])[0] || '';
  const ST = JSON.parse(fs.readFileSync(path.join(ROOT, 'state.json'), 'utf8'));

  const b = await chromium.launch({ executablePath: CHROME });
  const pg = await b.newPage({ viewport: { width: 1100, height: 1400 } });
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  let ng = 0;
  const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

  /* state.json の保有で始める（posMod で行を足し引きできる）。repo と同じ時刻にして自動の取り込みを起こさない */
  const seed = async posMod => {
    await pg.goto('http://localhost:' + PORT + '/index.html');
    await pg.waitForTimeout(600);
    await pg.evaluate(([st, mod]) => {
      localStorage.clear();
      const d = st.data || {};
      for (const k in d) localStorage.setItem(k, d[k]);
      if (mod) { const o = JSON.parse(localStorage.getItem('pf:portfolio')); o.positions = (new Function('ps', mod))(o.positions); localStorage.setItem('pf:portfolio', JSON.stringify(o)); }
      localStorage.setItem('ccf:stateSavedAt', st.savedAt);
      localStorage.removeItem('ccf:stateDirty');
    }, [ST, posMod || '']);
    await pg.reload(); await pg.waitForTimeout(1800);
    await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(800);
  };
  const open = async kind => { await pg.evaluate(k => { const bx = document.getElementById('tradeBox'); bx.innerHTML = ''; bx.dataset.kind = ''; ccfTrade(k); }, kind); await pg.waitForTimeout(900); };
  const pick = async t => { await pg.evaluate(t => { const s = document.getElementById('trT'); s.value = t; s.dispatchEvent(new Event('change')); }, t); await pg.waitForTimeout(150); };
  const fill = async (o) => { await pg.evaluate(o => { for (const k in o) { const e = document.getElementById(k); e.value = o[k]; e.dispatchEvent(new Event('input')); } }, o); await pg.waitForTimeout(100); };
  const go = async kind => { await pg.evaluate(k => { const bs = [...document.querySelectorAll('#tradeBox button')].find(x => x.textContent.trim() === '記録する'); bs.click(); }, kind); await pg.waitForTimeout(1200); };
  const msg = () => pg.evaluate(() => (document.getElementById('trMsg') || {}).textContent || '');
  const row = t => pg.evaluate(t => (JSON.parse(localStorage.getItem('pf:portfolio') || '{}').positions || []).find(p => p.t === t) || null, t);
  const vis = cls => pg.evaluate(c => [...document.querySelectorAll('#tradeBox .' + c)].map(e => getComputedStyle(e).display !== 'none'), cls);

  console.log('■ 🏦保有から投資信託を記録（night/check_fund_trade.js）');
  console.log(`  正本: ${FKEY}（${FUND.name}）・基準価額 ${NAV}円/${NPER}口（盤 ${DQ.day}）・名義の1人目 ${HOLD1}`);

  // ── ①② 一覧と欄の切り替え
  await seed();
  await open('buy');
  const opts = await pg.evaluate(() => [...document.getElementById('trT').options].map(o => [o.value, o.textContent]));
  const fo = opts.find(o => o[0] === FKEY);
  ok(!!fo && /投資信託・円で記録/.test(fo[1]), `① 持っていない ${FKEY} が銘柄の一覧に出る（${fo ? fo[1] : 'なし'}）`);
  await pick(FKEY);
  const vf = await vis('tr-fnd'), vs = await vis('tr-stk');
  ok(vf.length === 3 && vf.every(Boolean) && vs.length === 3 && vs.every(x => !x), `② 投資信託の欄3つが出て株の欄3つが隠れる（出${vf.filter(Boolean).length}/隠${vs.filter(x => !x).length}）`);
  const f2 = await pg.evaluate(() => ({ title: document.getElementById('trTitle').textContent, acct: document.getElementById('trA').value,
    nav: +document.getElementById('trFN').value, hint: document.getElementById('trHint').textContent }));
  ok(f2.title === '＋ 買った投資信託を記録' && f2.acct === 'つみたて', `② 見出し「${f2.title}」・口座「${f2.acct}」`);
  ok(Math.abs(f2.nav - NAV) < 0.01, `② 基準価額に盤の値 ${f2.nav} が入る`);
  ok(/まだ持っていません/.test(f2.hint) && /盤の最新/.test(f2.hint), '② 案内が「まだ持っていません」「盤の最新」を言う');

  // ── ⑥ 金額が空
  await go('buy');
  ok(/買付金額（円）を入れてください/.test(await msg()), '⑥ 金額が空なら記録しない（理由を言う）');

  // ── ③ 金額だけで記録
  const Y1 = 100000, U1 = Math.floor(Y1 / UPX);
  await fill({ trFJ: Y1 });
  const ph = await pg.evaluate(() => document.getElementById('trFU').placeholder);
  ok(ph.includes(U1.toLocaleString('ja-JP') + '口'), `③ 口数の欄が見積もり ${U1.toLocaleString('ja-JP')}口 を出す（${ph}）`);
  await go('buy');
  const m3 = await msg();
  ok(/^✓/.test(m3) && m3.includes('+' + U1.toLocaleString('ja-JP') + '口'), `③ 記録の返事: ${m3.slice(0, 90)}`);
  const r3 = await row(FKEY);
  ok(!!r3 && r3.sleeve === 'net' && r3.ccy === 'JPY' && r3.kind === '投資信託' && r3.sh === U1 && r3.bjpy === Y1 && +r3.navPer === NPER,
     `③ 行: 袖 ${r3 && r3.sleeve}・${r3 && r3.ccy}・${r3 && r3.kind}・${r3 && r3.sh}口・取得 ¥${r3 && r3.bjpy}・1万口=${r3 && r3.navPer}`);
  ok(!!r3 && Math.abs(r3.bpx - UPX) < 1e-5, `③ 1口あたりの取得単価 ${r3 && r3.bpx}（基準価額÷${NPER}＝${UPX.toFixed(6)}）`);
  const lot = r3 && (r3.bdLots || [])[0];
  ok(!!lot && lot.acct === 'つみたて' && lot.who === HOLD1 && lot.jpy === Y1 && lot.sh === U1, `③ ロット: ${JSON.stringify(lot)}`);
  const lv = await pg.evaluate(t => { const m = ccfLedgerMap(); return m && m.byT ? m.byT[t] : (m && m[t]) || m; }, FKEY);
  const vExp = U1 * UPX;
  const lvV = lv && (lv.v != null ? lv.v : null);
  ok(lvV != null && Math.abs(lvV - vExp) < 1 && (lv.sleeve === '網'), `③ 門の台帳の評価 ¥${lvV != null ? Math.round(lvV) : '?'}（口数×1口の円＝¥${Math.round(vExp)}）・袖 ${lv && lv.sleeve}`);

  // ── ④ 口数を入れて買い増し
  await open('buy'); await pick(FKEY);
  const Y2 = 50000, U2 = 8690;
  await fill({ trFJ: Y2, trFU: U2 });
  await go('buy');
  const r4 = await row(FKEY);
  ok(!!r4 && r4.sh === U1 + U2 && r4.bjpy === Y1 + Y2 && (r4.bdLots || []).length === 2,
     `④ 買い増し: ${r4 && r4.sh}口（${U1}+${U2}）・取得 ¥${r4 && r4.bjpy}・ロット ${r4 && (r4.bdLots || []).length}`);
  const optHeld = await pg.evaluate(t => [...document.getElementById('trT').options].find(o => o.value === t).textContent, FKEY);
  ok(optHeld.includes((U1 + U2).toLocaleString('ja-JP') + '口'), `④ 一覧の表示が口数に変わる（${optHeld}）`);

  // ── ⑤ 口数で一部売却
  await open('sell'); await pick(FKEY);
  const S5 = 1000;
  const f5 = await pg.evaluate(() => ({ title: document.getElementById('trTitle').textContent }));
  await fill({ trFU: S5 });
  const ph5 = await pg.evaluate(() => document.getElementById('trFJ').placeholder);
  const J5 = Math.round(S5 * UPX);
  ok(f5.title === '− 売った投資信託を記録' && ph5.includes('¥' + J5.toLocaleString('ja-JP')), `⑤ 見出し「${f5.title}」・受取額の見積もり（${ph5}）`);
  await go('sell');
  const r5 = await row(FKEY), sold = await pg.evaluate(() => JSON.parse(localStorage.getItem('pf:sold') || '[]'));
  const s5 = sold.filter(s => s.t === FKEY).slice(-1)[0];
  const left = U1 + U2 - S5, bjLeft = Math.round((Y1 + Y2) * left / (U1 + U2));
  ok(!!r5 && r5.sh === left && r5.bjpy === bjLeft, `⑤ 残り ${r5 && r5.sh}口（期待 ${left}）・取得 ¥${r5 && r5.bjpy}（按分 ¥${bjLeft}）`);
  ok(!!s5 && s5.sh === S5 && s5.jpy === J5 && s5.partial === true && /見積もり/.test(s5.memo || ''), `⑤ 売却記録: ${s5 ? JSON.stringify({ sh: s5.sh, jpy: s5.jpy, partial: s5.partial, memo: s5.memo }) : 'なし'}`);
  ok(/−1,000口/.test(await msg()), `⑤ 返事が口で言う（${(await msg()).slice(0, 60)}）`);

  // ── ⑩ 一覧と盤の表示
  /* 門は開くたびに金額を隠す（pf:showMoney='0'）——口数・基準価額は金額の表示の中なので、出してから読む */
  const pfTxt = await pg.evaluate(async () => { const f = document.getElementById('pfFrame');
    localStorage.setItem('pf:showMoney', '1'); f.contentWindow.render(); await new Promise(r => setTimeout(r, 200));
    const t = f.contentDocument.getElementById('holdList').innerText; localStorage.setItem('pf:showMoney', '0'); f.contentWindow.render(); return t; });
  ok(/[\d,]+口・基準価額¥[\d,]+\/万口/.test(pfTxt) && /投資信託・門の裁きではない/.test(pfTxt), `⑩ 🏦保有の一覧が「口・基準価額…/万口」「投資信託・門の裁きではない」を出す（${(pfTxt.match(/IFREE-NDX[^\n]*/) || [''])[0].slice(0, 90)}）`);
  await pg.evaluate(() => ccfDash()); await pg.waitForTimeout(900);
  const dashTxt = await pg.evaluate(() => (document.getElementById('dashBox') || document.body).innerText);
  ok(dashTxt.includes('¥' + Math.round(NAV).toLocaleString('ja-JP') + '/万口'), `⑩ 盤が基準価額 ¥${Math.round(NAV).toLocaleString('ja-JP')}/万口 を出す`);

  // ── ⑦ 株の欄は従来どおり
  await open('buy'); await pick('MSFT');
  const v7f = await vis('tr-fnd'), v7s = await vis('tr-stk');
  const f7 = await pg.evaluate(() => ({ acct: document.getElementById('trA').value, px: +document.getElementById('trP').value, title: document.getElementById('trTitle').textContent }));
  ok(v7f.every(x => !x) && v7s.every(Boolean) && f7.acct === '成長' && f7.px > 0 && f7.title === '＋ 買った株を記録', `⑦ MSFT: 株の欄・口座「${f7.acct}」・単価 ${f7.px}・見出し「${f7.title}」`);
  const ms0 = (await row('MSFT')).sh;
  await fill({ trS: 1 }); await go('buy');
  const ms1 = await row('MSFT');
  ok(ms1.sh === ms0 + 1 && ms1.ccy === 'USD' && ms1.sleeve === 'castle', `⑦ MSFT +1株（${ms0}→${ms1.sh}・${ms1.ccy}・${ms1.sleeve}）`);
  // 口座を人が選び直したら、銘柄を替えても上書きしない
  await open('buy'); await pick('MSFT');
  await pg.evaluate(() => { const a = document.getElementById('trA'); a.value = '特定'; a.dispatchEvent(new Event('change')); });
  await pick(FKEY);
  ok((await pg.evaluate(() => document.getElementById('trA').value)) === '特定', '⑦ 人が選んだ口座は銘柄を替えても残る');

  // ── ⑧ 旧の罠（個別株・ドル建ての行）
  await seed(`return ps.concat([{t:'${FKEY}',nm:'${FKEY}',sleeve:'castle',kind:'個別',ccy:'USD',sh:10,bpx:5,npx:5,v:0}]);`);
  await open('buy'); await pick(FKEY);
  await fill({ trFJ: 30000 }); await go('buy');
  const m8 = await msg(), r8 = await row(FKEY);
  ok(/個別株・ドル建て/.test(m8) && r8.sh === 10, `⑧ 足さずに直し方を言う（${m8.slice(0, 70)}…）・行は ${r8.sh}口のまま`);

  // ── ⑨ 買付順位の「＋円」で作った行
  /* 台帳が空だと買付順位は ETF の行を描かない早い道を通るので、全パックを取り込んでから（check_fund_cap と同じ） */
  await seed();
  await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1800);
  await pg.evaluate(() => { localStorage.setItem('pf:monthly_total', '170000'); showPage(5); });
  await pg.waitForTimeout(3200);
  const got9 = await pg.evaluate(async t => {
    const w = [...document.querySelectorAll('#pg5 .bctl')].find(x => x.dataset.t === t && x.dataset.fund === '1');
    if (!w) return { err: '＋円 が見つからない' };
    w.querySelector('button').click();
    await new Promise(r => setTimeout(r, 150));
    const i = w.querySelector('input'); i.value = '30000';
    w.querySelector('button').click();
    await new Promise(r => setTimeout(r, 1500));
    return { ok: true };
  }, FKEY);
  const r9 = await row(FKEY);
  ok(!got9.err && !!r9 && r9.kind === '投資信託' && r9.sleeve === 'net' && r9.ccy === 'JPY' && r9.bjpy === 30000 && r9.sh === Math.floor(30000 / (+DQ.px)),
     `⑨ 「＋円」の行: ${got9.err || (r9 ? r9.kind + '・' + r9.sleeve + '・' + r9.ccy + '・' + r9.sh + '口・¥' + r9.bjpy : 'なし')}`);
  // ★約定日（今日）も入る（2026-10-05）——日付の無い買付は📈成績が S&P500 と同じ日で比べられず外していた
  const today9 = await pg.evaluate(() => ccfTradeToday());
  const lot9 = r9 && (r9.bdLots || [])[0];
  ok(!!r9 && r9.bd === today9 && !!lot9 && lot9.bd === today9 && lot9.jpy === 30000,
     `⑨ 「＋円」の記録に約定日（今日 ${today9}）: 行 ${r9 && r9.bd}・ロット ${lot9 && lot9.bd}`);
  // 旧の「＋円」で作った行（種類 ETF）に 🏦保有 から足すと種類が直る
  await seed(`return ps.concat([{t:'${FKEY}',nm:'${FUND.name}',sleeve:'net',kind:'ETF',ccy:'JPY',sh:5000,bpx:${UPX},npx:${UPX},bjpy:28754,v:0}]);`);
  await open('buy'); await pick(FKEY);
  ok((await vis('tr-fnd')).every(Boolean), '⑨ 旧の行（種類 ETF・円）も投資信託として選べる（ami_funds にある本）');
  await fill({ trFJ: 10000 }); await go('buy');
  const r9b = await row(FKEY);
  ok(r9b.kind === '投資信託' && r9b.sh === 5000 + Math.floor(10000 / UPX) && r9b.bjpy === 38754, `⑨ 足すと種類が「投資信託」に直る（${r9b.kind}・${r9b.sh}口・¥${r9b.bjpy}）`);

  // ── ⑬ iDeCo の本（v9.9.202）: 口座の既定が iDeCo・ロットに口座 iDeCo が残る
  const IK = Object.keys(PJ.target.ami_funds || {}).find(k => (PJ.target.ami_funds[k] || {}).account === 'iDeCo');
  if (!IK) ok(true, '⑬ iDeCo の本が ami_funds に無い（検査を飛ばす）');
  else {
    await seed(); await open('buy'); await pick(IK);
    const f13 = await pg.evaluate(() => ({ acct: document.getElementById('trA').value, opts: [...document.getElementById('trA').options].map(o => o.value) }));
    ok(f13.acct === 'iDeCo' && f13.opts.includes('iDeCo'), `⑬ ${IK} を選ぶと口座の既定が iDeCo（${f13.opts.join('/')}）`);
    const nav13 = await pg.evaluate(() => +document.getElementById('trFN').value || 0);
    await fill(Object.assign({ trFJ: 20000 }, nav13 > 0 ? {} : { trFN: 41234 }));
    await go('buy');
    const r13 = await row(IK), l13 = r13 && (r13.bdLots || [])[0];
    ok(!!r13 && r13.kind === '投資信託' && r13.sleeve === 'net' && !!l13 && l13.acct === 'iDeCo' && l13.jpy === 20000,
       `⑬ 記録: ${r13 ? r13.kind + '・' + r13.sleeve + '・' + r13.sh + '口' : 'なし'}・ロット ${l13 ? l13.acct + ' ¥' + l13.jpy : 'なし'}（基準価額 ${nav13 > 0 ? '盤 ' + nav13 : '手入力 41234'}）`);
    await open('buy'); await pick(FKEY);
    ok(await pg.evaluate(() => document.getElementById('trA').value) === 'つみたて', `⑬ ${FKEY} は従来どおりつみたて投資枠`);
  }

  // ── ⑭ こどもNISA（2026-10-08 ユーザー明示指示「比率に数えて」）: 記録しそびれた月を 🏦保有 から手で入れられる
  const KO = PJ.target.kodomo_nisa || null, KW = KO && KO.bucket ? ((KO.members || []).find(m => +m.jpy > 0) || {}).who : '';
  if (!KW) ok(true, '⑭ target.kodomo_nisa に bucket か名義が無い（検査を飛ばす）');
  else {
    await seed(); await open('buy'); await pick(FKEY); await pg.waitForTimeout(400);
    const f14 = await pg.evaluate(() => ({ accts: [...document.getElementById('trA').options].map(o => o.value), whos: [...document.getElementById('trW').options].map(o => o.value) }));
    ok(f14.accts.includes('こどもNISA') && f14.whos.includes(KW), `⑭ 口座に「こどもNISA」（${f14.accts.join('/')}）・名義に「${KW}」（${f14.whos.join('/')}）`);
    await pg.evaluate(w => { const a = document.getElementById('trA'); a.value = 'こどもNISA'; a.dispatchEvent(new Event('change'));
      document.getElementById('trW').value = w; }, KW);
    await fill({ trFJ: 30000 }); await go('buy');
    const r14 = await row(FKEY), l14 = r14 && (r14.bdLots || []).slice(-1)[0];
    ok(!!l14 && l14.acct === 'こどもNISA' && l14.who === KW && l14.jpy === 30000 && r14.kind === '投資信託',
       `⑭ 記録: ロット ${l14 ? l14.acct + '・' + l14.who + '・¥' + l14.jpy + '・' + l14.sh + '口' : 'なし'}`);
  }

  // ── ⑪ 携帯の幅
  for (const w of [320, 360, 390]) {
    await pg.setViewportSize({ width: w, height: 900 });
    await open('buy'); await pick(FKEY); await pg.waitForTimeout(200);
    const o = await pg.evaluate(() => { const bx = document.getElementById('tradeBox');
      const r = bx.getBoundingClientRect(); const de = document.documentElement;
      const wide = [...bx.querySelectorAll('input,select,button')].filter(e => getComputedStyle(e).display !== 'none' && e.offsetParent && e.getBoundingClientRect().right > de.clientWidth + 1).length;
      return { over: de.scrollWidth > de.clientWidth + 1, right: r.right, cw: de.clientWidth, wide }; });
    ok(!o.over && o.wide === 0, `⑪ ${w}px: はみ出し ${o.over ? 'あり' : 'なし'}・枠の外の部品 ${o.wide}`);
  }

  ok(errs.length === 0, `⑫ pageerror ${errs.length}件${errs.length ? '：' + errs.slice(0, 3).join(' | ') : ''}`);
  await b.close(); srv.close();
  console.log(ng ? `\n✗ ${ng}項目が落ちた` : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
