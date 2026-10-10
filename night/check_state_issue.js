#!/usr/bin/env node
/**
 * night/check_state_issue.js — 門の「🚀 GitHub を開いて反映する」（Issue 経由で repo の state.json を更新する道・v9.9.210）を実ブラウザで確かめる
 *
 * 何の道か: 門（静的ページ）からは鍵なしで repo へ書けない。そこで ① 門が「新規 Issue」のリンクを作る → ② 人が GitHub で1回押す →
 *   ③ Actions（night/apply_state_issue.py）が検査して state.json を更新する。ここは ① と ④（戻ってきて追いつく）を見る。
 *   ③ のサーバー側は night/check_state_issue.py（オフライン）が見る。**この検査は ① のリンクを本物の Python に通して往復させる**（二つの実装の継ぎ目）。
 *
 * 見ること:
 *   A 自由記述の検問: 共有ベクトル night/state_issue_vectors.json の全件で、JS（ccfState.unseenText）が Python と同じ答え（rule 9 の核心）
 *   B リンクの往復: 買い増し → リンク → 本物の apply_state_issue.py → state.json に入り、端末の値と1バイトも違わない（z / d / p の3種の符号）
 *      ・二重に送っても二重には入らない・repo が先に変わっていたら止める・自分の前の送信の上には重ねられる・差が無ければ作らない
 *      ・repo に無い自由記述があればリンクを作らない（Issue は公開）・長すぎれば作らない・機械しか書かないキーは同乗し、長ければ外す
 *   C 門が本当に作る記録（買い・売り・投資信託）は検問を通る／手で打った売却メモは止まる（従来の道へ）
 *   D 画面: 赤い帯（開くと緑の枠）・記録の直後・📈成績の差の表示に出る／押すと新しいタブで GitHub／戻ると自動で追いつく／「↻ 確認」
 *   E 鍵なし: api.github.com へ一度も出ない・端末に鍵を置かない・state.js に GitHub API の呼び出しが無い
 *
 * ★データは**この検査の中で固定**する（repo の state.json を route で差し替える）。名前は A / B（絶対のルール9）。
 *
 * 使い方: NODE_PATH=$(npm root -g) node night/check_state_issue.js     前提: playwright と Chromium・python3。終了コード 1 = 1件でも ✗
 */
const { spawnSync } = require('child_process');
const http = require('http'), fs = require('fs'), path = require('path'), os = require('os'), zlib = require('zlib'), crypto = require('crypto');
const ROOT = path.dirname(__dirname), PORT = 8986;
const CHROME = process.env.CHROME_PATH || ['/opt/pw-browsers/chromium', '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => fs.existsSync(p));   // 無ければ playwright の既定（CI）
let chromium; try { ({ chromium } = require('playwright')); } catch (e) { console.error('playwright が無い。NODE_PATH=$(npm root -g) を付けるか `npm i playwright`'); process.exit(2); }

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓ ' + m); } else { fail++; console.log('  ✗ ' + m); } };
const clone = o => JSON.parse(JSON.stringify(o));
const sha = s => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
const jr = (r, o) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(o) });
const ST = JSON.parse(fs.readFileSync(path.join(ROOT, 'state.json'), 'utf8'));
const OWNER = 'touchme1956';

const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  let f = path.join(ROOT, rel);
  if (f.endsWith('/')) f += 'index.html';
  try {
    const b = fs.readFileSync(f);
    r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.json') ? 'application/json' : f.endsWith('.css') ? 'text/css'
      : f.endsWith('.jpg') ? 'image/jpeg' : f.endsWith('.png') ? 'image/png' : f.endsWith('.svg') ? 'image/svg+xml' : 'text/html' });
    r.end(b);
  } catch (e) { r.writeHead(404); r.end('x'); }
});

