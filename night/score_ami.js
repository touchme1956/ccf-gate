#!/usr/bin/env node
/* 網の門(ami.html)の採点を、端末から全候補へ一括で当てる。**表示だけ・門Ωの判定には一切使わない。**
 *
 * なぜ要るか（2026-08-19）:
 *   ETFを「金のつるはしか」「伸びる産業か」で評価しようとすると答えが出ない——それは**城の物差し**だから。
 *   網の判定はもう ami.html にある（コスト.40 / 土台の広さ.30 / 存続性.20 / 器の効率.10）。
 *   ところが ami.html は**1本ずつ手で入力する対話ページ**なので、候補が増えると誰も全部は当てない。
 *   → out/etf_profiles.json の実採取から入力を機械で作り、**同じ関数**を当てて並べる。
 *
 * ★採点関数は ami.html から実行時に抜き出して eval する（**書き写さない**）。
 *   書き写した瞬間に「同じ台帳を見る二つの検査器が違うことを言う」（v9.9.65）になるため。
 *
 * 入力の作り方（すべて実採取から機械で）:
 *   経費率・純資産・設定日・銘柄数・最大セクター … out/etf_profiles.json
 *   上位10集中 … 保有比の上位10合計
 *   城との重複 … portfolio.json(sleeve=城) ＋ state.json(pf:portfolio) の銘柄に当たる保有比
 *   器 … 米国ETF固定(us_etf=62)。日本の投信で持つなら +2〜4pt（末尾の感度で出す）
 * ⚠ 中身が薄いETF（VTは9500銘柄中41件しか採れていない）は**上位10と城重複が過小に出る**。
 *   広さの主因は銘柄数と最大セクターなので順位は動かないが、数字は「測れた分」であることを併記する。
 *
 * 使い方: node night/score_ami.js
 */
const fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname);
const R = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

/* ---- ami.html から採点関数をそのまま抜く（再実装しない） ---- */
const html = R('ami.html');
const grab = name => {
  const i = html.indexOf('function ' + name);
  if (i < 0) throw new Error('ami.html に ' + name + ' が無い');
  let d = 0, j = html.indexOf('{', i), k;
  for (k = j; k < html.length; k++) {
    if (html[k] === '{') d++;
    else if (html[k] === '}' && --d === 0) break;
  }
  return html.slice(i, k + 1);
};
const NEED = ['ramp', 'gm', 'costPt', 'breadthPt', 'durPt', 'wrapPt'];
eval(NEED.map(grab).join('\n'));

const P = JSON.parse(R('out/etf_profiles.json')).etfs;
const pf = JSON.parse(R('portfolio.json'));
const castle = new Set(pf.positions.filter(p => p.sleeve === '城').map(p => p.ticker));
try {
  const st = JSON.parse(R('state.json'));
  const pp = JSON.parse((st.data || {})['pf:portfolio'] || '{}');
  (pp.positions || []).forEach(x => { if (x.t) castle.add(String(x.t).split(/\s/)[0]); });
} catch (e) { /* state.json が無くても portfolio.json だけで動く */ }

const USDJPY = 158.2;   // 純資産を億円へ直すためだけ。順位に効かない桁
const rows = [];
for (const [t, e] of Object.entries(P)) {
  const h = (e.h || []).slice().sort((a, b) => b[1] - a[1]);
  if (!h.length) continue;
  const cov = h.reduce((s, x) => s + x[1], 0);
  const top10 = h.slice(0, 10).reduce((s, x) => s + x[1], 0) * 100;
  const sec = Math.max(...Object.values(e.sec || { x: 0 })) * 100;
  const ov = h.filter(x => castle.has(x[0])).reduce((s, x) => s + x[1], 0) * 100;
  const er = (e.er || 0) * 100;
  const aum = (e.aum || 0) * USDJPY / 1e8;
  const y = parseInt(String(e.inc).slice(0, 4)), mo = parseInt(String(e.inc).slice(5, 7) || '1');
  const age = (2026 - y) + (8 - mo) / 12;
  const n = e.n || h.length;
  const kills = [];
  if (e.lev) kills.push('レバレッジ');
  if (aum < 100) kills.push('純資産<100億円');
  if (age < 3) kills.push('設定<3年');
  if (er > 0.75) kills.push('経費率>0.75%');
  const C = costPt(er), B = breadthPt(n, top10, sec), D = durPt(aum, age), T = wrapPt('us_etf');
  let W = gm([C, B, D, T], [.40, .30, .20, .10]);
  const ovPen = ov <= 10 ? 0 : ramp(ov, [[10, 0], [20, 3], [30, 7], [50, 14], [70, 22]]);
  W = Math.max(0, W - ovPen);
  if (kills.length) W = Math.min(W, Math.max(20, 45 - 8 * (kills.length - 1)));
  const pass = kills.length === 0 && B >= 60 && C >= 68 && ov < 30;
  const why = [];
  if (B < 60) why.push(`広さ${B.toFixed(0)}<60`);
  if (C < 68) why.push(`コスト${C.toFixed(0)}<68`);
  if (ov >= 30) why.push(`重複${ov.toFixed(0)}%≥30`);
  rows.push({ t, W, pass, C, B, D, er, top10, sec, ov, cov, kills, why });
}
rows.sort((a, b) => b.W - a.W);

const f = (x, w, d) => x.toFixed(d).padStart(w);
console.log('■ 網の門(ami.html)の採点を全候補へ — **表示だけ・門Ωの判定には一切使わない**');
console.log('  城の銘柄:', [...castle].join(' '));
console.log('\nETF    網Ω 判定  コスト   広さ   存続   経費率   上位10  最大Sec  城重複  測れた  落ちた理由');
for (const r of rows) {
  console.log(r.t.padEnd(5) + f(r.W, 5, 1) + '  ' + (r.pass ? '🟢' : '⛔') + f(r.C, 6, 1) + f(r.B, 7, 1)
    + f(r.D, 7, 1) + f(r.er, 7, 2) + '%' + f(r.top10, 7, 1) + '%' + f(r.sec, 7, 1) + '%'
    + f(r.ov, 6, 1) + '%' + f(r.cov * 100, 6, 0) + '%  '
    + ((r.kills.length ? '✕' + r.kills.join('/') + ' ' : '') + r.why.join('/')));
}
console.log('\n■ 器の感度（同じ中身を 米国ETF(62) → 日本の投信(95) の器で持ったら）');
for (const r of rows.slice(0, 4)) {
  const ovPen = r.ov <= 10 ? 0 : ramp(r.ov, [[10, 0], [20, 3], [30, 7], [50, 14], [70, 22]]);
  const W2 = Math.max(0, gm([r.C, r.B, r.D, wrapPt('jp_toshin')], [.40, .30, .20, .10]) - ovPen);
  console.log('   ' + r.t.padEnd(5) + ' 米国ETF ' + r.W.toFixed(1) + ' → 日本の投信 ' + W2.toFixed(1)
    + '（+' + (W2 - r.W).toFixed(1) + '）');
}
console.log('\n⚠ 「上位10」「城重複」は**測れた分**の上の数字。中身の薄いETF（VTは9500銘柄中41件）では過小に出る。');
console.log('⚠ この採点に「どの産業が伸びるか」「つるはしか」は**一つも入っていない**——それは城(門Ω)の仕事。');
