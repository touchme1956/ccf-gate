#!/usr/bin/env node
/* night/check_auto_import.js — 台帳が空の端末で🛒買付順位が空にならないかを実ブラウザで確かめる（v9.9.218）
 *
 * ■ なぜ要るか（実害から作った検査）
 *   2026-10-12、ユーザー「全然買付順位に出ない」。ホーム画面のアプリ（v9.9.216）は Safari と保存場所（localStorage）が別で、
 *   初めて開くと台帳(g7:)が0件＝🛒買付順位が「🟢投下可なし」だけになり、注文書も出なかった。
 *   未取込の案内は📚台帳のタブにしか無く、買付順位だけ見る人には理由が分からなかった。
 *
 * ■ 判定
 *   ① 台帳が空 → 起動時に全パックを自動で取り込む（ページは移動しない・取り込み中は買付順位に進み具合）
 *      → 終わると買付順位に注文書が出る・赤い帯（未書き出し）は立たない・検証履歴に「自動取込」
 *   ② 自動取込の最中に「⭳ 全パック一括取込」を押す → 2本目は始めずに待つ（パックの取得は1回）
 *      → 台帳の各社がパックの数字のまま（取り込みが重なって別の社の数字で保存されていない）
 *   ③ 台帳がパックの半分以上あり印も無い → 自動では取り込まない（人が直した値を巻き戻さない）・未取込の帯を🛒買付順位にも出す
 *      → 買付順位の帯から押した取り込みはページを移動しない
 *   ④ 自動取込が途中で終わった（印 ccf:autoImp が残る）→ 次に開くと台帳にまだ無い社だけを取り込む
 *      → 取得は無かった社の数だけ・既にあったレコードは置き換えない・終わると印は消える（2026-10-13 ユーザー「投下可がなしになってるから直して」）
 *   ⑤ 印が3回目まで残る → 続きはせず印を消し、🛒買付順位の帯で知らせる
 *   ⑥ 取り込み中の🏦保有・📋今日・今月の買付プラン・目標ポートフォリオのカード → 「投下可なし」とだけ言わず理由と進み具合
 *      → 台帳が半分の間も席を計算しない（席が欠けた注文書や「投下可なし」を出さない）
 *   ⑦ 印は無いが台帳がパックの半分に届かない → 台帳にまだ無い社だけを続きから（置き換えない）
 *   ⑤の続き: 台帳に入っていないパックがあれば🏦保有の投下可の下にも注記と「⭳ いま取り込む」
 *
 * playwright が要るので CI には入れていない（check_stale_bar.js / check_state_banner.js と同じ扱い）。
 *   使い方: NODE_PATH=$(npm root -g) node night/check_auto_import.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8799;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const TYPES = { '.js': 'text/javascript', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.css': 'text/css' };

let PACK_DELAY = 0, packFetches = 0;          // パックの取得を遅らせて「取り込み中」の表示を読む・取得の回数を数える
const srv = http.createServer((q, r) => {
  let f = path.join(ROOT, decodeURIComponent(q.url.split('?')[0]));
  if (f.endsWith('/')) f += 'index.html';
  const isPack = /_gate_pack\.json$/.test(f);
  if (isPack) packFetches++;
  const send = () => {
    try { const b = fs.readFileSync(f); r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'text/html' }); r.end(b); }
    catch (e) { r.writeHead(404); r.end('x'); }
  };
  if (isPack && PACK_DELAY) setTimeout(send, PACK_DELAY); else send();
});

let ng = 0;
const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const b = await chromium.launch({ executablePath: CHROME });
  const URL = 'http://localhost:' + PORT + '/index.html';
  const IDX = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/packs_index.json'), 'utf8')).packs || [];
  const N = IDX.length;
  const waitAuto = async pg => {
    for (let i = 0; i < 120; i++) {
      const st = await pg.evaluate(() => window.__ccfAutoImp);
      if (st === 'done' || st === 'fail') return st;
      await pg.waitForTimeout(1000);
    }
    return 'timeout';
  };
  const ledgerN = pg => pg.evaluate(() => Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length);
  console.log('■ 台帳が空の端末の自動取込（night/check_auto_import.js）');

  // ① 台帳が空 → 自動で取り込む
  {
    const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 30; packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(1500);
    const startPage = await pg.evaluate(() => window.__ccfPage);
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(1200);
    const mid = await pg.evaluate(() => ({ ai: window.__ccfAutoImp, pb: (document.getElementById('planBox') || {}).innerText || '',
      bar5: (document.getElementById('packFreshBar5') || {}).innerText || '' }));
    ok(mid.ai && typeof mid.ai === 'object', '① 台帳が空 → 起動時に自動取込が始まる（' + JSON.stringify(mid.ai) + '）');
    ok((/台帳がまだ空です/.test(mid.pb) && /自動で取り込んでいます/.test(mid.pb)) || /取り込んでいる途中です/.test(mid.pb), '   取り込み中の🛒買付順位は理由と進み具合を出す（「投下可なし」だけにしない）');
    ok(/自動で取り込んでいます/.test(mid.bar5) && !/いま取り込む/.test(mid.bar5), '   🛒買付順位の帯も「取り込み中」（押すボタンは出さない）');
    const st = await waitAuto(pg);
    await pg.waitForTimeout(2500);
    const after = await pg.evaluate(() => {
      const t = (document.querySelector('#pg5') || {}).innerText || '';
      const sb = document.getElementById('stateBar');
      return { page: window.__ccfPage, order: /📋 今月の注文書/.test(t), empty: /台帳が空/.test(t),
        dirty: (window.ccfState && ccfState.isDirty) ? ccfState.isDirty() : null,
        sb: sb ? (sb.innerText || '').trim() : '',
        bar5: getComputedStyle(document.getElementById('packFreshBar5')).display,
        logs: Object.keys(localStorage).filter(k => k.indexOf('g7log:') === 0).map(k => JSON.parse(localStorage.getItem(k)).title) };
    });
    const n = await ledgerN(pg);
    ok(st === 'done' && n === N, '   取り込み終了 ' + st + '・台帳 ' + n + '/' + N + '社');
    ok(startPage === 10 && after.page === 5, '   ページは移動しない（起動 ' + startPage + '・人が開いた 5 のまま → ' + after.page + '）');
    ok(after.order && !after.empty, '   終わると🛒買付順位に今月の注文書が出る（作り直しは自動）');
    ok(after.bar5 === 'none', '   未取込の帯は消える');
    ok(after.dirty === false && !/書き出/.test(after.sb), '   赤い帯（未書き出し）は立たない（台帳と検証履歴は人の決定ではない）');
    ok(after.logs.length === 1 && /自動取込（台帳が空だった）/.test(after.logs[0]), '   検証履歴に「自動取込（台帳が空だった）」が1件');
    ok(packFetches === N, '   パックの取得は ' + packFetches + ' 件（各1回）');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  // ② 自動取込の最中に一括取込を押す → 待つだけ・台帳は各社のパックの数字のまま
  {
    const pg = await (await b.newContext()).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 0; packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(2500);
    const mid = await pg.evaluate(() => window.__ccfAutoImp);
    await pg.evaluate(() => ccfImportAllPacks());      // 人が📚台帳の「⭳ 全パック一括取込」を押したのと同じ
    const st = await waitAuto(pg);
    await pg.waitForTimeout(1500);
    const recs = await pg.evaluate(() => {
      const o = {};
      for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.indexOf('g7:') === 0) o[k] = JSON.parse(localStorage.getItem(k)); }
      return o;
    });
    const packByNm = {};
    for (const f of IDX) { const p = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); const d = p.data || p; if (d.nm) packByNm[String(d.nm).trim()] = d; }
    let checked = 0; const bad = [];
    for (const [k, rec] of Object.entries(recs)) {
      const d = rec.data || {}; const p = packByNm[String(d.nm || '').trim()]; if (!p) continue; checked++;
      for (const f of ['roic', 'irr', 'per', 'dom', 'moatW', 'nde']) {
        const a = d[f] == null ? '' : String(d[f]), e = p[f] == null ? '' : String(p[f]);
        if (e !== '' && a !== '' && parseFloat(a) !== parseFloat(e)) { bad.push(k + ' ' + f + ' ' + a + '≠' + e); break; }
      }
    }
    ok(mid && typeof mid === 'object', '② 自動取込の最中に一括取込を押す（' + JSON.stringify(mid) + '）');
    ok(st === 'done' && packFetches === N, '   2本目は始めずに待つ（パックの取得 ' + packFetches + ' 件＝1回分）');
    ok(Object.keys(recs).length === N && checked === N && bad.length === 0,
      '   台帳 ' + Object.keys(recs).length + '社・パックと突き合わせた ' + checked + '社で数字の食い違い ' + bad.length + '件' + (bad.length ? '（' + bad.slice(0, 3).join(' / ') + '）' : ''));
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  // ③ 台帳がパックの半分以上あり、印も無い（5社だけ無い）→ 自動では取り込まない（人が直した値を巻き戻さない）・帯を🛒買付順位にも出す
  //    → そこから押した取り込みはページを移動しない
  //    （v9.9.218 の続きで、半分に届かない台帳は「初めての取り込みが途中で終わった」とみなして台帳に無い社だけを自動で取り込む＝⑦。
  //      旧版の③は「1件でもあれば自動では取り込まない」を1社の台帳で確かめていた）
  {
    const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 0;
    await pg.goto(URL);
    const s0 = await waitAuto(pg);                    // 台帳が空なので、まず全部が自動で入る
    await pg.waitForTimeout(1500);
    await pg.evaluate(() => {
      const ks = Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).sort();
      ks.slice(0, 5).forEach(k => localStorage.removeItem(k));
      localStorage.removeItem('ccf:autoImp');
    });
    packFetches = 0;
    await pg.reload(); await pg.waitForTimeout(3000);
    const n0 = await ledgerN(pg);
    const st0 = await pg.evaluate(() => window.__ccfAutoImp);
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
    const bar5 = await pg.evaluate(() => { const e = document.getElementById('packFreshBar5'); return { shown: getComputedStyle(e).display !== 'none', t: e.innerText }; });
    ok(s0 === 'done' && n0 === N - 5 && st0 === null && packFetches === 0,
      '③ 台帳がパックの半分以上（5社だけ無い）・印なし → 自動では取り込まない（台帳 ' + n0 + '社・自動取込 ' + JSON.stringify(st0) + '・取得 ' + packFetches + '件）');
    ok(bar5.shown && /台帳に入っていないパックが 5社/.test(bar5.t) && /いま取り込む/.test(bar5.t) && /買付順位にも出ない/.test(bar5.t),
      '   🛒買付順位にも未取込の帯（理由と「⭳ いま取り込む」）');
    await pg.evaluate(() => { const btn = document.querySelector('#packFreshBar5 button'); btn && btn.click(); });
    for (let i = 0; i < 120; i++) { await pg.waitForTimeout(1000); if ((await ledgerN(pg)) >= N && !(await pg.evaluate(() => window.__ccfImpRun))) break; }
    await pg.waitForTimeout(2500);
    const after = await pg.evaluate(() => ({ page: window.__ccfPage, order: /📋 今月の注文書/.test((document.querySelector('#pg5') || {}).innerText || ''),
      bar5: getComputedStyle(document.getElementById('packFreshBar5')).display }));
    ok((await ledgerN(pg)) === N && after.page === 5 && after.order && after.bar5 === 'none',
      '   帯から押すと全部取り込み、ページは🛒買付順位のまま・注文書が出て帯は消える（page ' + after.page + '）');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  // ④ 自動取込が途中で終わった（アプリを閉じた等）→ 次に開くと**台帳にまだ無い社だけ**を続きから取り込む
  //    既にあるレコードは1件も置き換えない（人が直した値を巻き戻さない）・終わると印（ccf:autoImp）は消える
  {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
    const pg = await ctx.newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 0;
    await pg.goto(URL);
    const st0 = await waitAuto(pg);                    // 台帳が空なので、まず全部が自動で入る
    await pg.waitForTimeout(1500);
    const prep = await pg.evaluate(() => {
      const ks = Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).sort();
      const drop = ks.filter((k, i) => i % 3 === 1);   // 3社に1社を消す＝途中で終わった台帳
      drop.forEach(k => localStorage.removeItem(k));
      const keep = ks.filter((k, i) => i % 3 !== 1);
      const k0 = keep[0], o = JSON.parse(localStorage.getItem(k0));
      o.__probe = 'keep';                               // 置き換えられれば消える印（レコードごと書き直すと残らない）
      localStorage.setItem(k0, JSON.stringify(o));
      localStorage.setItem('ccf:autoImp', JSON.stringify({ at: new Date().toISOString(), tries: 1 }));
      return { drop: drop.length, keep: keep.length, k0 };
    });
    PACK_DELAY = 25; packFetches = 0;
    await pg.reload(); await pg.waitForTimeout(1500);
    const mid = await pg.evaluate(() => ({ ai: window.__ccfAutoImp, today: (document.getElementById('pg10') || {}).innerText || '' }));
    const st = await waitAuto(pg);
    await pg.waitForTimeout(2000);
    const after = await pg.evaluate(k0 => ({
      n: Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length,
      probe: (JSON.parse(localStorage.getItem(k0) || '{}') || {}).__probe || null,
      mark: localStorage.getItem('ccf:autoImp'),
      logs: Object.keys(localStorage).filter(k => k.indexOf('g7log:') === 0).map(k => JSON.parse(localStorage.getItem(k)).title),
      dirty: (window.ccfState && ccfState.isDirty) ? ccfState.isDirty() : null }), prep.k0);
    ok(st0 === 'done' && prep.drop > 50, '④ 途中で終わった台帳を作る（' + prep.keep + '社が残り ' + prep.drop + '社が無い・印あり）');
    ok(mid.ai && typeof mid.ai === 'object' && mid.ai.resume === true, '   次に開くと続きの自動取込が始まる（' + JSON.stringify(mid.ai) + '）');
    ok(/前回の自動取込の続き/.test(mid.today) && !/自動では取り込みません/.test(mid.today), '   📋今日は「前回の自動取込の続き」と言う（「自動では取り込みません」と言わない）');
    ok(st === 'done' && after.n === N, '   取り込み終了 ' + st + '・台帳 ' + after.n + '/' + N + '社');
    ok(packFetches === prep.drop, '   取得したのは台帳に無かった社だけ（' + packFetches + '件＝無かった ' + prep.drop + '社）');
    ok(after.probe === 'keep', '   既にあったレコードは置き換えない（人が直した印 __probe が残る）');
    ok(after.mark === null, '   終わると印（ccf:autoImp）は消える');
    ok(after.logs.some(t => /自動取込の続き/.test(t)), '   検証履歴に「自動取込の続き」');
    ok(after.dirty === false, '   赤い帯（未書き出し）は立たない');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));

    // ⑤ 印が3回続けて残る（毎回終わらない）なら、諦めて印を消し、帯で知らせるだけにする
    const prep2 = await pg.evaluate(() => {
      const ks = Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).sort();
      const drop = ks.slice(0, 5); drop.forEach(k => localStorage.removeItem(k));
      localStorage.setItem('ccf:autoImp', JSON.stringify({ at: new Date().toISOString(), tries: 3 }));
      return { drop: drop.length };
    });
    PACK_DELAY = 0; packFetches = 0;
    await pg.reload(); await pg.waitForTimeout(3000);
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
    const g = await pg.evaluate(() => ({ ai: window.__ccfAutoImp, mark: localStorage.getItem('ccf:autoImp'),
      n: Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length,
      bar5: (document.getElementById('packFreshBar5') || {}).innerText || '' }));
    ok(g.ai === null && packFetches === 0 && g.n === N - prep2.drop && g.mark === null,
      '⑤ 印が3回目まで残っていたら続きはしない（自動取込 ' + JSON.stringify(g.ai) + '・取得 ' + packFetches + '件・印 ' + g.mark + '）');
    ok(/台帳に入っていないパックが 5社/.test(g.bar5) && /いま取り込む/.test(g.bar5), '   代わりに🛒買付順位の帯で知らせる（' + prep2.drop + '社・「⭳ いま取り込む」）');
    await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(3000);
    const note = await pg.evaluate(() => { const e = document.querySelector('#pg6 .packMissNote'); return e ? e.innerText : ''; });
    ok(/台帳に入っていないパックが 5社/.test(note) && /いま取り込む/.test(note), '   🏦保有の投下可の下にも「台帳に入っていないパックが 5社」と「⭳ いま取り込む」');

    // ⑦ 印は無いが台帳がパックの半分に届かない（印を置く前の版で押した一括取込を途中で閉じた等）→ 台帳にまだ無い社だけを続きから
    const prep3 = await pg.evaluate(() => {
      const ks = Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).sort();
      const keep = ks.filter((k, i) => i % 3 === 0);   // 3社に1社だけ残す＝半分に届かない
      const drop = ks.filter((k, i) => i % 3 !== 0); drop.forEach(k => localStorage.removeItem(k));
      const k0 = keep[0], o = JSON.parse(localStorage.getItem(k0)); o.__probe = 'keep3'; localStorage.setItem(k0, JSON.stringify(o));
      localStorage.removeItem('ccf:autoImp');
      return { drop: drop.length, keep: keep.length, k0 };
    });
    packFetches = 0;
    await pg.reload(); await pg.waitForTimeout(1200);
    const ai7 = await pg.evaluate(() => window.__ccfAutoImp);
    const st7 = await waitAuto(pg); await pg.waitForTimeout(1500);
    const a7 = await pg.evaluate(k0 => ({ n: Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length,
      probe: (JSON.parse(localStorage.getItem(k0) || '{}') || {}).__probe || null, mark: localStorage.getItem('ccf:autoImp') }), prep3.k0);
    ok(ai7 && (ai7 === 'done' || (typeof ai7 === 'object' && ai7.resume === true)) && st7 === 'done' && a7.n >= N,
      '⑦ 印なし・台帳がパックの半分未満（' + prep3.keep + '社）→ 続きの自動取込（' + JSON.stringify(ai7) + '・台帳 ' + a7.n + '社）');
    // 無かった社＝パックの数 − 残した社（⑤で消した5社も無いまま＝それも含めて取り込む）
    ok(packFetches === N - prep3.keep && a7.probe === 'keep3' && a7.mark === null,
      '   取得は無かった社だけ（' + packFetches + '件＝パック ' + N + ' − 残した ' + prep3.keep + '社）・既にあったレコードは置き換えない・印は残らない');
  }

  // ⑥ 取り込み中の🏦保有・📋今日・今月の買付プラン・目標ポートフォリオのカード——「投下可なし」とだけ言わない
  {
    const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 45; packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(2500);
    const today = await pg.evaluate(() => (document.getElementById('pg10') || {}).innerText || '');
    await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(2500);
    const hold = await pg.evaluate(() => ({ t: (document.getElementById('pg6') || {}).innerText || '',
      pft: (document.getElementById('pftCard') || {}).innerText || '' }));
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2000);
    const plan = await pg.evaluate(() => (document.getElementById('planBox') || {}).innerText || '');
    ok(/自動で取り込んでいます/.test(today) && !/自動では取り込みません/.test(today), '⑥ 📋今日: 「自動で取り込んでいます」（「自動では取り込みません」と言わない）');
    ok(/台帳がまだ空です|取り込んでいる途中です/.test(hold.t) && !/投下可なし/.test(hold.t), '   🏦保有の投下可: 台帳が空・取り込み中の理由と進み具合（「投下可なし」と言わない）');
    ok(/取り込んでいる途中なので席を出せない/.test(hold.pft), '   目標ポートフォリオのカード: 席を出せない理由に「取り込んでいる途中」');
    ok(/台帳を自動で取り込んでいる途中のため/.test(plan) && !/🟢投下可なし/.test(plan) && !/📋 今月の注文書/.test(plan),
      '   🛒買付順位: 途中の台帳で席を計算しない（「🟢投下可はまだ出せません——取り込んでいる途中のため」・注文書は終わってから）');
    // 取込の段（台帳が半分だけ入った状態）まで待ってから、もう一度🏦保有と🛒買付順位を見る
    let half = null;
    for (let i = 0; i < 120; i++) {
      const ai = await pg.evaluate(() => window.__ccfAutoImp);
      if (ai && typeof ai === 'object' && ai.st === '取込' && ai.done >= 60) { half = ai; break; }
      if (ai === 'done' || ai === 'fail') break;
      await pg.waitForTimeout(500);
    }
    if (half) {
      await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(2000);
      const h = await pg.evaluate(() => ({ t: (document.getElementById('pg6') || {}).innerText || '',
        n: Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length, seats: ((window.__pftData || {}).castle || []).filter(c => c.k !== 'c:_rest' && c.tw > 0).length }));
      await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2000);
      const pl = await pg.evaluate(() => (document.getElementById('planBox') || {}).innerText || '');
      ok(h.n > 0 && /取り込んでいる途中です/.test(h.t) && !/投下可なし/.test(h.t) && h.seats === 0,
        '   台帳が半分（' + h.n + '社）の間も🏦保有は席を計算しない（「取り込んでいる途中です」・席 ' + h.seats + '社）');
      ok(/取り込んでいる途中/.test(pl) && !/📋 今月の注文書/.test(pl) && !/🟢投下可なし/.test(pl), '   同じく🛒買付順位も途中の台帳では注文書を出さない');
    } else ok(false, '   取込の段の途中を捕まえられなかった（' + JSON.stringify(half) + '）');
    const st = await waitAuto(pg);
    await pg.evaluate(() => showPage(6)); await pg.waitForTimeout(3000);
    const hold2 = await pg.evaluate(() => {
      const t = (document.getElementById('pg6') || {}).innerText || '';
      const M = window.__pftData || {};
      return { empty: /台帳がまだ空です|台帳が空/.test(t), none: /投下可なし/.test(t),
        seats: (M.castle || []).filter(c => c.k !== 'c:_rest' && c.tw > 0).length };
    });
    ok(st === 'done' && !hold2.empty && !hold2.none && hold2.seats >= 1,
      '   終わると🏦保有に投下可と目標の席が出る（席 ' + hold2.seats + '社・「台帳が空」「投下可なし」は消える）');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
