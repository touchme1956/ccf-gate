// night/audit_cliffs.js — 採点に残っている「崖（二値・定数の段差）」を全部数える（2026-09-21新設）
//   読むだけ・採点に一切触れない。audit_monotonic.js は **数値欄しか振らない**ので、
//   enum で発火するキルや定性の段差（sht/gls/moatdecay/expiry/eq…）が視野の外にあった。
//   ここは **規則ごとに入力を「発火する値／しない値」へ振って ΔΩ を実測**する。
//   使い方: node night/audit_cliffs.js [--all]   （既定は判定圏 Ω72+ だけを数える）
const fs = require('fs'), path = require('path');
const SA = require('./score_all.js');
const BASE = path.dirname(__dirname);
const ALL = process.argv.includes('--all');

// 規則 = {名前, 大きさ(設計値), 欄, 発火する値, 発火しない値}
// ⚠ ROIC≤WACC と ROIIC³<WACC は **WACCとの比較**なので「発火しない値」を大きめに取る
const RULES = [
  { n: '財務キル nde>4',             sz: 'キル', k: 'nde',        on: 5,      off: 2,     is: v => v != null && +v > 4 },
  { n: '利払キル intcov<3',          sz: 'キル', k: 'intcov',     on: 2,      off: 8,     is: v => v != null && +v < 3 },
  { n: '債務超過キル eq=neg',        sz: 'キル', k: 'eq',         on: 'neg',  off: 'pos', is: v => v === 'neg' },
  { n: '倒産圏キル Z<1.1',           sz: 'キル', k: 'z',          on: 0.5,    off: 4,     is: v => v != null && +v < 1.1 },
  { n: '価値破壊キル ROIC≤WACC',     sz: 'キル', k: 'roic',       on: 2,      off: 40,    is: (v, d) => v != null && +v <= 11 },
  { n: '複利停止キル ROIIC³<WACC',   sz: 'キル', k: 'roiic',      on: 2,      off: 40,    is: v => v != null && v !== 'na' && +v < 11 },
  { n: '堀の減衰キル moatdecay',     sz: 'キル', k: 'moatdecay',  on: 'yes',  off: 'no',  is: v => v === 'yes' },
  { n: '期限型独占キル expiry',      sz: 'キル', k: 'expiry',     on: 'yes',  off: 'no',  is: v => v === 'yes' },
  { n: 'ROIIC³ WACC近傍 −8',         sz: '−8',  k: 'roiic',      on: 10,     off: 40,    is: v => v != null && v !== 'na' && +v >= 11 && +v < 13 },
  { n: 'アクルーアル accr>10',       sz: 'p4減', k: 'accr',       on: 20,     off: 0,     is: v => v != null && +v > 10 },
  { n: 'シェア趨勢 sht=down',        sz: 'pm−10', k: 'sht',      on: 'down', off: 'flat', is: v => v === 'down' },
  { n: 'シェア趨勢 sht=up',          sz: 'pm+3', k: 'sht',        on: 'up',   off: 'flat', is: v => v === 'up' },
  { n: '粗利趨勢 gmt=down',          sz: 'gmPt−12', k: 'gmt',     on: 'down', off: 'flat', is: v => v === 'down' },
  { n: '侵食 erosion=active',        sz: '段差', k: 'erosion',    on: 'active', off: 'none', is: v => v === 'active' },
  { n: '破壊 disrupt=unsettled',     sz: 'f5段差', k: 'disrupt',  on: 'unsettled', off: 'settled', is: v => v === 'unsettled' },
  { n: '買収の強度 acqS5=買収しない', sz: '−1',  k: 'acqS5',      on: 0,      off: 0.05,  is: v => v != null && +v <= 0 },
  { n: '買収の強度 acqS5=大きく買う', sz: '0',   k: 'acqS5',      on: 0.5,    off: 0.05,  is: v => v != null && +v > 0.311 },
];
// v9.9.194: 文化 gls・純収益維持率 nrr<100 は門から撤去／acq5 の乖離の罰の門は v9.9.183 で罰ごと撤去済み——表から外した
// v9.9.195: Z'' 灰色帯 −6・GP/A<15 −5 を撤去（2026-09-23 事前登録の歴史検定で不合格 → ユーザー明示指示「外して」）——表から外した


