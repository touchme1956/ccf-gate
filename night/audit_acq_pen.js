// night/audit_acq_pen.js — 「買収による減点」が今も何社で効いているかを数える（2026-09-21新設）
//   読むだけ。門の compute() をそのまま走らせ、警戒帯(ambers)の文面から買収まわりの3本を拾う。
//   v9.9.181 で acqS5 が入ったあと「買収のマイナスは消えたのか」を答えるための道具。
const fs = require('fs'), path = require('path');
const SA = require('./score_all.js');
const BASE = path.dirname(__dirname);
const files = fs.readdirSync(path.join(BASE, 'out')).filter(f => f.endsWith('_gate_pack.json'));
const rows = [];
for (const f of files) {
  const t = f.replace('_gate_pack.json', '');
  const d = JSON.parse(fs.readFileSync(path.join(BASE, 'out', f), 'utf8'));
  let r; try { r = SA.scorePack(d); } catch (e) { continue; }
  const ks = global.$('killSig');
  const html = (ks && ks.innerHTML) || '';
  const gapM = html.match(/のれん込みROIC乖離(\d+)pt——買収規律に疑義 −([\d.]+)/);
  const wacc = /のれん込みROIC .*＜WACC——買収が価値破壊 −8/.test(html);
  const acqM = html.match(/買収支出は5年で総資産の ([\d.]+)% ＝ (.+?) ([+-]?\d)（/);
  rows.push({ t, s: Number(r.evalScore), gap: gapM ? parseFloat(gapM[2]) : 0, wacc: wacc ? 8 : 0,
              acqPt: acqM ? parseInt(acqM[3], 10) : null, acqLab: acqM ? acqM[2] : '未測定' });
}
const f2 = (x) => (x == null ? '??' : x.toFixed(1));
// ⚠ 検査器の自己検問——Ωが取れない行が1つでもあれば**大声で止まる**。
//   初版は scorePack の戻り値を r.score と読んでおり（正しくは r.evalScore）、
//   全行の Ω が undefined になって「判定圏(Ω72+)に該当なし」という**嘘の安心**を出した。
//   直したあとも evalScore は **文字列**で返ってきて（'57.8'）、この検問が二度目に止めた。Number() で揃える。
//   「強い結論ほど先に道具を疑う」（recalc_roic の ADBE 事故と同型）。
{
  const bad = rows.filter(r => typeof r.s !== 'number' || !isFinite(r.s));
  if (bad.length) { console.error(`✗ Ωを取れなかった社が ${bad.length} 件ある。検査器が壊れている——結果を使うな`); process.exit(2); }
}
const hasGap = rows.filter(r => r.gap > 0), hasW = rows.filter(r => r.wacc > 0);
const both = rows.filter(r => r.gap > 0 && r.wacc > 0);
console.log(`全 ${rows.length} 社`);
console.log(`\n【いま効いている買収まわりの減点】`);
console.log(`  ① のれん込みROIC乖離>15pt ∧ acq5=yes → ramp 0〜−6 : ${hasGap.length}社（合計 −${f2(hasGap.reduce((a, r) => a + r.gap, 0))}pt・最大 −${f2(Math.max(0, ...hasGap.map(r => r.gap)))}）`);
console.log(`  ② のれん込みROIC < WACC          → −8         : ${hasW.length}社（合計 −${hasW.length * 8}pt）`);
console.log(`     ①②の両方を食らっている社                    : ${both.length}社`);
const byPt = {};
for (const r of rows) { const k = r.acqLab; byPt[k] = (byPt[k] || 0) + 1; }
console.log(`\n【v9.9.181 で入った acqS5 の項（罰ではなく加点差）】`);
for (const k of ['買収しない', '買収は控えめ', '買収は中程度', '大きく買う', '未測定'])
  if (byPt[k]) console.log(`  ${k.padEnd(7)} ${String(byPt[k]).padStart(3)}社  ${k === '大きく買う' ? '←「大きく買う」は 0 点＝**減点ではない**' : ''}`);
console.log(`\n【判定圏(Ω72+)で買収の減点を食らっている社】`);
const pen = rows.filter(r => r.gap > 0 || r.wacc > 0).sort((a, b) => b.s - a.s);
const q = pen.filter(r => r.s >= 72);
for (const r of q) console.log(`  ${r.t.padEnd(6)} Ω${f2(r.s)}  乖離 −${f2(r.gap)} / WACC割れ −${r.wacc}  合計 −${f2(r.gap + r.wacc)}   acqS5の帯=${r.acqLab}`);
if (!q.length) console.log('  なし（＝買収の減点は判定圏の外でだけ効いている）');
console.log(`\n【減点を食らっている社をΩの高い順に12社】`);
for (const r of pen.slice(0, 12))
  console.log(`  ${r.t.padEnd(6)} Ω${f2(r.s)}  乖離 −${f2(r.gap)} / WACC割れ −${r.wacc}  合計 −${f2(r.gap + r.wacc)}  acqS5=${r.acqLab}`);