// ── Node 側で依頼を独立に読む（JS 側の符号化の検算）と、本物の Python（サーバー）に通す
function decodeBody(body) {
  const m = String(body).match(/```ccf-state\r?\n([\s\S]*?)\r?\n?```/); if (!m) return null;
  const blk = m[1].replace(/\s+/g, ''), i = blk.indexOf('.'), enc = blk.slice(0, i);
  let buf = Buffer.from(blk.slice(i + 1).replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  if (enc === 'z') buf = zlib.inflateRawSync(buf); else if (enc === 'd') buf = zlib.inflateSync(buf);
  return { enc, payload: JSON.parse(buf.toString('utf8')) };
}
function runApply(urlStr, repoState, o = {}) {
  const u = new URL(urlStr);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ccf_si_'));
  const st = path.join(dir, 'state.json'), ev = path.join(dir, 'event.json'), out = path.join(dir, 'out.txt'), msg = path.join(dir, 'msg.md');
  fs.writeFileSync(st, JSON.stringify(repoState, null, 1) + '\n');
  // GitHub は本文を CRLF にして保存する（textarea の仕様）。それでも読めることも確かめる
  const body = (o.body != null ? o.body : u.searchParams.get('body')).replace(/\r?\n/g, '\r\n');
  fs.writeFileSync(ev, JSON.stringify({ issue: { number: 7, user: { login: o.login || OWNER }, title: u.searchParams.get('title'), body } }));
  const env = Object.assign({}, process.env, { GITHUB_EVENT_PATH: ev, GITHUB_REPOSITORY_OWNER: OWNER, GITHUB_OUTPUT: out, CCF_MSG_PATH: msg, CCF_STATE_PATH: st });
  const r = spawnSync('python3', [path.join(ROOT, 'night', 'apply_state_issue.py')], { env, encoding: 'utf8' });
  const kv = {}; try { fs.readFileSync(out, 'utf8').split('\n').forEach(l => { const i = l.indexOf('='); if (i > 0) kv[l.slice(0, i)] = l.slice(i + 1); }); } catch (e) {}
  let state = null; try { state = JSON.parse(fs.readFileSync(st, 'utf8')); } catch (e) {}
  return { code: r.status, stderr: r.stderr, status: kv.status, why: kv.code, redact: kv.redact === 'true', keys: (kv.keys || '').split(',').filter(Boolean), state,
           msg: fs.existsSync(msg) ? fs.readFileSync(msg, 'utf8') : '' };
}

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const browser = await chromium.launch(CHROME ? { executablePath: CHROME } : {});
  const errs = [], apiReqs = [], ghReqs = [];
  let REPO = clone(ST);

  async function open(o = {}) {
    const ctx = await browser.newContext({ viewport: { width: o.w || 360, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript(() => { try { if (!localStorage.getItem('ccf_theme')) localStorage.setItem('ccf_theme', 'light'); } catch (e) {} });
    if (o.init) await ctx.addInitScript(o.init);
    await ctx.route('**/*', r => {
      const u = r.request().url();
      if (/^https?:\/\/api\.github\.com\//.test(u)) { apiReqs.push(u); return r.abort(); }
      if (/^https:\/\/github\.com\//.test(u)) { ghReqs.push(u); return r.fulfill({ status: 200, contentType: 'text/html', body: '<title>stub</title>' }); }
      if (!/^http:\/\/localhost/.test(u)) return r.abort();
      if (/\/state\.json(\?|$)/.test(u)) return jr(r, REPO);
      if (o.returns && /out\/returns\.json/.test(u)) return o.returns === 'none' ? r.fulfill({ status: 404, body: '' }) : jr(r, o.returns);
      return r.continue();
    });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1500);
    return { p, ctx };
  }
  const seed = (p, device, savedAt, dirty) => p.evaluate(([d, s, dirty]) => {
    localStorage.clear();
    for (const k in d) localStorage.setItem(k, d[k]);
    if (s) localStorage.setItem('ccf:stateSavedAt', s);
    if (dirty) localStorage.setItem('ccf:stateDirty', '1'); else localStorage.removeItem('ccf:stateDirty');
  }, [device, savedAt, dirty]);
  async function openWith(device, savedAt, dirty, o) {   // 端末を作ってから読み込み直す（起動時の load と帯まで通す）
    const x = await open(o);
    await seed(x.p, device, savedAt, dirty);
    await x.p.reload({ waitUntil: 'domcontentloaded' }); await x.p.waitForTimeout(1800);
    return x;
  }
  const prep = p => p.evaluate(() => ccfState.prepareIssue());
  const dev = (mod) => { const d = Object.assign({}, ST.data); if (mod) mod(d); return d; };
  const withPf = (d, fn) => { const o = JSON.parse(d['pf:portfolio']); fn(o); d['pf:portfolio'] = JSON.stringify(o); };
  const NEWLOT = { sh: 1, jpy: 80000, bd: '2026-10-10', who: 'A', acct: '成長', src: '門の🏦保有で記録（約定日 2026-10-10）（A・成長）' };
  const buyMsft = d => withPf(d, o => { const p = o.positions.find(x => x.t === 'MSFT'); p.bdLots.push(clone(NEWLOT)); p.sh += 1; p.bjpy += 80000; });

  try {
    // ════════════════════════════════════════════════════════════════════════
    console.log('■ A. 自由記述の検問（JS = Python）');
    {
      const { p, ctx } = await open();
      const V = JSON.parse(fs.readFileSync(path.join(ROOT, 'night', 'state_issue_vectors.json'), 'utf8'));
      const ser = o => typeof o === 'string' ? o : JSON.stringify(o);
      const toStr = m => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, ser(v)]));
      const repoS = toStr(V.repo);
      let bad = 0;
      for (const c of V.cases) {
        const got = await p.evaluate(([send, repo]) => ccfState.unseenText(send, repo), [toStr(c.send), repoS]);
        const same = JSON.stringify([...got].sort()) === JSON.stringify([...c.expect].sort());
        if (!same) { bad++; ok(false, `ベクトル「${c.name}」: 期待 ${JSON.stringify(c.expect)} / JS ${JSON.stringify(got)}`); }
      }
      ok(bad === 0, `共有ベクトル ${V.cases.length} 件がすべて Python と同じ答え（名前の入りうる古い文・定型・数字の欄・全角/アラビア数字・行末の改行）`);
      // 定数の一致（表は二箇所にある）
      const py = spawnSync('python3', ['-c', 'import sys,json;sys.path.insert(0,"night");import apply_state_issue as A;print(json.dumps({"strict":sorted(A.STRICT_FIELDS),"free":sorted(A.FREE_FIELDS),"enum":sorted(A.ENUM_OK),"plain":sorted(__import__("state_keys").PLAIN_NUMBER_KEYS),"sep":A.SEG_SEP}))'], { cwd: ROOT, encoding: 'utf8' });
      const P = JSON.parse(py.stdout || '{}');
      const J = await p.evaluate(() => ccfState.guardConsts ? ccfState.guardConsts() : null);
      ok(J && JSON.stringify(P.strict) === JSON.stringify(J.strict) && JSON.stringify(P.free) === JSON.stringify(J.free) && JSON.stringify(P.enum) === JSON.stringify(J.enum) &&
         JSON.stringify(P.plain) === JSON.stringify(J.plain) && P.sep === J.sep, '欄の表・既知の区分名・数字だけの欄・区切りの文字が Python と JS で同じ');
      await ctx.close();
    }

    // ════════════════════════════════════════════════════════════════════════
    console.log('■ B. リンクの往復（端末 → リンク → 本物の apply_state_issue.py → state.json）');
    let B1;
    {
      REPO = clone(ST);
      const device = dev(buyMsft);
      const { p, ctx } = await openWith(device, ST.savedAt, true);
      const r = await prep(p);
      ok(r.ok === true && /株数/.test(r.labels.join('・')), `買い増し（MSFT +1ロット）でリンクが作れる（labels ${r.ok ? r.labels.join('・') : JSON.stringify(r)}）`);
      const u = new URL(r.url);
      ok(u.origin + u.pathname === `https://github.com/${OWNER}/ccf-gate/issues/new`, `宛先は新規 Issue（${u.origin + u.pathname}）`);
      const title = u.searchParams.get('title'), body = u.searchParams.get('body');
      ok(title.startsWith('[ccf-state]') && /株数/.test(title), `題名は [ccf-state] で始まり対象を言う（${title}）`);
      ok(/Submit new issue/.test(body) && /```ccf-state\n[zdp]\./.test(body), '本文は「Submit new issue を押してください」と ```ccf-state の囲み');
      ok(r.len <= 7000, `URL は ${r.len} 字（上限 7000）`);
      console.log(`    （実データで URL ${r.len} 字・符号 ${decodeBody(body).enc}）`);
      const dec = decodeBody(body);
      const dj = JSON.parse(dec.payload.dataJson);
      const devNow = await p.evaluate(() => localStorage.getItem('pf:portfolio'));     // 起動時に盤の株価（npx）が書き戻されうるので、種ではなく今の端末の値と比べる
      ok(dec.payload.fmt === 'ccf-state-issue' && dec.payload.ver === 1 && dec.payload.sha === sha(dec.payload.dataJson), 'Node で独立に読み直すと fmt / ver / sha256 が合う');
      ok(Object.keys(dj).includes('pf:portfolio') && dj['pf:portfolio'] === devNow, '送る値は端末の文字列そのまま（1バイトも違わない）');
      ok(dec.payload.bases['pf:portfolio'][0] === sha(ST.data['pf:portfolio']), '前提（bases）は「今の repo の値」のハッシュ');
      ok(!Object.keys(dj).some(k => !['pf:portfolio', 'pf:weights', 'g7ignite:map'].includes(k)), `送るキーは差のあるものだけ（${Object.keys(dj).join(', ')}）`);
      // 本物の Python へ
      const a = runApply(r.url, REPO);
      ok(a.status === 'applied' && a.keys.includes('pf:portfolio'), `本物の apply_state_issue.py が受け付けた（status=${a.status} code=${a.why} keys=${a.keys}）${a.status === 'applied' ? '' : '\n' + a.msg + a.stderr}`);
      ok(a.state && a.state.data['pf:portfolio'] === devNow, 'state.json の株数は端末の値と一致');
      ok(a.state && a.state.savedAt > ST.savedAt && Object.keys(a.state).join() === Object.keys(ST).join() && a.state.note === ST.note && a.state.asof === ST.asof, 'savedAt が進み、ほかの欄（note / asof）と並びは動かない');
      ok(a.state && ['pf:sold', 'pf:monthly'].every(k => a.state.data[k] === ST.data[k]), '送っていないキー（売却記録・今月の個別枠）は1バイトも動かない');
      ok(a.redact === false && !/依頼の本文は.*削除/.test(a.msg), '受け付けたときは本文を消さない');
      B1 = { url: r.url, applied: a.state, device };
      // 二重に送っても二重には入らない
      const a2 = runApply(r.url, a.state);
      ok(a2.status === 'noop', `同じ依頼をもう一度流しても「変更なし」（${a2.status}）`);
      // repo が先に変わっていたら止める
      const moved = clone(ST); const pfm = JSON.parse(moved.data['pf:portfolio']); pfm.positions.find(x => x.t === 'ASML').sh += 1; moved.data['pf:portfolio'] = JSON.stringify(pfm); moved.savedAt = '2026-10-10T00:00:00.000Z';
      const a3 = runApply(r.url, moved);
      ok(a3.status === 'rejected' && a3.why === 'conflict', `作った後に repo が変わっていたら、サーバーも止める（${a3.status}/${a3.why}）`);
      // 端末に記録が残る
      const sent = await p.evaluate(() => ({ s: JSON.parse(localStorage.getItem('ccf:stateSent') || 'null'), at: +localStorage.getItem('ccf:stateSentAt') || 0 }));
      ok(sent.s && sent.s['pf:portfolio'] && sent.s['pf:portfolio'][0] === sha(devNow) && sent.at > 0, '送った値のハッシュと時刻を端末に控える（次の安全確認に使う）');
      await ctx.close();
    }
    {
      // 符号の3種（z は上、d / p）。小さな依頼で（p は URL が長くなるので）
      for (const [name, init, enc] of [
        ['d（zlib・deflate-raw が使えない端末）', () => { const O = window.CompressionStream; window.CompressionStream = function (f) { if (f === 'deflate-raw') throw new TypeError('unsupported'); return new O(f); }; }, 'd'],
        ['p（無圧縮・CompressionStream が無い端末）', () => { window.CompressionStream = undefined; }, 'p']]) {
        REPO = { fmt: 'ccf-state', ver: 1, savedAt: '2026-10-08T00:00:00.000Z', note: 'x', data: { 'pf:monthly_total': '100000' } };
        const { p, ctx } = await open({ init });
        await seed(p, { 'pf:monthly_total': '170000' }, REPO.savedAt, true);
        const r = await prep(p);
        const dec = r.ok ? decodeBody(new URL(r.url).searchParams.get('body')) : null;
        ok(r.ok && dec && dec.enc === enc, `${name}: 符号の頭が ${enc}`);
        const a = r.ok ? runApply(r.url, REPO) : {};
        ok(a.status === 'applied' && a.state.data['pf:monthly_total'] === '170000', `${name}: 本物の Python が読めて入る（${a.status}）`);
        await ctx.close();
      }
    }
    {
      // 差が無い・機械の書き戻しだけの差
      REPO = clone(ST);
      let { p, ctx } = await openWith(dev(), ST.savedAt, false);
      let r = await prep(p);
      ok(r.ok === false && r.why === 'none', `端末が repo と同じなら作らない（${r.why}）`);
      const d2 = dev(d => withPf(d, o => { o.fx = 999; o.positions.forEach(x => { x.npx = 12.34; x.npxAuto = '2026-10-10'; }); }));
      await seed(p, d2, ST.savedAt, false);
      r = await prep(p);
      ok(r.ok === false && r.why === 'none', `盤の株価・ドル円の書き戻し（fx / npx / npxAuto）だけの差は数えない（${r.why}）`);
      const d3 = dev(d => { d['pf:weights'] = JSON.stringify({ total: 1, city: 0.123 }); d['g7ignite:map'] = JSON.stringify({ NEW: '2026-10-10' }); });
      await seed(p, d3, ST.savedAt, false);
      r = await prep(p);
      ok(r.ok === false && r.why === 'none', `機械しか書かないキー（目標ウェイト・点灯日）だけの差では作らない（${r.why}）`);
      await ctx.close();
    }
    {
      // 目標ウェイト・点灯日は、人の決定を送るときだけ同乗する。長すぎれば外す
      REPO = clone(ST);
      const mod = d => { buyMsft(d); d['pf:weights'] = JSON.stringify({ total: 1, city: 0.123 }); d['g7ignite:map'] = JSON.stringify({ NEW: '2026-10-10' }); };
      let { p, ctx } = await openWith(dev(mod), ST.savedAt, true);
      let r = await prep(p);
      ok(r.ok && r.derived === true && r.keys.includes('g7ignite:map') && r.keys.includes('pf:weights'), `人の決定を送るときは目標ウェイト・点灯日の写しも同乗する（${r.keys}）`);
      const a = runApply(r.url, REPO);
      ok(a.status === 'applied' && JSON.parse(a.state.data['g7ignite:map']).NEW === '2026-10-10', '同乗した点灯日も入る');
      // 同乗する機械のキーに未知の日本語があっても、人の決定は止めない（同乗だけ外す）
      await seed(p, dev(d => { buyMsft(d); d['g7ignite:map'] = JSON.stringify({ NEW: 'テスト氏メモ' }); }), ST.savedAt, true);
      r = await prep(p);
      ok(r.ok && !r.keys.includes('g7ignite:map') && r.keys.includes('pf:portfolio'), `同乗の点灯日に未知の文があるときは、同乗だけ外して人の決定は送る（${r.ok ? r.keys : r.why}）`);
      const big = JSON.stringify(Object.fromEntries(Array.from({ length: 700 }, (_, i) => ['T' + i, crypto.randomBytes(9).toString('hex')])));
      await seed(p, dev(d => { buyMsft(d); d['g7ignite:map'] = big; }), ST.savedAt, true);
      r = await prep(p);
      ok(r.ok && r.derived === false && !r.keys.includes('g7ignite:map') && r.len <= 7000, `点灯日が大きすぎてリンクに入らないときは同乗を外し、人の決定だけ送る（${r.keys}・${r.len}字）`);
      await ctx.close();
    }
    {
      // repo が先に変わっている／自分の前の送信の上には重ねられる
      REPO = clone(ST);
      const device = dev(buyMsft);
      let { p, ctx } = await openWith(device, ST.savedAt, true);
      // (1) 別の端末や Claude が先に株数を変えた: 端末の最後の同期の印と repo の印が違い、repo の値は自分が送ったものでもない
      const moved = clone(ST); const pfm = JSON.parse(moved.data['pf:portfolio']); pfm.positions.find(x => x.t === 'ASML').sh += 1;
      moved.data['pf:portfolio'] = JSON.stringify(pfm); moved.savedAt = '2026-10-10T00:00:00.000Z'; REPO = moved;
      let r = await prep(p);
      ok(r.ok === false && r.why === 'behind' && /株数/.test((r.labels || []).join('・')), `repo が先に更新されていたら送らない（${r.why}・${(r.labels || []).join('・')}）`);
      const sent0 = await p.evaluate(() => localStorage.getItem('ccf:stateSent'));
      ok(sent0 === null, '止めたときは「送った」控えを作らない');
      // (2) 自分の前の送信が入った後に、さらに記録した: repo の値は自分が送ったもの
      REPO = clone(ST);
      await seed(p, device, ST.savedAt, true);
      r = await prep(p); ok(r.ok, '（準備）1回目のリンクを作る');
      const applied = runApply(r.url, REPO).state; REPO = applied;                  // Action が入れた
      const d2 = Object.assign({}, device); withPf(d2, o => { const x = o.positions.find(y => y.t === 'MSFT'); x.bdLots.push(Object.assign(clone(NEWLOT), { jpy: 81000, bd: '2026-10-11', src: '門の🏦保有で記録（約定日 2026-10-11）（A・成長）' })); x.sh += 1; });
      // 端末の印はまだ古い（取り込む前）。controls: 控えが無ければ止まるはず
      await p.evaluate(([d]) => { for (const k in d) localStorage.setItem(k, d[k]); }, [d2]);
      r = await prep(p);
      ok(r.ok === true, '自分が前に送った値が repo に入っているなら、その上に重ねて送れる（控えのハッシュ一致）');
      if (r.ok) { const a = runApply(r.url, REPO); ok(a.status === 'applied', `重ねた依頼を本物の Python が受け付ける（${a.status}）`); }
      await p.evaluate(() => { localStorage.removeItem('ccf:stateSent'); });
      r = await prep(p);
      ok(r.ok === false && r.why === 'behind', `控えが無ければ（他人の更新と区別がつかないので）止める（${r.why}）`);
      await ctx.close();
    }
    {
      // Pages の反映が遅れて古い state.json を読んだ日: 前の送信はもう入っているのに、画面は古い repo を見ている
      REPO = clone(ST);
      const { p, ctx } = await openWith(dev(buyMsft), ST.savedAt, true);
      const r1 = await prep(p);
      const NEW = runApply(r1.url, REPO).state;                         // Action は入れた。だが REPO（画面が読む側）はまだ古いまま
      ok(NEW && NEW.savedAt > ST.savedAt, '（準備）1回目の依頼が入った（画面はまだ古い state.json を読んでいる）');
      await p.evaluate(() => { const o = JSON.parse(localStorage.getItem('pf:portfolio')); const m = o.positions.find(x => x.t === 'MSFT'); m.bdLots.push({ sh: 1, jpy: 81000, bd: '2026-10-11', who: 'A', acct: '成長', src: '門の🏦保有で記録（約定日 2026-10-11）（A・成長）' }); m.sh += 1; localStorage.setItem('pf:portfolio', JSON.stringify(o)); });
      const r2 = await prep(p);
      ok(r2.ok === true, '古い state.json を見ていても、2回目のリンクは作れる');
      const dec2 = decodeBody(new URL(r2.url).searchParams.get('body'));
      ok(dec2.payload.bases['pf:portfolio'].length === 2 && dec2.payload.bases['pf:portfolio'][0] === sha(ST.data['pf:portfolio']) && dec2.payload.bases['pf:portfolio'][1] === sha(NEW.data['pf:portfolio']),
         '前提には「読んだ repo の値」と「自分が前に送った値」の両方が入る');
      const a2 = runApply(r2.url, NEW);
      ok(a2.status === 'applied', `1回目が入った後の repo に対して、サーバーの CAS が通る（${a2.status}/${a2.why}）`);
      await ctx.close();
    }
    {
      // repo にまだ無いキー（pf:net）は重ねてよい
      REPO = clone(ST);
      let { p, ctx } = await openWith(dev(d => { d['pf:net'] = JSON.stringify({ add: { QQQM: { sh: 1 } } }); }), '2020-01-01T00:00:00.000Z', true);
      const r = await prep(p);
      ok(r.ok && r.keys.includes('pf:net'), `repo に無いキーだけなら、印が違っても送れる（${r.ok ? r.keys : r.why}）`);
      const a = r.ok ? runApply(r.url, REPO) : {};
      ok(a.status === 'applied' && !!a.state.data['pf:net'], '新しいキーが state.json に足される（前提は「無い」）');
      await ctx.close();
    }
    {
      // repo に無い自由記述 → リンクを作らない（Issue は作った瞬間に公開される）
      REPO = clone(ST);
      const SECRET = '楽天証券 テスト氏 証券口座 1株';
      const { p, ctx } = await openWith(dev(d => withPf(d, o => { const x = o.positions.find(y => y.t === 'MSFT'); x.bdLots.push(Object.assign(clone(NEWLOT), { src: SECRET })); x.sh += 1; })), ST.savedAt, true);
      const r = await prep(p);
      ok(r.ok === false && r.why === 'text' && r.paths.some(s => /bdLots\[3\]\.src/.test(s)), `repo に無い自由な文があれば、リンクを作らない（${r.why}・${(r.paths || []).join(',')}）`);
      ok(!('url' in r) && !JSON.stringify(r.paths).includes('テスト氏'), '結果にリンクは無く、場所の道筋に中身は入らない');
      const ls = await p.evaluate(() => ({ s: localStorage.getItem('ccf:stateSent'), at: localStorage.getItem('ccf:stateSentAt') }));
      ok(ls.s === null && ls.at === null, '止めたときは「送った」控えを作らない');
      ok(ghReqs.length === 0 && apiReqs.length === 0, 'GitHub へは何も送っていない');
      await ctx.close();
    }
    {
      // 長すぎる
      REPO = clone(ST);
      const junk = Array.from({ length: 400 }, (_, i) => i);
      const { p: p2, ctx: c2 } = await openWith(dev(d => withPf(d, o => { const x = o.positions.find(y => y.t === 'MSFT'); x.bdLots = x.bdLots.concat(junk.map(i => ({ sh: 1, jpy: 1000 + i * 7919, bd: '2026-10-10', who: 'A', acct: '成長', src: '門の🏦保有で記録（約定日 2026-10-10）（A・成長）', usd: Math.random() * 1000 }))); })), ST.savedAt, true);
      const r2 = await prep(p2);
      ok(r2.ok === false && r2.why === 'size' && r2.len > 7000, `定型の記録を大量に足して、圧縮しても 7000字を超えれば「size」で止まる（${r2.why}・${r2.len}字）`);
      await c2.close();
    }

    // ════════════════════════════════════════════════════════════════════════
    console.log('■ C. 門が本当に作る記録は検問を通る（買い・売り・投資信託）');
    {
      const FUNDS = JSON.parse(fs.readFileSync(path.join(ROOT, 'portfolio.json'), 'utf8')).target.ami_funds || {};
      const FKEY = Object.keys(FUNDS)[0];
      const flow = async (kind, setup, label, after) => {
        REPO = clone(ST);
        const { p, ctx } = await openWith(dev(), ST.savedAt, false);
        await p.evaluate(() => showPage(6)); await p.waitForTimeout(900);
        await p.evaluate(k => { const bx = document.getElementById('tradeBox'); bx.innerHTML = ''; bx.dataset.kind = ''; ccfTrade(k); }, kind); await p.waitForTimeout(900);
        await setup(p);
        await p.evaluate(() => { const b = [...document.querySelectorAll('#tradeBox button')].find(x => x.textContent.trim() === '記録する'); b.click(); });
        await p.waitForTimeout(2200);
        const msg = await p.evaluate(() => (document.getElementById('trMsg') || {}).textContent || '');
        const r = await prep(p);
        return { p, ctx, msg, r };
      };
      const pick = (p, t) => p.evaluate(t => { const s = document.getElementById('trT'); s.value = t; s.dispatchEvent(new Event('change')); }, t);
      const fillF = (p, o) => p.evaluate(o => { for (const k in o) { const e = document.getElementById(k); e.value = o[k]; e.dispatchEvent(new Event('input')); } }, o);
      // 買い（個別株・名義と口座を選ぶ）
      let x = await flow('buy', async p => { await pick(p, 'MSFT'); await fillF(p, { trS: 1, trP: 520, trJ: 80000 }); }, '買い');
      ok(/^✓/.test(x.msg), `門で MSFT を買い増すと記録できる（${x.msg.slice(0, 40)}）`);
      ok(x.r.ok === true, `買い増しの記録は検問を通り、リンクになる（${x.r.ok ? x.r.labels.join('・') : x.r.why + ' ' + (x.r.paths || [])}）`);
      const lot = await x.p.evaluate(() => JSON.parse(localStorage.getItem('pf:portfolio')).positions.find(y => y.t === 'MSFT').bdLots.slice(-1)[0]);
      ok(/^門の🏦保有で記録/.test(lot.src), `門が付ける出所の文は定型（${lot.src}）`);
      const a = x.r.ok ? runApply(x.r.url, REPO) : {};
      ok(a.status === 'applied', `本物の Python も受け付ける（${a.status}）`);
      await x.ctx.close();
      // 売り（理由は選ぶだけ・メモは空）
      x = await flow('sell', async p => { await pick(p, 'MSFT'); await fillF(p, { trS: 1, trP: 520 }); }, '売り');
      ok(/^✓/.test(x.msg), `門で MSFT を一部売却できる（${x.msg.slice(0, 40)}）`);
      ok(x.r.ok === true, `売却の記録（pf:sold の自動のメモ・行の note）は検問を通る（${x.r.ok ? x.r.labels.join('・') : x.r.why + ' ' + (x.r.paths || [])}）`);
      const a2 = x.r.ok ? runApply(x.r.url, REPO) : {};
      ok(a2.status === 'applied', `本物の Python も受け付ける（${a2.status}）`);
      await x.ctx.close();
      // 売り（手で打ったメモ）→ 止まる
      x = await flow('sell', async p => { await pick(p, 'MSFT'); await fillF(p, { trS: 1, trP: 520, trM: '手で打ったメモ' }); }, '売り+メモ');
      ok(x.r.ok === false && x.r.why === 'text' && x.r.paths.some(s => /^pf:sold:/.test(s)), `手で打った売却メモは（repo に無い自由記述なので）止まる＝従来の道へ（${x.r.why}・${(x.r.paths || []).join(',')}）`);
      await x.ctx.close();
      // 投資信託（円で記録）
      if (FKEY) {
        x = await flow('buy', async p => { await pick(p, FKEY); await fillF(p, { trFJ: 10000 }); }, '投資信託');
        ok(/^✓/.test(x.msg), `投資信託（${FKEY}）を円で記録できる（${x.msg.slice(0, 40)}）`);
        ok(x.r.ok === true, `投資信託の記録も検問を通る（${x.r.ok ? x.r.labels.join('・') : x.r.why + ' ' + (x.r.paths || [])}）`);
        const a3 = x.r.ok ? runApply(x.r.url, REPO) : {};
        ok(a3.status === 'applied', `本物の Python も受け付ける（${a3.status}）`);
        await x.ctx.close();
      }
      // 記録の直後に、その場に「GitHub を開いて反映する」が出る
      x = await flow('buy', async p => { await pick(p, 'MSFT'); await fillF(p, { trS: 1, trP: 520, trJ: 80000 }); }, '買い');
      const tr = await x.p.evaluate(() => { const a = document.querySelector('#trIssue a.ccfIssueGo'); return { has: !!a, href: a ? a.href : '', text: (document.getElementById('trAfter') || {}).innerText || '' }; });
      ok(tr.has && /^https:\/\/github\.com\/[^/]+\/ccf-gate\/issues\/new\?title=/.test(tr.href), `記録の直後に「🚀 GitHub を開いて反映する」が出る（${tr.href.slice(0, 60)}…）`);
      ok(/Submit new issue/.test(tr.text) && /鍵は要りません/.test(tr.text), '押すだけ・鍵は要りません、と言う');
      // Action が入れたあとで「↻ 反映できたか確認」→ 記録の直後の枠も「repo に入りました」に変わる（赤い帯のように作り直されない場所）
      await x.p.evaluate(() => { window.__synced = 0; window.addEventListener('ccf:synced', () => window.__synced++); });
      REPO = runApply(tr.href, REPO).state;
      await x.p.click('#trIssue button:has-text("反映できたか確認")'); await x.p.waitForTimeout(1800);
      const t2 = await x.p.evaluate(() => ({ box: (document.getElementById('trIssue') || {}).innerText || '', synced: window.__synced, dirty: ccfState.isDirty() }));
      ok(/repo に入りました/.test(t2.box) && t2.synced >= 1 && t2.dirty === false, `入ったあとで確認すると、記録の直後の枠も「repo に入りました」に変わる（${t2.box.replace(/\s+/g, ' ').slice(0, 40)}・ccf:synced ${t2.synced}回）`);
      await x.ctx.close();
    }

    // ════════════════════════════════════════════════════════════════════════
    console.log('■ D. 画面（赤い帯・押すと GitHub が開く・戻ると自動で追いつく）');
    {
      REPO = clone(ST);
      const device = dev(buyMsft);
      const { p, ctx } = await openWith(device, ST.savedAt, true);
      await p.evaluate(() => { window.__synced = 0; window.addEventListener('ccf:synced', () => window.__synced++); });
      const bar = await p.evaluate(() => { const d = document.querySelector('#stateBar details'); return { has: !!d, open: d && d.open, sum: d ? d.querySelector('summary').innerText.replace(/\s+/g, ' ') : '', btn: d ? d.querySelectorAll('button').length : 0 }; });
      ok(bar.has && /未書き出し/.test(bar.sum), `赤い帯が出る（${bar.sum.slice(0, 40)}）`);
      ok(await p.evaluate(() => !document.querySelector('#stateBar .ccfIssueGo')), '閉じたままでは repo を読みに行かない（リンクはまだ作らない）');
      await p.click('#stateBar details summary'); await p.waitForTimeout(1500);
      const w = await p.evaluate(() => { const a = document.querySelector('#stateBar .ccfIssueBox a.ccfIssueGo'); const b = document.querySelector('#stateBar .ccfIssueBox'); return { has: !!a, href: a ? a.href : '', target: a && a.target, rel: a && a.rel, text: b ? b.innerText.replace(/\s+/g, ' ') : '' }; });
      ok(w.has && w.target === '_blank' && /noopener/.test(w.rel), '開くと緑の枠に「🚀 GitHub を開いて反映する」（新しいタブ・noopener）');
      ok(/Submit new issue/.test(w.text) && /鍵は要りません/.test(w.text) && /株数/.test(w.text), `押すだけ・鍵は要りません・送る内容を言う（${w.text.slice(0, 80)}…）`);
      const sw = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
      ok(sw.sw <= sw.cw, `横にはみ出さない（360px・${sw.sw}/${sw.cw}）`);
      // 押す → 新しいタブで GitHub
      const [pop] = await Promise.all([ctx.waitForEvent('page'), p.click('#stateBar .ccfIssueBox a.ccfIssueGo')]);
      await pop.waitForLoadState('domcontentloaded').catch(() => {});
      ok(/^https:\/\/github\.com\/[^/]+\/ccf-gate\/issues\/new\?title=/.test(pop.url()), `新しいタブで GitHub の新規 Issue が開く（${pop.url().slice(0, 64)}…）`);
      const msg1 = await p.evaluate(() => (document.querySelector('#stateBar .ccfIssueMsg') || {}).innerText || '');
      ok(/戻ってください/.test(msg1), `押したあとに「戻ってきたら自動で確認します」と言う（${msg1.slice(0, 50)}…）`);
      await pop.close();
      // まだ入っていない → 確認しても「まだ」
      const href = w.href;
      await p.click('#stateBar .ccfIssueBox button:has-text("反映できたか確認")'); await p.waitForTimeout(1200);
      const m2 = await p.evaluate(() => (document.querySelector('#stateBar .ccfIssueMsg') || {}).innerText || '');
      ok(/まだ入っていません/.test(m2) && await p.evaluate(() => ccfState.isDirty()), `repo にまだ入っていない間は「まだ入っていません」・赤い帯は残る（${m2.slice(0, 40)}…）`);
      // Action が入れた（= REPO が更新される）→ 確認で追いつく
      const a = runApply(href, REPO); REPO = a.state;
      await p.click('#stateBar .ccfIssueBox button:has-text("反映できたか確認")'); await p.waitForTimeout(1800);
      const done = await p.evaluate(() => ({ dirty: ccfState.isDirty(), synced: window.__synced, box: [...document.querySelectorAll('.ccfIssueBox')].map(e => e.innerText.replace(/\s+/g, ' ')).join(' | '),
        sent: localStorage.getItem('ccf:stateSent'), at: localStorage.getItem('ccf:stateSentAt'), mine: localStorage.getItem('ccf:stateSavedAt'), bar: (document.getElementById('stateBar') || {}).innerText || '' }));
      ok(done.dirty === false && done.mine === a.state.savedAt, `repo に入ったら確認で追いつく（dirty 解除・印が repo の savedAt に揃う）`);
      ok(done.synced >= 1, `ccf:synced が出る（${done.synced}回）`);
      ok(done.sent === null && done.at === null, '追いついたら「送った」控えを消す');
      ok(!/未書き出し/.test(done.bar) && done.bar.trim() === '', `追いついたら赤い帯は消える（${JSON.stringify(done.bar.replace(/\s+/g, ' ').slice(0, 40))}）`);
      await ctx.close();
    }
    {
      // 🏦保有（portfolio.html・iframe の中身）の赤い帯にも同じ部品が出る（state.js は二つの文書が別々に読む）
      REPO = clone(ST);
      const { p, ctx } = await openWith(dev(buyMsft), ST.savedAt, true);
      const q = await ctx.newPage(); q.on('pageerror', e => errs.push('PAGEERROR(portfolio) ' + e.message));
      await q.goto(`http://localhost:${PORT}/portfolio.html`, { waitUntil: 'domcontentloaded' }); await q.waitForTimeout(2200);
      const has = await q.evaluate(() => !!document.querySelector('#stateBar details'));
      ok(has, '🏦保有（portfolio.html）にも赤い帯が出る');
      if (has) {
        await q.click('#stateBar details summary'); await q.waitForTimeout(1500);
        const w = await q.evaluate(() => { const a = document.querySelector('#stateBar .ccfIssueBox a.ccfIssueGo'); return { has: !!a, href: a ? a.href : '' }; });
        ok(w.has && /ccf-gate\/issues\/new\?title=/.test(w.href), '🏦保有の赤い帯の中にも「GitHub を開いて反映する」が出る');
        const a = w.has ? runApply(w.href, REPO) : {};
        ok(a.status === 'applied', `そこで作ったリンクも本物の Python が受け付ける（${a.status}）`);
      }
      await ctx.close();
    }
    {
      // 戻ってきたら（visibilitychange）自動で確認する
      REPO = clone(ST);
      const device = dev(buyMsft);
      const { p, ctx } = await openWith(device, ST.savedAt, true);
      const r = await prep(p);
      ok(r.ok, '（準備）リンクを作る');
      REPO = runApply(r.url, REPO).state;                             // Action が入れた
      await p.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
      let done = false; for (let i = 0; i < 20 && !done; i++) { await p.waitForTimeout(300); done = await p.evaluate(() => !ccfState.isDirty()); }
      ok(done, 'GitHub から戻ってきた（visibilitychange）とき、自動で repo を読み直して追いつく');
      await ctx.close();
    }
    {
      // 別の文書（iframe・別タブ）が追いついたら、こちらにも伝わる（SENT_AT が消えるのが合図）
      REPO = clone(ST);
      const device = dev(buyMsft);
      const { p, ctx } = await openWith(device, ST.savedAt, true);
      const r = await prep(p);
      REPO = runApply(r.url, REPO).state;
      await p.evaluate(() => { window.__synced = 0; window.addEventListener('ccf:synced', () => window.__synced++); });
      const p2 = await ctx.newPage(); p2.on('pageerror', e => errs.push('PAGEERROR(p2) ' + e.message));
      await p2.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' }); await p2.waitForTimeout(2200);   // 2枚目が起動時の load で追いつく
      let n = 0; for (let i = 0; i < 20 && !n; i++) { await p.waitForTimeout(300); n = await p.evaluate(() => window.__synced); }
      ok(n >= 1 && await p.evaluate(() => !ccfState.isDirty()), '別のタブが追いついたら、元のタブにも ccf:synced が届き、赤い帯が消える');
      await ctx.close();
    }
    {
      // 見出しの途中: 一度でも「behind」「text」「none」を画面に出せる
      REPO = clone(ST);
      const moved = clone(ST); const pfm = JSON.parse(moved.data['pf:portfolio']); pfm.positions.find(x => x.t === 'ASML').sh += 1; moved.data['pf:portfolio'] = JSON.stringify(pfm); moved.savedAt = '2026-10-10T00:00:00.000Z';
      let { p, ctx } = await openWith(dev(buyMsft), ST.savedAt, true);
      REPO = moved;
      await p.click('#stateBar details summary'); await p.waitForTimeout(1500);
      let t = await p.evaluate(() => ({ box: (document.querySelector('#stateBar .ccfIssueBox') || {}).innerText || '', go: !!document.querySelector('#stateBar .ccfIssueGo') }));
      ok(!t.go && /先に更新されています/.test(t.box) && /書き出す/.test(t.box), `repo が先に更新されているとき、リンクは出さず理由と「📤 書き出す」を言う（${t.box.replace(/\s+/g, ' ').slice(0, 60)}…）`);
      await ctx.close();
      REPO = clone(ST);
      ({ p, ctx } = await openWith(dev(d => withPf(d, o => { const x = o.positions.find(y => y.t === 'MSFT'); x.bdLots.push(Object.assign(clone(NEWLOT), { src: '楽天証券 テスト氏 1株' })); x.sh += 1; })), ST.savedAt, true));
      await p.click('#stateBar details summary'); await p.waitForTimeout(1500);
      t = await p.evaluate(() => ({ box: (document.querySelector('#stateBar .ccfIssueBox') || {}).innerText || '', go: !!document.querySelector('#stateBar .ccfIssueGo'), html: (document.querySelector('#stateBar .ccfIssueBox') || {}).innerHTML || '' }));
      ok(!t.go && /公開の Issue には載せません/.test(t.box) && /書き出す/.test(t.box), `repo に無い自由記述があるとき、リンクは出さず「載せません」と言う（${t.box.replace(/\s+/g, ' ').slice(0, 60)}…）`);
      ok(/bdLots\[3\]\.src/.test(t.box), '場所（欄の道筋）を言う');
      await ctx.close();
    }
    {
      // 📈成績の差の表示にも出る
      const RET = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'returns.json'), 'utf8'));
      REPO = clone(ST);
      const { p, ctx } = await openWith(dev(buyMsft), ST.savedAt, true, { returns: Object.assign({}, RET, { generated: '2026-10-09', positions: RET.positions.map(r => ({ t: r.t, nm: r.nm, sh: r.t === 'MSFT' ? (r.sh || 8) : r.sh })) }) });
      await p.evaluate(() => showPage(12)); await p.waitForTimeout(2600);
      const t = await p.evaluate(() => { const e = document.getElementById('perfSync'), a = document.querySelector('#perfSyncAct a.ccfIssueGo'); return { has: !!e, go: !!a, href: a ? a.href : '', text: e ? e.innerText.replace(/\s+/g, ' ') : '' }; });
      ok(t.has && t.go && /ccf-gate\/issues\/new\?title=/.test(t.href), `📈成績の「この端末の保有と違います」の中に「GitHub を開いて反映する」が出る（${t.text.slice(0, 50)}…）`);
      ok(/MSFT/.test(t.text) && /鍵は要りません/.test(t.text), '違う銘柄を名指しし、鍵は要りません、と言う');
      await ctx.close();
    }

    // ════════════════════════════════════════════════════════════════════════
    console.log('■ E. 鍵なし（GitHub の API を一度も呼ばない・端末に鍵を置かない）');
    {
      const src = fs.readFileSync(path.join(ROOT, 'state.js'), 'utf8');
      ok(!/api\.github\.com|Authorization|ghp_|github_pat_|ccf:ghToken['"]\s*,/.test(src.replace(/localStorage\.removeItem\('ccf:ghToken'\)/g, '')), 'state.js に GitHub API の呼び出し・認証ヘッダ・鍵の保存が無い（過去の鍵を消す removeItem だけ）');
      ok(apiReqs.length === 0, `検査の間、api.github.com へは一度も出ていない（${apiReqs.length}件）`);
      ok(ghReqs.every(u => /^https:\/\/github\.com\/[^/]+\/ccf-gate\/issues\/new\?/.test(u)), `github.com へ出たのは「新規 Issue」の画面だけ（人がリンクを押したときの${ghReqs.length}件）`);
    }
  } finally {
    await browser.close();
    srv.close();
  }
  console.log(errs.length ? `\n（ページ内のJSエラー ${errs.length}件）\n  ` + errs.slice(0, 5).join('\n  ') : '\n（ページ内のJSエラーなし）');
  ok(errs.length === 0, 'pageerror 0件');
  console.log(`\n結果: ✓ ${pass} / ✗ ${fail}`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