// ── その崖に歴史検証があるか（出典つき。**判断を人の頭でなくここに置く**）──────────────
//   'pass' = 歴史で検定して合格 ／ 'fail' = 検定して落ちた（撤去済みのものと、落ちたが門に残っているものがある）
//   'none' = **検定していない** ／ 'null' = 検定したが効果が見つからなかった（それでも残っている）
const TESTED = {
  '財務キル nde>4':            ['pass', '2026-08-13 層0の653社・恒久毀損の濃縮 2.82倍（ARCHIVE:6774）'],
  '利払キル intcov<3':         ['pass', '2026-08-13 同母集団・濃縮 11.0倍＝nde>4より左尾をよく分ける（ARCHIVE:6774/6962）'],
  '買収の強度 acqS5=買収しない': ['pass', '2026-09-21 7ビンテージ・平均順位3.43位（ARCHIVE:14804/14864）'],
  '買収の強度 acqS5=大きく買う': ['pass', '同上・平均順位3.43位'],
  '債務超過キル eq=neg':       ['pass', '2026-09-23 事前登録(8d260d9a)・**2018の1ビンテージだけ**で両方向（中央値2.8% vs 6.9%・毀損1.6倍）。2013/2015は該当6〜7社で群が薄く判定外＝弱い合格（night/retro_kills2_test.py）'],
  '倒産圏キル Z<1.1':          ['fail', "2026-09-23 事前登録(8d260d9a)・2013/2018は両方向（毀損2.8〜2.9倍）だが **2015で毀損が逆**（止めた群41社の毀損0件）＝全ビンテージの基準に届かず（retro_kills2_test）"],
  '価値破壊キル ROIC≤WACC':    ['pass', '2026-09-21 事前登録(4149bd0)・3ビンテージとも中央値が低く恒久毀損が1.9〜2.8倍濃い（ARCHIVE:15036）'],
  '複利停止キル ROIIC³<WACC':  ['fail', '2026-09-23 事前登録(46aa6537)・**2018 は両方向**（中央値4.9% vs 7.8%・毀損2.8倍）／2015 は中央値が逆（両群とも毀損0件）／2013 は算出できた社が少なく止めた群0社＝判定外（night/retro_kills3_test.py）'],
  'ROIIC³ WACC近傍 −8':        ['none', '同上。二値の崖'],
  '堀の減衰キル moatdecay':    ['none', '検定なし。判定圏の発火0社'],
  '期限型独占キル expiry':     ['none', '検定なし。OLED 1社でしか立ったことがない'],
  'アクルーアル accr>10':      ['null', '2026-09-19 の候補38本に accr が入り **lift ±0.00**（ARCHIVE:12821/1364）'],
  'シェア趨勢 sht=down':       ['fail', '2026-09-23 事前登録(46aa6537)・**2013/2018 は両方向**（毀損3.1倍/2.6倍）。2015 は中央値は低いが両群とも毀損0件で基準に届かず＝弱いが向きは正しい（retro_kills3_test）'],
  'シェア趨勢 sht=up':         ['fail', '2026-09-23 事前登録・**3ビンテージとも逆向き**（up のほうが中央値が低く毀損が濃い 0.022/0.021/0.082 vs 0.017/0/0.033）＝歴史は +3 を支持しない'],
  '粗利趨勢 gmt=down':         ['fail', '2026-08-18 事前登録(4c6f6e3)で営業利益率の5年差 opmD5<0 を8ビンテージ検定・**H1 不合格**（8年中2年で符号が逆）／**H5 符号は5年後に持続しない**（ARCHIVE:9311）。⚠ gmt は審査官の±1pt判定で opmD5<0 と同一ではない＝代理'],
  '侵食 erosion=active':      ['none', '**「dep/erosion/disrupt は歴史に無い」と台帳自身が明記**（ARCHIVE:5371）'],
  '破壊 disrupt=unsettled':   ['none', '2026-09-21 に検定を試みたが**検定できなかった**（歴史側に disrupt が無い・ARCHIVE:15036 ②）'],
};
const MARK = { pass: '✓検定済', fail: '✗落ちた', none: '**未検定**', null: '△効果なし' };

