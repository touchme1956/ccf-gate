#!/usr/bin/env node
/* night/check_stale_bar.js — 台帳の取り残しの帯が「鳴るべきときだけ鳴る」かを実ブラウザで確かめる
 *
 * ■ なぜ要るか（実害から作った帯）
 *   2026-09-22、ユーザーの画面に **LRCX が投下可として出てこなかった**。配信は正しく更新されていて
 *   （curl で v9.9.186・CCF_SEATS=5・新しい堀の重みを確認）、原因は **ブラウザの台帳(g7:)が
 *   v9.9.181 より前のパックのまま**で `acqS5` を1件も持っていなかったこと。
 *   再現: `node night/score_all.js --set acqS5=` で**同じ画面**が出る（LRCX 81.2 で IDXX と同点→6位）。
 *   ⚠「↻全再採点」では直らない（保存済み data に現行 compute() を通すだけ）。
 *   必要なのは Ⅵの「⭳ 全パック一括取込」だが、**押し忘れが外から見えなかった**。
 *
 * ■ 判定（両方向を見る——鳴ることと、鳴り止むこと）
 *   ① 台帳が空          → **何も出さない**（まだ何も取り込んでいない人に警告は要らない）
 *   ② 欄を全部持っている → **何も出さない**（健全なら黙る）
 *   ③ acqS5 だけ抜く    → **鳴る**＋一括取込へ誘導し、「全再採点では直らない」と書いてある
 *   ④ 銘柄が足りない    → **鳴る**（パックはあるのに台帳に記録が無い）
 *   ⑤ 材料が読めない    → **「検査できず」と出す**（測っていないことを健全と読ませない・ルール7）
 *
 * playwright が要るので CI には入れていない（check_state_banner.js / check_mobile_fit.js と同じ扱い）。
 *   使い方: node night/check_stale_bar.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8793;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

let HIDE_PF = false;                       // ⑤ 材料が読めない場合の再現に使う
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  if (HIDE_PF && rel.endsWith('/out/pack_fields.json')) { r.writeHead(404); r.end('x'); return; }
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
  const pf = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/pack_fields.json'), 'utf8'));
  const b = await chromium.launch({ executablePath: CHROME });
  const pg = await b.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  const bar = async () => (await pg.locator('#staleBar').innerText().catch(() => '')).trim();
  let ng = 0;
  const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

  // 台帳を作る道具。全パックから欄を写し、drop で指定した欄だけ落とす（＝古い台帳の再現）
  const seed = async (tickers, drop) => {
    const packs = {};
    for (const t of tickers) {
      const d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/' + t + '_gate_pack.json'), 'utf8'));
      packs[t] = d.data || d;
    }
    await pg.evaluate(([packs, drop, fields]) => {
      Object.keys(localStorage).forEach(k => { if (k.indexOf('g7:') === 0) localStorage.removeItem(k); });
      Object.entries(packs).forEach(([t, p]) => {
        const data = { nm: t };
        fields.forEach(f => {
          if (drop.indexOf(f) >= 0) return;
          if (p[f] !== undefined && p[f] !== null && p[f] !== '') data[f] = String(p[f]);
        });
        localStorage.setItem('g7:' + t, JSON.stringify({ data: data, r: {} }));
      });
    }, [packs, drop || [], Object.keys(pf.fields)]);
  };

  console.log('■ 台帳の取り残しの帯（night/check_stale_bar.js）');
  await pg.goto('http://localhost:' + PORT + '/index.html');

  // ① 台帳が空 → 黙る
  await pg.evaluate(() => localStorage.clear());
  await pg.reload(); await pg.waitForTimeout(1200);
  ok(!(await bar()), '① 台帳が空 → 帯を出さない');

  // ② 全パック・全欄そろい → 黙る
  const ALL = pf.tickers;
  await seed(ALL, []);
  await pg.reload(); await pg.waitForTimeout(2500);
  const t2 = await bar();
  ok(!t2, '② 全パック・欄そろい → 帯を出さない' + (t2 ? '（出た: ' + t2.slice(0, 90) + '）' : ''));

  // ③ acqS5 だけ抜く＝2026-09-22 の実害そのもの → 鳴る
  await seed(ALL, ['acqS5']);
  await pg.reload(); await pg.waitForTimeout(2500);
  const t3 = await bar();
  ok(/台帳が古い/.test(t3), '③ acqS5 を抜く → 鳴る');
  ok(/acqS5/.test(t3), '   欄を名指しする（acqS5）');
  ok(/一括取込/.test(t3), '   一括取込へ誘導する');
  ok(/全再採点/.test(t3) && /直りません/.test(t3), '   「全再採点では直らない」と書いてある');

  // ④ 銘柄が足りない → 鳴る
  await seed(ALL.slice(0, 40), []);
  await pg.reload(); await pg.waitForTimeout(2500);
  const t4 = await bar();
  ok(/台帳に無い銘柄/.test(t4), '④ パックはあるのに台帳に無い銘柄 → 鳴る');

  // ⑤ 材料が読めない → 「検査できず」と言う（黙って健全に見せない）
  HIDE_PF = true;
  await seed(ALL, []);
  await pg.reload(); await pg.waitForTimeout(2500);
  const t5 = await bar();
  ok(/検査できません/.test(t5), '⑤ pack_fields.json が読めない → 「検査できず」と出す');
  HIDE_PF = false;

  ok(errs.length === 0, 'pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  await pg.evaluate(() => localStorage.clear());
  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
