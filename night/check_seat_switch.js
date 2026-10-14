#!/usr/bin/env node
/* night/check_seat_switch.js — 門の席が入れ替わったとき、端末の台帳が repo に追いつき、持っている社は売らずに引き継ぐかを実ブラウザで確かめる（v9.9.219）
 *
 * ■ なぜ要るか（2026-10-14 ユーザー「購入した個別銘柄で入れ替わった場合は売却せず引き継ぐ形にしたい。それと門の個別銘柄が入れ替わった場合は
 *   きちんと入れ替わるようになってる？」）
 *   席（🟢投下可）は端末の台帳（localStorage の g7:）から描くたびに計算する。ところが台帳そのものは「⭳ 全パック一括取込」を押すまで古いまま
 *   ——repo のパックが新しくなっても（審査のやり直し・毎営業日の株価）、採点の式が変わっても、端末の席は前のままで、知らせる印も無かった。
 *   v9.9.219 で、開いたときに台帳を repo に追いつかせる（ccfAutoRefresh）。この検査はそれを外から確かめる。
 *
 * ■ 判定
 *   ① 新しい端末（台帳が空）→ 自動取込の記録に印（pfx＝索引の指紋・sv＝採点の式の指紋）。開き直しても何も取り込まない
 *   ② repo のパックが新しくなる（MSFT にキル・KLAC の irr 70→85）→ 開くと2社だけ取り込み直し、席が入れ替わる
 *      → 🛒買付順位の帯「入 KLAC・出 MSFT（売らずに引き継ぐ）」・注文書の「引き継ぎ」・目標ポートフォリオの「引き継ぎ」・📋今日の知らせ
 *      → 「✓ 確認した」で帯と知らせが消える・検証履歴に1件・赤い帯（未書き出し）は立たない
 *   ③ 人が直した記録（✎採点機で記録）は、パックが新しくなっても置き換えない → 帯で名指し → 押せば置き換わる
 *   ④ 台帳から消した社は、開いたときの自動の取り込みで戻さない → 「⭳ いま取り込む」で戻る
 *   ⑤ 採点の式が変わる（門の index.html の本文が変わる）→ 開くと全社を再採点（パックは取りに行かない・data は変えない）
 *   ⑥ 印の無い古い記録（v9.9.218 までに取り込んだ記録）→ 一度だけ全部を取り込み直す（かかった時間を出す）
 *   ⑦ 'ccf:autoRefresh'='off' → 何もしない
 *
 * playwright が要るので CI には入れていない（check_auto_import.js と同じ扱い）。
 *   使い方: NODE_PATH=$(npm root -g) node night/check_seat_switch.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const ROOT = path.dirname(__dirname), PORT = 8801;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const TYPES = { '.js': 'text/javascript', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.css': 'text/css' };

// ── 検査の中だけの repo（パック・索引・今日の集計・門の本文を差し替える）──
const OVR = {};               // 'MSFT_gate_pack.json' → Buffer（実ファイルの代わりに配る）
let TODAY_BUY = null;         // out/today.json の buy を差し替える
let SIG_MARK = '';            // 門の本文（メインのスクリプト）に1行の注記を足す＝採点の式の指紋が変わる
const fetched = {};           // パックの取得回数（ファイル名ごと）
const sha12 = b => crypto.createHash('sha1').update(b).digest('hex').slice(0, 12);
const packBuf = f => OVR[f] || fs.readFileSync(path.join(ROOT, 'out', f));
const modPack = (t, fn) => { const f = t + '_gate_pack.json'; const d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); fn(d); OVR[f] = Buffer.from(JSON.stringify(d, null, 1)); return f; };
const indexBuf = () => { const ij = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/packs_index.json'), 'utf8')); ij.fp = ij.fp || {};
  for (const f of Object.keys(OVR)) ij.fp[f] = sha12(OVR[f]); return Buffer.from(JSON.stringify(ij)); };
const srv = http.createServer((q, r) => {
  let rel = decodeURIComponent(q.url.split('?')[0]); if (rel.endsWith('/')) rel += 'index.html';
  const f = path.join(ROOT, rel), base = path.basename(rel);
  const send = (b, ct) => { r.writeHead(200, { 'Content-Type': ct || TYPES[path.extname(f)] || 'text/html' }); r.end(b); };
  try {
    if (rel === '/out/packs_index.json') return send(indexBuf(), 'application/json');
    if (/_gate_pack\.json$/.test(base)) { fetched[base] = (fetched[base] || 0) + 1; return send(packBuf(base), 'application/json'); }
    if (rel === '/out/today.json' && TODAY_BUY) { const j = JSON.parse(fs.readFileSync(f, 'utf8')); j.buy = TODAY_BUY.slice(); return send(Buffer.from(JSON.stringify(j)), 'application/json'); }
    if (rel === '/index.html' && SIG_MARK) { const h = fs.readFileSync(f, 'utf8').replace('const $=id=>document.getElementById(id);', 'const $=id=>document.getElementById(id);// ' + SIG_MARK); return send(Buffer.from(h), 'text/html'); }
    send(fs.readFileSync(f));
  } catch (e) { r.writeHead(404); r.end('x'); }
});
const nFetched = () => Object.values(fetched).reduce((a, b) => a + b, 0);
const resetFetched = () => { for (const k of Object.keys(fetched)) delete fetched[k]; };

let ng = 0;
const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const b = await chromium.launch({ executablePath: CHROME });
  const URL = 'http://localhost:' + PORT + '/index.html';
  const IDX = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/packs_index.json'), 'utf8'));
  const N = (IDX.packs || []).length;
  const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  const waitAuto = async () => { for (let i = 0; i < 150; i++) { const st = await pg.evaluate(() => window.__ccfAutoImp); if (st === 'done' || st === 'fail') return st; await pg.waitForTimeout(1000); } return 'timeout'; };
  // 開いたときの追いつき（ccfAutoRefresh）が終わるまで待つ。null のまま（走らなかった）も返す
  const waitRefresh = async (ms) => { const t0 = Date.now(); for (let i = 0; i < (ms || 180000) / 500; i++) {
      const x = await pg.evaluate(() => { const r = window.__ccfRefresh; return r ? { running: !!r.running, at: r.at || 0 } : null; });
      if (x && !x.running && x.at) break; await pg.waitForTimeout(500); }
    return { r: await pg.evaluate(() => window.__ccfRefresh), ms: Date.now() - t0 }; };
  const recOf = t => pg.evaluate(t => { const k = Object.keys(localStorage).find(k => k.indexOf('g7:') === 0 && k.slice(3).split(/[\s_]/)[0].toUpperCase() === t);
    return k ? Object.assign({ __k: k }, JSON.parse(localStorage.getItem(k))) : null; }, t);
  const ledgerN = () => pg.evaluate(() => Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length);
  const clickYes = async () => { for (let i = 0; i < 20; i++) { const h = await pg.$('[data-uic="yes"]'); if (h) { await h.click(); return true; } await pg.waitForTimeout(200); } return false; };
  console.log('■ 席の入れ替わりと台帳の追いつき（night/check_seat_switch.js）');

  // ① 新しい端末 → 自動取込の記録に印。開き直しても何も取り込まない
  await pg.goto(URL);
  const st0 = await waitAuto(); await pg.waitForTimeout(1500);
  const stamp = await pg.evaluate(fp => { const sig = ccfScoreSig(); let n = 0, pfxOk = 0, svOk = 0, src = 0;
    for (const k of Object.keys(localStorage)) { if (k.indexOf('g7:') !== 0) continue; const o = JSON.parse(localStorage.getItem(k)); n++;
      const t = k.slice(3).split(/[\s_]/)[0]; if (o.pfx && o.pfx === fp[t + '_gate_pack.json']) pfxOk++; if (o.sv === sig) svOk++; if (o.src === 'JSON取込') src++; }
    return { n, pfxOk, svOk, src, sig }; }, IDX.fp || {});
  ok(st0 === 'done' && stamp.n === N && stamp.pfxOk === N && stamp.svOk === N && stamp.src === N && !!stamp.sig,
    `① 自動取込の記録 ${stamp.n}/${N}社に印（パックの指紋 ${stamp.pfxOk}・採点の式の指紋 ${stamp.svOk}〔${stamp.sig}〕・src 'JSON取込' ${stamp.src}）`);
  resetFetched();
  await pg.reload(); const w1 = await waitRefresh(60000);
  ok(w1.r && w1.r.imp === 0 && w1.r.rs === 0 && nFetched() === 0, `   開き直すと追いつきは走るが、取り込むものは無い（取得 ${nFetched()}件・${JSON.stringify(w1.r && { imp: w1.r.imp, rs: w1.r.rs })}）`);
  await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
  const s1 = await pg.evaluate(() => ({ buy: window.__ccfBuyList || [], ack: JSON.parse(localStorage.getItem('ccf:seats') || 'null'), ban: !!document.querySelector('.seat-change') }));
  ok(s1.buy.length > 0 && s1.ack && JSON.stringify(s1.ack.seats.slice().sort()) === JSON.stringify(s1.buy.slice().sort()) && !s1.ban,
    `   初めて🛒買付順位を見たときは席を黙って覚える（${s1.buy.join('・')}・帯は出さない）`);
  const held0 = await pg.evaluate(() => { const P = JSON.parse(localStorage.getItem('pf:portfolio') || '{}'); return (P.positions || []).filter(p => p.sleeve === 'castle' && +p.sh > 0).map(p => String(p.t).toUpperCase()); });
  ok(held0.includes('MSFT') && s1.buy.includes('MSFT') && !s1.buy.includes('KLAC'), `   前提: MSFT は持っていて席にいる・KLAC は席の外（持っている個別株 ${held0.join('・')}）`);

  // ② repo のパックが新しくなる → 2社だけ取り込み直し・席が入れ替わる・MSFT は売らずに引き継ぐ
  const fM = modPack('MSFT', d => { d.eq = 'neg'; }), fK = modPack('KLAC', d => { d.irr = 85; });
  TODAY_BUY = s1.buy.filter(t => t !== 'MSFT').concat(['KLAC']);
  resetFetched();
  await pg.reload(); const w2 = await waitRefresh(90000); await pg.waitForTimeout(2500);
  const r2 = w2.r || {};
  ok(nFetched() === 2 && fetched[fM] === 1 && fetched[fK] === 1 && r2.impOld === 2 && r2.impNew === 0,
    `② パックが新しくなった2社だけを取り込み直す（取得 ${JSON.stringify(fetched)}・新しくなった ${r2.impOld}社・${Math.round(w2.ms / 100) / 10}秒）`);
  const recM = await recOf('MSFT'), recK = await recOf('KLAC');
  ok(recM && recM.data.eq === 'neg' && recM.pfx === sha12(OVR[fM]) && recK && String(recK.data.irr) === '85' && recK.pfx === sha12(OVR[fK]),
    '   台帳の記録が新しいパックの数字と指紋になる（MSFT eq=neg・KLAC irr=85）');
  const today2 = await pg.evaluate(() => (document.getElementById('pg10') || {}).innerText || '');
  ok(/門の席が入れ替わりました/.test(today2) && /入 KLAC/.test(today2) && /出 MSFT/.test(today2) && /売らずに引き継ぐ/.test(today2),
    '   📋今日: 「門の席が入れ替わりました：入 KLAC　出 MSFT」・出た社は売らずに引き継ぐ');
  await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(3000);
  const p2 = await pg.evaluate(() => { const ban = document.querySelector('.seat-change'), cy = document.querySelector('.carry-row');
    return { buy: window.__ccfBuyList || [], ban: ban ? ban.innerText : '', carry: cy ? cy.innerText : '', diff: window.__ccfSeatDiff,
      order: /📋 今月の注文書/.test((document.getElementById('planBox') || {}).innerText || '') }; });
  ok(!p2.buy.includes('MSFT') && p2.buy.includes('KLAC'), `   🛒買付順位の席が入れ替わる（${p2.buy.join('・')}）`);
  ok(/門の席が入れ替わりました/.test(p2.ban) && /入 KLAC/.test(p2.ban) && /出 MSFT（保有 [\d.]+%→売らずに引き継ぐ）/.test(p2.ban) && /S1\/S2\/S3/.test(p2.ban),
    '   帯「入 KLAC・出 MSFT（保有 x%→売らずに引き継ぐ）」・売りは S1/S2/S3 だけ');
  ok(p2.order && /引き継ぎ/.test(p2.carry) && /MSFT [\d.]+%/.test(p2.carry) && /売らずに持ち続ける/.test(p2.carry) && !/¥/.test(p2.carry),
    `   注文書の個別株の節に「↪ 引き継ぎ（席の外・売らずに持ち続ける）：MSFT x%」（金額は出さない）`);
  await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(3000);
  const pft = await pg.evaluate(() => { const e = document.querySelector('#pftCard [data-k="c:MSFT"]'); return e ? e.innerText : ''; });
  ok(/引き継ぎ/.test(pft) && !/多い/.test(pft), `   目標ポートフォリオの MSFT の行は「引き継ぎ」（「多い」と言わない・${pft.replace(/\s+/g, ' ').slice(0, 60)}）`);
  const misc2 = await pg.evaluate(() => ({ logs: Object.keys(localStorage).filter(k => k.indexOf('g7log:') === 0).map(k => JSON.parse(localStorage.getItem(k))),
    dirty: (window.ccfState && ccfState.isDirty) ? ccfState.isDirty() : null }));
  const lg = misc2.logs.filter(x => /開いたときの自動の追いつき/.test(x.title));
  ok(lg.length === 1 && /MSFT/.test(lg[0].body) && /KLAC/.test(lg[0].body), `   検証履歴に1件（${lg[0] ? lg[0].title.slice(0, 60) : '—'}）`);
  ok(misc2.dirty === false, '   赤い帯（未書き出し）は立たない（台帳・検証履歴・席の印は人の決定ではない）');
  await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
  // 幅320px（いちばん狭い携帯）でも、帯と引き継ぎの行が横にはみ出さない
  await pg.setViewportSize({ width: 320, height: 760 }); await pg.evaluate(() => renderPlan()); await pg.waitForTimeout(1500);
  const fit = await pg.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
    ban: !!document.querySelector('.seat-change'), cy: !!document.querySelector('.carry-row'),
    wide: [...document.querySelectorAll('.seat-change, .carry-row')].map(e => Math.round(e.getBoundingClientRect().right)) }));
  ok(fit.ban && fit.cy && fit.sw <= fit.cw && fit.wide.every(x => x <= fit.cw), `   幅320px でも帯と引き継ぎの行がはみ出さない（scroll ${fit.sw} / client ${fit.cw}・右端 ${fit.wide.join('/')}）`);
  await pg.setViewportSize({ width: 390, height: 844 }); await pg.evaluate(() => renderPlan()); await pg.waitForTimeout(1200);
  await pg.evaluate(() => { const bt = document.querySelector('.seat-change button'); bt && bt.click(); });
  await pg.waitForTimeout(800);
  const ack2 = await pg.evaluate(() => ({ ack: JSON.parse(localStorage.getItem('ccf:seats') || 'null'), ban: !!document.querySelector('.seat-change') }));
  ok(ack2.ack && !ack2.ban && ack2.ack.seats.includes('KLAC') && !ack2.ack.seats.includes('MSFT'), '   「✓ 確認した」で帯が消え、今の席を覚える');
  await pg.evaluate(() => showPage(10)); await pg.waitForTimeout(2000);
  const today2b = await pg.evaluate(() => (document.getElementById('pg10') || {}).innerText || '');
  ok(!/門の席が入れ替わりました/.test(today2b), '   📋今日の知らせも消える（今日の集計と覚えた席が同じ）');
  resetFetched();
  await pg.reload(); await waitRefresh(60000); await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
  ok(nFetched() === 0 && !(await pg.$('.seat-change')), `   開き直しても取り込まない・帯は出ない（取得 ${nFetched()}件）`);

  // ③ 人が直した記録は置き換えない → 帯で名指し → 押せば置き換わる
  const fpI0 = (IDX.fp || {})['IDXX_gate_pack.json'];
  await pg.evaluate(fp => { const k = Object.keys(localStorage).find(k => k.indexOf('g7:IDXX') === 0); const o = JSON.parse(localStorage.getItem(k));
    o.src = 'manual'; o.pfxBase = fp; delete o.pfx; o.__probe = 'human'; localStorage.setItem(k, JSON.stringify(o)); }, fpI0);
  const fI = modPack('IDXX', d => { d.memo = (d.memo || '') + ' （検査: パックの更新）'; });
  resetFetched();
  await pg.reload(); const w3 = await waitRefresh(60000); await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
  const recI = await recOf('IDXX');
  const bar3 = await pg.evaluate(() => { const e = document.getElementById('packFreshBar5'); return { shown: getComputedStyle(e).display !== 'none', t: e.innerText }; });
  ok(!fetched[fI] && recI && recI.__probe === 'human' && recI.src === 'manual' && (w3.r.keep || []).some(x => x.t === 'IDXX' && !x.unk),
    `③ ✎採点機で直した記録はパックが新しくなっても置き換えない（取得 ${fetched[fI] || 0}件・記録の印 ${recI && recI.__probe}）`);
  ok(bar3.shown && /人が直した記録 1社/.test(bar3.t) && /IDXX/.test(bar3.t) && /パックで置き換える/.test(bar3.t) && /パックのほうが新しくなった社/.test(bar3.t),
    '   🛒買付順位の帯で名指し（「人が直した記録 1社…IDXX」・「⭳ パックで置き換える」）');
  await pg.evaluate(() => { const bt = [...document.querySelectorAll('#packFreshBar5 button')].find(x => /置き換える/.test(x.textContent)); bt && bt.click(); });
  ok(await clickYes(), '   押すと確かめる（置き換えるかは人が決める）');
  for (let i = 0; i < 60; i++) { await pg.waitForTimeout(500); const r = await recOf('IDXX'); if (r && !r.__probe) break; }
  await waitRefresh(30000); await pg.waitForTimeout(1500);
  const recI2 = await recOf('IDXX');
  const bar3b = await pg.evaluate(() => getComputedStyle(document.getElementById('packFreshBar5')).display);
  ok(recI2 && !recI2.__probe && recI2.src === 'JSON取込' && recI2.pfx === sha12(OVR[fI]) && bar3b === 'none',
    '   置き換えると repo の記録になり（src JSON取込・新しい指紋）、帯は消える');

  // ④ 台帳から消した社は、開いたときの自動の取り込みで戻さない → 「⭳ いま取り込む」で戻る
  const kA = (await recOf('ADBE') || {}).__k;
  await pg.evaluate(k => { delIt(k); }, kA); ok(await clickYes(), '④ 📚台帳の削除（ADBE）');
  await pg.waitForTimeout(1000);
  const na = await pg.evaluate(() => JSON.parse(localStorage.getItem('ccf:noAuto') || '[]'));
  resetFetched();
  await pg.reload(); const w4 = await waitRefresh(60000); await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
  const bar4 = await pg.evaluate(() => (document.getElementById('packFreshBar5') || {}).innerText || '');
  ok(na.includes('ADBE') && !fetched['ADBE_gate_pack.json'] && !(await recOf('ADBE')) && (await ledgerN()) === N - 1,
    `   開いても戻さない（印 ccf:noAuto ${JSON.stringify(na)}・取得 ${fetched['ADBE_gate_pack.json'] || 0}件・台帳 ${await ledgerN()}社）`);
  ok(/台帳に入っていないパックが 1社/.test(bar4) && /台帳から消した社（ADBE）/.test(bar4) && /いま取り込む/.test(bar4), '   帯は「台帳から消した社（ADBE）は戻さない」と言い、「⭳ いま取り込む」を出す');
  await pg.evaluate(() => { const bt = [...document.querySelectorAll('#packFreshBar5 button')].find(x => /いま取り込む/.test(x.textContent)); bt && bt.click(); });
  for (let i = 0; i < 180; i++) { await pg.waitForTimeout(1000); if ((await ledgerN()) >= N && !(await pg.evaluate(() => window.__ccfImpRun))) break; }
  await pg.waitForTimeout(1500);
  const na2 = await pg.evaluate(() => localStorage.getItem('ccf:noAuto'));
  ok((await ledgerN()) === N && !!(await recOf('ADBE')) && na2 === null, '   人が「⭳ いま取り込む」を押すと全部を取り込み、消した印も消える');

  // ⑤ 採点の式が変わる（門の本文が変わる）→ 全社を再採点（パックは取りに行かない・data は変えない）
  const dataBefore = await pg.evaluate(() => { const o = {}; for (const k of Object.keys(localStorage)) if (k.indexOf('g7:') === 0) o[k] = JSON.stringify(JSON.parse(localStorage.getItem(k)).data); return o; });
  SIG_MARK = 'sig-test-' + Date.now(); resetFetched();
  await pg.reload(); const w5 = await waitRefresh(240000); await pg.waitForTimeout(1500);
  const after5 = await pg.evaluate(() => { const sig = ccfScoreSig(); let n = 0, sv = 0; const d = {};
    for (const k of Object.keys(localStorage)) if (k.indexOf('g7:') === 0) { const o = JSON.parse(localStorage.getItem(k)); n++; if (o.sv === sig) sv++; d[k] = JSON.stringify(o.data); }
    return { sig, n, sv, d }; });
  const dataSame = Object.keys(dataBefore).filter(k => dataBefore[k] !== after5.d[k]);
  ok(w5.r && w5.r.rs === N && nFetched() === 0 && after5.sv === N && after5.sig !== stamp.sig,
    `⑤ 門の本文が変わると全社を再採点（再採点 ${w5.r && w5.r.rs}件・パックの取得 ${nFetched()}件・${Math.round(w5.ms / 100) / 10}秒）`);
  ok(dataSame.length === 0, `   data は1社も変えない（違った ${dataSame.length}社）`);
  SIG_MARK = ''; await pg.reload(); await waitRefresh(240000);

  // ⑥ 印の無い古い記録（v9.9.218 までに取り込んだ記録）→ 一度だけ全部を取り込み直す
  await pg.evaluate(() => { for (const k of Object.keys(localStorage)) if (k.indexOf('g7:') === 0) { const o = JSON.parse(localStorage.getItem(k)); delete o.pfx; delete o.sv; localStorage.setItem(k, JSON.stringify(o)); } });
  resetFetched();
  await pg.reload(); const w6 = await waitRefresh(300000);
  ok(w6.r && w6.r.impOld === N && nFetched() === N && (await ledgerN()) === N,
    `⑥ 印の無い古い記録は一度だけ全部を取り込み直す（${w6.r && w6.r.impOld}社・取得 ${nFetched()}件・${Math.round(w6.ms / 1000)}秒）`);
  resetFetched(); await pg.reload(); const w6b = await waitRefresh(60000);
  ok(nFetched() === 0 && w6b.r && w6b.r.imp === 0 && w6b.r.rs === 0, '   次に開いたときは何も取り込まない');

  // ⑦ 'ccf:autoRefresh'='off' → 何もしない
  await pg.evaluate(() => localStorage.setItem('ccf:autoRefresh', 'off'));
  modPack('CW', d => { d.memo = (d.memo || '') + ' （検査: off）'; }); resetFetched();
  await pg.reload(); await pg.waitForTimeout(5000);
  ok(nFetched() === 0 && (await pg.evaluate(() => window.__ccfRefresh)) === null, `⑦ 'ccf:autoRefresh'='off' なら追いつきは走らない（取得 ${nFetched()}件）`);
  await pg.evaluate(() => localStorage.removeItem('ccf:autoRefresh'));

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 160) + '）' : ''));
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