const packs = fs.readdirSync(path.join(BASE, 'out')).filter(f => f.endsWith('_gate_pack.json'))
  .map(f => ({ t: f.replace('_gate_pack.json', ''), d: JSON.parse(fs.readFileSync(path.join(BASE, 'out', f), 'utf8')) }));
const num = (r) => Number(r && r.evalScore);
const base = {};
for (const p of packs) { try { base[p.t] = num(SA.scorePack(p.d)); } catch (e) {} }
{ // 自己検問——Ωが取れない行があれば大声で止まる（audit_acq_pen.js で二度踏んだ）
  const bad = Object.values(base).filter(v => !isFinite(v));
  if (bad.length || !Object.keys(base).length) { console.error('✗ Ωを取れなかった。検査器が壊れている——結果を使うな'); process.exit(2); }
}
const zone = packs.filter(p => ALL || base[p.t] >= 72);
console.log(`■ 崖の検査　対象 ${zone.length}社（${ALL ? '全件' : '判定圏 Ω72+'}）・母集団 ${packs.length}社\n`);
console.log('規則'.padEnd(34) + '設計値'.padEnd(8) + '今 発火'.padStart(7) + '   ΔΩ(中央/最大)'.padEnd(20) + '歴史検証');
const out = [];
for (const R of RULES) {
  let fire = 0; const deltas = [];
  for (const p of zone) {
    const cur = p.d[R.k];
    // ⚠ 発火判定は規則ごとの述語で持つ。初版は on の型から推測しており、
    //   **nrr=105 を「nrr<100」として35社**と数えるなど逆向きの嘘を出した
    const isOn = R.is(cur, p.d);
    if (isOn) fire++;
    // ΔΩ = 発火させた版 − 発火させない版（同じ社で両方を作る＝その社の他の条件は固定）
    const mk = (v) => { const c = JSON.parse(JSON.stringify(p.d)); c[R.k] = v; try { return num(SA.scorePack(c)); } catch (e) { return NaN; } };
    const on = mk(R.on), off = mk(R.off);
    if (isFinite(on) && isFinite(off)) deltas.push(on - off);
  }
  deltas.sort((a, b) => a - b);
  const med = deltas.length ? deltas[deltas.length >> 1] : NaN;
  const mx = deltas.length ? deltas[0] : NaN;   // 最も大きく下げるもの
  out.push({ R, fire, med, mx });
  const tv = TESTED[R.n] || ['none', '(表に無い)'];
  console.log(R.n.padEnd(34) + String(R.sz).padEnd(8) + String(fire).padStart(5) + '社  ' +
    (isFinite(med) ? `${med >= 0 ? '+' : ''}${med.toFixed(1)} / ${mx.toFixed(1)}pt` : '—').padEnd(18) + MARK[tv[0]]);
  out[out.length - 1].tv = tv;
}
// 未検定のうち「今きいている」ものを名指しで出す＝作業リスト
const live = out.filter(o => o.tv[0] === 'none' && (o.fire > 0 || Math.abs(o.mx) >= 5));
console.log(`\n■ **未検定の崖のうち、今きいている／きけば大きいもの ${live.length}本**`);
for (const o of live)
  console.log(`  ・${o.R.n}（${o.R.sz}）発火${o.fire}社 / 最大 ${o.mx.toFixed(1)}pt —— ${o.tv[1]}`);
console.log('\n※「今 発火」＝いまその値を持っている社数。「ΔΩ」＝同じ社で発火/非発火の両方を作った差。');
console.log('※ 大きさが 0.0pt の規則は、判定圏では**空回り**しているか、他の罰に飲まれている。');
