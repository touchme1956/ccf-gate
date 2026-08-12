#!/usr/bin/env node
/* night/check_state_banner.js — state.js の帯が「鳴るべきときだけ鳴る」かを実ブラウザで確かめる
 *
 * ■ なぜ要るか（この帯は2回続けて壊れた）
 *   1回目 2026-08-10: Ⅶ資産が <iframe> の中にあり `allow="clipboard-write"` が無く、
 *     クリップボードが**例外も出さずに拒否**され、3回書き出しても同じ古い中身が貼られ続けた。
 *   2回目 2026-08-11: `done()`（④入れた）が **押した時刻**を savedAt に書いていたため、
 *     repo より必ず新しくなり『repo の state.json が手元より古い』が**鳴り続けた**。
 *     しかも帯自身が「④ ここへ戻って押す」と案内している＝**手順どおりにやると必ずこうなる**。
 *   どちらも「副作用の無い経路は失敗しても静か」の型で、文章では見つからない。**実ブラウザで見る**。
 *
 * ■ 判定
 *   ① 手元と repo が揃っている（印だけ手元が新しい）→ **何も出さない**（自己修復）
 *   ② 中身が違うが未書き出しは無い          → **何も出さない**（人がやることが無い）
 *   ③ decide() の分岐が壊れていない
 *   ④ 「入れた」は押した時刻でなく **repo の savedAt** を書く
 *   ⑤ **本物の警報（未書き出しの決定がある）は赤いまま・ボタンつきで出る**
 *
 * playwright が要るので CI には入れていない（night/check_mobile_fit.js と同じ扱い）。
 *   使い方: node night/check_state_banner.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8791;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

const srv = http.createServer((q, r) => {
  let f = path.join(ROOT, decodeURIComponent(q.url.split('?')[0]));
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
  const st = JSON.parse(fs.readFileSync(path.join(ROOT, 'state.json'), 'utf8'));
  const b = await chromium.launch({ executablePath: CHROME });
  const pg = await b.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  const bar = async () => (await pg.locator('#stateBar').innerText().catch(() => '')).trim();
  let ng = 0;
  const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

  await pg.goto('http://localhost:' + PORT + '/index.html');

  // ① 印だけ手元が新しい（2026-08-11の詰まりの再現）→ 何も出さず、印を repo に合わせる
  await pg.evaluate(([d]) => {
    localStorage.clear();
    for (const k in d) localStorage.setItem(k, d[k]);
    localStorage.setItem('ccf:stateSavedAt', '2999-01-01T00:00:00.000Z');
    localStorage.removeItem('ccf:stateDirty');
  }, [st.data]);
  await pg.reload(); await pg.waitForTimeout(1500);
  ok(!(await bar()), '① 印だけ手元が新しい → 帯を出さない');
  ok(await pg.evaluate(s => localStorage.getItem('ccf:stateSavedAt') === s, st.savedAt),
     '   印が repo の savedAt に揃う（自己修復）');

  // ③ decide の分岐
  const d = await pg.evaluate(() => [
    ccfState.decide(null, 'x', false), ccfState.decide('b', 'a', false),
    ccfState.decide('a', 'b', false), ccfState.decide('a', 'a', false),
    ccfState.decide('a', 'b', true)]);
  ok(d.join('/') === 'uninit/adopt/stale/same/dirty', '③ decide の5分岐: ' + d.join(' / '));

  // ④ 「入れた」は押した時刻を書かない
  await pg.evaluate(([d]) => {
    localStorage.clear();
    for (const k in d) localStorage.setItem(k, d[k]);
    localStorage.setItem('pf:monthly', '777');
    localStorage.setItem('ccf:stateSavedAt', '2999-01-01T00:00:00.000Z');
  }, [st.data]);
  await pg.reload(); await pg.waitForTimeout(1200);
  await pg.evaluate(() => { try { ccfState.done(null); } catch (e) {} });
  await pg.waitForTimeout(2500);
  ok(await pg.evaluate(s => localStorage.getItem('ccf:stateSavedAt') === s, st.savedAt),
     '④ 入れた → repo の savedAt を書く（押した時刻ではない）');
  ok(!(await bar()), '   その場で帯が消える');

  // ⑤ 本物の警報は赤いまま
  await pg.evaluate(() => { localStorage.setItem('pf:monthly', '123456'); });
  await pg.evaluate(() => ccfState.load().then(() => ccfState.banner('stateBar')));
  await pg.waitForTimeout(1200);
  const t = await bar(), nb = await pg.locator('#stateBar button').count();
  ok(/まだ repo に入っていません/.test(t) && nb >= 2,
     '⑤ 未書き出しの決定 → 赤い帯 + ボタン' + nb + '個');

  /* ⑥⑦⑧ 2026-08-12（3回目の破れ・ユーザー「これがでないようにして」）
     ⭳全パック一括取込／↻全再採点 は最後に `saveLog({title:'一括再採点 …銘柄'})` を自動で呼び、
     それが `g7log:` を書く。旧実装はそこで dirty を立てていたので、
     **手順書どおりの運用で毎回 赤い帯が出ていた**（決定は1バイトも変えていないのに）。 */
  const install = () => pg.evaluate(([d]) => {
    localStorage.clear();
    for (const k in d) localStorage.setItem(k, d[k]);
    localStorage.removeItem('ccf:stateDirty');
    localStorage.setItem('ccf:stateSavedAt', '1999-01-01T00:00:00.000Z');
  }, [st.data]);

  await install(); await pg.reload(); await pg.waitForTimeout(1500);
  await pg.evaluate(() => saveLog({ date: '2026-08-12', title: '一括再採点 369銘柄', body: 'x' }));
  await pg.waitForTimeout(400);
  ok(await pg.evaluate(() => localStorage.getItem('ccf:stateDirty') === null),
     '⑥ 機械の検証履歴(g7log:)では dirty が立たない');
  await pg.reload(); await pg.waitForTimeout(1500);
  ok(!(await bar()), '   再読込しても帯は出ない');

  // ⑦ 既に立ってしまった旗は自己修復する（違うのは盤が書き戻した npx/fx だけ）
  await pg.evaluate(() => localStorage.setItem('ccf:stateDirty', '1'));
  await pg.reload(); await pg.waitForTimeout(1500);
  ok(!(await bar()) && await pg.evaluate(() => localStorage.getItem('ccf:stateDirty') === null),
     '⑦ 価格の書き戻ししか違わない旗は自己修復して消える');

  // ⑧ ★正規化が本物の決定を隠していないこと（株数を1株だけ変える）
  await pg.evaluate(() => {
    const o = JSON.parse(localStorage.getItem('pf:portfolio'));
    o.positions[0].sh = (o.positions[0].sh || 0) + 1;
    localStorage.setItem('pf:portfolio', JSON.stringify(o));
  });
  await pg.reload(); await pg.waitForTimeout(1500);
  ok(/まだ repo に入っていません/.test(await bar()),
     '⑧ 株数(sh)を1株変えたら帯が出る（正規化は決定を隠さない）');

  ok(errs.length === 0, 'pageerror ' + errs.length + '件');
  await b.close(); srv.close();
  console.log(ng ? `\n✗ ${ng}件の不一致` : '\n✓ 帯は鳴るべきときだけ鳴る');
  process.exit(ng ? 1 : 0);
})();
