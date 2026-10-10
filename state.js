/* ============================================================================
   state.js — **人の決定を repo に置き、門はそれを読む**（v9.9.131・2026-08-10
   ユーザー明示指示「localStorage → repo これはなに？」→「repoに全部」）

   ■ 何を移すか（**localStorage が正本で repo にコピーが1バイトも無かった6つ**）
       pf:portfolio  … 何株持っているか（Ⅶ資産）
       pf:weights    … 目標ウェイト（配分の決定そのもの）
       pf:sold       … 売却記録
       pf:monthly_total… 今月の入金総額（v9.9.163で新設。**入っていればこれが正本**で、
                        個別枠とETF枠は portfolio.json の target（shiro_castle_pct / ami_net_pct）から導かれる。
                        ⚠**ここに比を書き写さない**——2026-09-18 に 個別50/ETF50 → 個別20/ETF80 へ改定された）
       pf:monthly    … 今月の個別枠
       pf:monthly_net… 今月のETF枠（ETF・v9.9.160で新設）
       pf:net        … ETFの買付の記録（v9.9.168で新設）。**Ⅶ資産は sleeve:'net' の行を
                        読み込み時に削除する**（2026-08-03 ユーザー明示指示「個別銘柄だけに」）ので、
                        ETFの株数は pf:portfolio に置けない。門だけが読む別のキーとして持ち、
                        portfolio.json（静的スナップショット）に重ねて保有%を出す
       g7ignite:map  … 点灯日（Ulysses契約の48時間冷却）
       g7log:…       … Ⅴ検証履歴（**記録であって決定ではない**。大半は⭳一括取込／↻全再採点が
                        自動で残すもので、赤い帯＝dirty は立てない。下の「dirty はどう立つか」）
     台帳 g7: は out/*_gate_pack.json という repo の正本があるので**ここには含めない**
     （含めると「同じものが二箇所に正本を持つ」＝この台帳が最も嫌う型になる）。

   ■ なぜ「読むだけ」なのか（設計の制約を正直に書く）
     門は GitHub Pages の静的ページで、**ブラウザから repo へ書く手段が無い**。
     書けるようにするにはトークンをブラウザに置くことになり、それは絶対にしない。
     よって正本の向きはこうなる:
       repo → 門 … fetch で自動（out/dashboard.json と同じ「CIで作ってJSONで配る」作法）
       門 → repo … **人が書き出してコミットする**（gate_exceptions.json と同じ形）
     つまり「自動で守られる」のではなく「**書き出し忘れが見える**」ようになる。
     見えるようにするのが本体——回転盤(ops_status)が state.json の鮮度を測る。
     ★v9.9.210（2026-10-10 ユーザー明示指示「案1でやってマージして」）: 門→repo の道が**二つ**になった——
       (a) 📤 書き出す → Claude に貼って「反映して」（従来。Claude が目で確かめて commit する）
       (b) 「🚀 GitHub を開いて反映する」（**鍵なし**。門が新規 Issue のリンクを作り、人が GitHub で1回押すと、
           Actions〔.github/workflows/state_from_issue.yml〕が検査して state.json を更新する）。下の「Issue 経由」の節。
       どちらでも**ブラウザに鍵は置かない**。

   ■ 絶対に踏まない事故（この台帳が繰り返し記録している型）
     **新しいほうが古いほうを黙って上書きしてはいけない。**
     キーエンスの「Ⅵ一括取込が台帳のレコードを置き換え、Ⅲ採点機で直した値を無言で巻き戻す」
     とまったく同じ形が、ここでは「repoのstate.jsonが手元の未書き出しの株数を消す」になる。
     だから三重に縛る:
       (1) state.json の savedAt が **null なら何もしない**（未初期化のrepoが手元を消さない）
       (2) 手元に**未書き出しの変更(dirty)があれば採用しない**——警告だけ出す
       (3) 採用は **repo のほうが新しいときだけ**（savedAt を比較する）
     どの分岐でも**黙って消す経路が無い**ことがこの実装の全部。

   ■ dirty はどう立つか
     書き込み地点を一つずつ探して呼び出しを足すと**必ず取りこぼす**ので、
     `localStorage.setItem/removeItem` を包んで**対象キーが書かれたら自動で立てる**。
     `store`（claudeモード）も localStorage へミラーするので、これで全部拾える。
     ⚠ ただし**立てるのは決定の5キーだけ**（decides()）。`g7log:`（検証履歴）は集めはするが
       旗は立てない——⭳全パック一括取込／↻全再採点 が最後に自動で1件書くので、
       **手順書どおりの運用で毎回 赤い帯が出ていた**（2026-08-12 実測・是正）。
     ⚠ そして**旗を信じない**。読み込みのたびに nothingPending() が中身を突き合わせ、
       決定が repo と一致していれば旗を落とす（2026-08-11 に stale を自分で治したのと同じ形）。
   ========================================================================== */
(function () {
  'use strict';

  var EXACT = ['pf:portfolio', 'pf:net', 'pf:weights', 'pf:sold', 'pf:monthly_total', 'pf:monthly', 'pf:monthly_net', 'g7ignite:map'];
  var PREFIX = ['g7log:'];
  var SAVED_AT = 'ccf:stateSavedAt';   // 最後に採用/書き出しした state.json の savedAt
  var DIRTY = 'ccf:stateDirty';        // '1' = 手元に未書き出しの変更がある

  function watched(k) {
    if (!k) return false;
    if (EXACT.indexOf(k) >= 0) return true;
    for (var i = 0; i < PREFIX.length; i++) if (k.indexOf(PREFIX[i]) === 0) return true;
    return false;
  }

  /* ★**集める集合**と**警報を鳴らす集合**は別（2026-08-12・ユーザー「これがでないようにして」）。
     旧実装は watched() 一つで両方を兼ねていたので、**`g7log:`（検証履歴）を書いただけで
     「手元の決定が、まだ repo に入っていません」という赤い帯が出た**。
     ⚠ この帯は手順書どおりの運用で必ず出る——⭳全パック一括取込／↻全再採点 が最後に
        `saveLog({title:'一括再採点 369銘柄'})` を自動で呼び、それが `g7log:` を書くから
        （index.html:2820）。**人は決定を一つも触っていない**。実測: 決定5キーは1バイトも変わらず
        `ccf:stateDirty='1'` だけが立つ。applyDash と同じ「機械の書き戻しで警報が鳴りっぱなし」の型で、
        **鳴りすぎる警報は鳴らないのと同じ**。
     ⚠ そもそも旧実装は筋が通っていなかった——帯が第一に勧める「① 決定だけ（小）」は
        **設計上 `g7log:` を含まない**（collect(core) が外す）。つまり
        「検証履歴で鳴った帯を、検証履歴を含まない書き出しで消す」ことになっていた。
     ⇒ **dirty が守るのは決定（EXACT の5キー）だけ**とはっきりさせる。`g7log:` は記録であって
        決定ではない。書き出し（履歴も）と収集からは外していないので、repo へ入れる道は残る
        （鮮度は回転盤の `state`〔月次〕が測る）。 */
  function decides(k) { return !!k && EXACT.indexOf(k) >= 0; }

  /* ── 書き込みを包んで dirty を自動で立てる（呼び出し地点を探さない） ──
     ⚠ ただし**機械が書き戻す分は数えない**。Ⅶ資産の applyDash は盤(out/dashboard.json)の
     現在株価とドル円を pf:portfolio へ書き戻すので（v9.9.87）、素朴に包むと
     **人が何も触らなくても毎回 dirty が立ち、警告が鳴りっぱなしになる**——
     鳴りすぎる警報は鳴らないのと同じ。機械書き込みは quiet() で囲む。
     失われるのは npx/fx だけで、どちらも盤から再取得できる（人の決定ではない）。 */
  var quietDepth = 0;
  function quiet(fn) { quietDepth++; try { return fn(); } finally { quietDepth--; } }
  try {
    var _set = localStorage.setItem.bind(localStorage);
    var _rm = localStorage.removeItem.bind(localStorage);
    localStorage.setItem = function (k, v) {
      var r = _set(k, v);
      if (decides(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      scheduleHold(k);
      return r;
    };
    localStorage.removeItem = function (k) {
      var r = _rm(k);
      if (decides(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      scheduleHold(k);
      return r;
    };
  } catch (e) {}

  /* ── 保有が変わったら、保有に依る画面を全部つくり直す合図（v9.9.209・2026-10-10 ユーザー「保有に追加したら自動で他にも反映されるようにして。
        他の数値もきちんと自動反映されるような仕組みにして」）──
     旧は、記録した画面が「🏦保有を描き直す・買付順位を描き直す」を**自分で呼んで**いた。呼び出し地点を探して足すと必ず取りこぼす
     （dirty を立てる呼び出しを探さず書き込みを包んだのと同じ理由）ので、**書き込みの包みから一本の合図 `ccf:holdings`** を出し、
     受け取る側（index.html の ccfHoldingsChanged）が保有に依る画面をまとめて作り直す。
     ・対象は 保有(pf:portfolio)・売却記録(pf:sold)・ETFの買付(pf:net) の3つ。**目標ウェイト・入金額・点灯日は含めない**（保有ではない）。
     ・**機械の書き戻しでは鳴らない**: 盤の現在株価とドル円を pf:portfolio へ書き戻す applyDash（v9.9.87）や、取り込み直しで中身が同じなら、
       signature（stripMachine 後の文字列）が変わらないので合図は出ない。人が株数・取得額を動かしたときだけ鳴る。
     ・🏦保有の iframe（portfolio.html）が書いた分は、このページの包みを通らない＝**別の文書の書き込み**なので、ブラウザの storage イベントで拾う。
     ・連続した書き込み（買付で pf:portfolio と pf:sold を続けて書く等）は 60ms にまとめて1回。 */
  var HOLD_KEYS = ['pf:portfolio', 'pf:sold', 'pf:net'];
  var holdSig = {}, holdTimer = null;
  function sigOf(k, v) {
    if (v == null) return '';
    if (k === 'pf:portfolio') { try { return stripMachine(v); } catch (e) {} }   // npx / npxAuto / fx は保有の変更ではない
    return String(v);
  }
  function holdSnap() {
    HOLD_KEYS.forEach(function (k) { try { holdSig[k] = sigOf(k, localStorage.getItem(k)); } catch (e) { holdSig[k] = ''; } });
  }
  function holdNotify() {
    holdTimer = null;
    var ch = [];
    HOLD_KEYS.forEach(function (k) {
      var sg; try { sg = sigOf(k, localStorage.getItem(k)); } catch (e) { return; }
      if (sg !== holdSig[k]) { holdSig[k] = sg; ch.push(k); }
    });
    if (!ch.length) return;
    try { window.dispatchEvent(new CustomEvent('ccf:holdings', { detail: { keys: ch } })); } catch (e) {}
  }
  function scheduleHold(k) {
    if (k != null && HOLD_KEYS.indexOf(k) < 0) return;
    if (!holdTimer) holdTimer = setTimeout(holdNotify, 60);
  }
  holdSnap();
  try { window.addEventListener('storage', function (e) { scheduleHold(e.key); }); } catch (e) {}   // 別の文書（🏦保有の iframe・別のタブ）が書いた分
  /* ★2026-10-10: 過去に「この端末に鍵を置く」で入れた GitHub の鍵（ccf:ghToken）を消す。鍵を置く道そのものを撤去したので、残っていても使われないが、
     端末に認証情報を置いたままにしない。（GitHub 側の鍵は、作った人が Settings → Developer settings で無効にする） */
  try { localStorage.removeItem('ccf:ghToken'); } catch (e) {}

  /* collect(core) — core=true なら **検証履歴(g7log:)を外す**。
     ⚠ これは実害から来た分割（2026-08-10）。**貼り付けで渡すと必ず切れる**——
     `g7log:` は「一括再採点 362銘柄」の全文がそのまま入るので1件で数十KBあり、
     しかも localStorage の並び順でログが先に来るため、**株数(pf:portfolio)が本文に
     現れる前に切れた**（実測）。だから (a)小さい決定だけを別に出せるようにし、
     (b)出力の**並びを重要度順に固定**して、万一切れても先頭に大事なものが載るようにする。
     取り込み側は「data にあるキーだけ書く」ので、小さい方をコミットしても
     手元の検証履歴が消えることはない（**消す経路は無い**）。 */
  var ORDER = ['pf:portfolio', 'pf:net', 'pf:sold', 'pf:weights', 'pf:monthly_total', 'pf:monthly', 'pf:monthly_net', 'g7ignite:map'];
  function collect(core) {
    var all = {}, keys = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!watched(k)) continue;
        if (core && k.indexOf('g7log:') === 0) continue;
        var v = localStorage.getItem(k);
        if (v != null) { all[k] = v; keys.push(k); }
      }
    } catch (e) {}
    keys.sort(function (a, b) {
      var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
      if (ia < 0) ia = 99; if (ib < 0) ib = 99;
      return ia - ib || (a < b ? -1 : a > b ? 1 : 0);
    });
    var d = {};                                  // 重要度順に詰め直す（JSONはこの順で出る）
    keys.forEach(function (k) { d[k] = all[k]; });
    return { data: d, n: keys.length };
  }

  function isDirty() { try { return localStorage.getItem(DIRTY) === '1'; } catch (e) { return false; } }
  function localSavedAt() { try { return localStorage.getItem(SAVED_AT) || null; } catch (e) { return null; } }

  /* 採用の判定だけを純関数にしておく（門と端末が同じ規則を言えるように）。
     戻り値: 'adopt' 採用する / 'dirty' 手元に未書き出しがあるので採用しない /
             'uninit' repoが未初期化 / 'stale' repoのほうが古い / 'same' 同じ */
  function decide(repoSavedAt, mySavedAt, dirty) {
    if (!repoSavedAt) return 'uninit';
    if (dirty) return 'dirty';
    if (!mySavedAt) return 'adopt';
    if (repoSavedAt > mySavedAt) return 'adopt';
    if (repoSavedAt === mySavedAt) return 'same';
    return 'stale';
  }

  /* nothingPending(repoData) — **旗を信じず、中身で確かめる**。
     手元の決定キーが repo の state.json と一つ残らず一致するなら、**書き出すものは定義上ゼロ**。
     ⚠ これは「危ないものを隠す」検査ではない——一つでも食い違えば false を返すので、
        本物の未書き出しは絶対に消えない（片側だけに倒れる）。
     なぜ要るか: 旗は一度立つと書き出すまで落ちないので、**上の欠陥で既に立ってしまった端末**は
     直しただけでは帯が消えない。2026-08-11 に stale を自分で治したのと同じ形で、旗の側も治す。 */
  /* ⚠ **素の文字列比較では一度も一致しない**。決定のファイルに機械の書き戻しが混ざっているから。
     推測せず実測した（2026-08-12・素の読み込み直後に state.json と突き合わせ）——食い違うのは
       pf:portfolio … `fx` と 各行の `npx` / `npxAuto` の**3項目だけ**（盤の現在株価とドル円・v9.9.87）
                      ※ `sh`(株数) `v`(金額) `bpx` は**1件も動かない**＝人の決定は無傷
       pf:weights   … `city`(浮動小数の誤差) と `total`＝**全部が P からの導出値**（portfolio.html:350）
       pf:sold / pf:net / pf:monthly_total / pf:monthly / pf:monthly_net / g7ignite:map … **完全一致**
       ※ pf:net は 2026-08-22 新設。**人しか書かない**（門の◈ETFの「＋株」だけが書き手で、機械の書き戻しは無い）
     ⇒ 落とすのはこの実測どおりの範囲だけにする。**広く落とすと本物の決定を隠す**ので、
        JSONとして読めなければ素の比較へ倒す（片側だけに倒れる）。 */
  /* ⚠2026-08-17 追加: `g7ignite:map`（点灯日）も**機械しか書かない**。
     index.html の renderPlan が、投下可の顔ぶれが変わるたびに点灯日と消灯印を自動で入れる
     ——人が触る UI は一つも無い。ところがここで中身を比べていたため、
     **投下可が動いた日は必ず repo と食い違い、旗が自己修復できず帯が出っぱなし**になった
     （書き込み側は quiet() で囲んだが、既に立ってしまった旗はこちらでしか治せない）。
     ⚠ 書き出しの対象からは外さない——点灯日は out/ に正本が無いので repo へは要る。
       その鮮度は回転盤の `state`（月次）が測る。**赤い帯は「人の決定」だけを守る。** */
  var DERIVED_KEY = { 'pf:weights': 1, 'g7ignite:map': 1 };   // 機械しか書かないキー
  var MACHINE_FLD = { fx: 1, npx: 1, npxAuto: 1 };       // 盤から書き戻される欄
  function stripMachine(v) {
    var o = JSON.parse(v);
    if (o && typeof o === 'object') {
      for (var f in MACHINE_FLD) delete o[f];
      if (Array.isArray(o.positions)) {
        o.positions = o.positions.map(function (p) {
          if (!p || typeof p !== 'object') return p;
          var q = {}; for (var kk in p) if (!MACHINE_FLD[kk]) q[kk] = p[kk];
          return q;
        });
      }
    }
    return JSON.stringify(o);
  }
  function sameDecision(k, mine, theirs) {
    if (mine === theirs) return true;
    if (mine == null || theirs == null) return false;
    try { return stripMachine(mine) === stripMachine(theirs); } catch (e) { return false; }
  }
  /* pendingKeys(repoData) — **どの決定が未書き出しか**を名指しで返す（2026-08-17新設）。
     旧版の帯は「手元の決定が repo に入っていません」としか言わず、**何が未書き出しかを出さなかった**
     ので、読み手には本物か誤検知かが判らなかった（実際その状態でユーザーから「そもそもいるの？」と
     問われた）。判定は nothingPending と同じ sameDecision を使う＝二つの答えが割れない。 */
  var LABEL = { 'pf:portfolio': '株数', 'pf:net': 'ETFの買付記録', 'pf:sold': '売却記録',
                'pf:weights': '目標ウェイト', 'pf:monthly_total': '今月の入金総額',
                'pf:monthly': '今月の個別枠', 'pf:monthly_net': '今月のETF枠', 'g7ignite:map': '点灯日' };
  function pendingKeys(repoData) {
    var out = [];
    try {
      for (var i = 0; i < EXACT.length; i++) {
        var k = EXACT[i];
        if (DERIVED_KEY[k]) continue;                    // 機械しか書かないキーは人の決定ではない
        var mine = localStorage.getItem(k);
        var theirs = (repoData && Object.prototype.hasOwnProperty.call(repoData, k)) ? repoData[k] : null;
        if (mine == null && theirs == null) continue;
        if (!sameDecision(k, mine, theirs)) out.push(LABEL[k] || k);
      }
    } catch (e) { return null; }                          // 測れなければ null（0件と区別する・ルール7）
    return out;
  }

  function nothingPending(repoData) {
    try {
      for (var i = 0; i < EXACT.length; i++) {
        var k = EXACT[i];
        if (DERIVED_KEY[k]) continue;
        var mine = localStorage.getItem(k);
        var theirs = (repoData && Object.prototype.hasOwnProperty.call(repoData, k)) ? repoData[k] : null;
        if (mine == null && theirs == null) continue;
        if (!sameDecision(k, mine, theirs)) return false;   // 一つでも違えば「未書き出しがある」側へ
      }
      return true;
    } catch (e) { return false; }
  }

  var last = null;   // 最後の判定（バナー描画が読む）

  function load() {
    return fetch('state.json?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (s) {
        if (!s || s.fmt !== 'ccf-state') { last = { verdict: 'none' }; return last; }
        // 旗が立っていても、決定が repo と一致しているなら書き出すものは無い＝自分で落とす
        var healed = false;
        if (isDirty() && nothingPending(s.data || {})) {
          try { localStorage.removeItem(DIRTY); healed = true; } catch (e) {}
        }
        var v = decide(s.savedAt || null, localSavedAt(), isDirty());
        var applied = 0;
        if (v === 'adopt') {
          var d = s.data || {};
          quiet(function () {                             // 採用は機械の書き込み＝dirty を立てない
            for (var k in d) {
              if (!watched(k)) continue;                  // 想定外のキーは入れない
              try { localStorage.setItem(k, d[k]); applied++; } catch (e) {}
            }
          });
          // 採用は「書き出し済みの状態に追いついた」ことなので dirty は落とす
          try { localStorage.setItem(SAVED_AT, s.savedAt); localStorage.removeItem(DIRTY); } catch (e) {}
        }
        /* 2026-08-11: **stale は自分で治す**。
           decide() は dirty を stale より先に見るので、stale に来た時点で
           「手元に未書き出しの決定は無い」が確定している＝**人がやることは何も無い**。
           それでも印(savedAt)だけが repo より新しいままだと、以後ずっと帯が出続ける。
           ここで**印だけ repo に合わせる**（data は触らない＝上書きしない）。
           そうすれば次に repo が更新されたとき正しく adopt に入る。 */
        if (v === 'stale' && !isDirty() && s.savedAt) {
          try { localStorage.setItem(SAVED_AT, s.savedAt); } catch (e) {}
          v = 'same';
        }
        last = { verdict: v, savedAt: s.savedAt || null, applied: applied,
                 mine: localSavedAt(), dirty: isDirty(), healed: healed,
                 pend: pendingKeys(s.data || {}),        // 何が未書き出しか（null=測れなかった）
                 n: Object.keys(s.data || {}).length };
        if (!isDirty()) sentClear();   // 手元に未反映が無ければ、反映待ちの控え（Issue の送信記録）は要らない——Issue の反映が済んだ印でもある
        return last;
      });
  }

  /* 書き出し: state.json をそのまま作って落とす。人がコミットすれば repo が正本になる。 */
  function exportFile(btn, core) {
    var c = collect(core);
    var savedAt = new Date().toISOString();
    var payload = JSON.stringify({ fmt: 'ccf-state', ver: 1, savedAt: savedAt,
      note: '門の「人の決定」の正本。repo直下に置き、門が起動時に読む。' +
            'ブラウザからrepoへ鍵なしでは書けないので、書き出してコミットするか、門の「GitHub を開いて反映する」（Issue 経由）で入れる（state.jsの頭注）。',
      data: c.data }, null, 1);
    var o = btn ? btn.textContent : '';
    try {
      var blob = new Blob([payload], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = 'state.json';
      document.body.appendChild(a); a.click();
      setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1200);
      /* ⚠ クリップボードに**頼らない**（2026-08-10 実害）。Ⅶ資産は <iframe> の中にあり、
         `allow="clipboard-write"` が無いとブラウザが writeText を**黙って拒否**する。
         実測: 3回書き出しても savedAt が 17:29 のまま固定＝クリップボードが一度も更新されず、
         同じ古い中身が貼られ続けた（しかも大きい方なので毎回途中で切れた）。
         → **本文を画面に出して選択済みにする**。これはどのブラウザでも必ず動く。 */
      try { navigator.clipboard && navigator.clipboard.writeText(payload); } catch (e) {}
      showBox(payload, savedAt, c.n);
      // **落とした時点では repo にまだ無い**ので dirty は落とさない——
      // コミットして初めて正本になる。落とすのは「コミットした」を押したとき。
      // そのとき記録する savedAt は**この書き出しのもの**でなければならない（今の時刻ではない）
      last = last || {}; last.pendingSavedAt = savedAt;
      var kb = payload.length < 1024 ? '1KB未満' : Math.round(payload.length / 1024) + 'KB';
      if (btn) { btn.textContent = '✓ 書き出した（' + c.n + '件 / ' + kb + '・コピー済）→ ② へ';
                 setTimeout(function () { btn.textContent = o; }, 6000); }
    } catch (e) {
      if (btn) { btn.textContent = '書き出せない'; setTimeout(function () { btn.textContent = o; }, 2000); }
    }
    return { savedAt: savedAt, n: c.n };
  }

  /* 「コミットした」の申告: dirty を落とす。**押すのは人**＝嘘をつけば盤が古いままになるだけ。 */
  function markCommitted(savedAt) {
    try {
      if (savedAt) localStorage.setItem(SAVED_AT, savedAt);
      localStorage.removeItem(DIRTY);
      sentClear();
    } catch (e) {}
  }

  /* 書き出した中身をその場に出す（選択済み）。クリップボードが効かない環境でも渡せる。 */
  function showBox(payload, savedAt, n) {
    var host = document.getElementById('stateBox') || (function () {
      var d = document.createElement('div'); d.id = 'stateBox';
      var b = document.getElementById('stateBar');
      if (b && b.parentNode) b.parentNode.insertBefore(d, b.nextSibling);
      else document.body.appendChild(d);
      return d;
    })();
    var kb = payload.length < 1024 ? '1KB未満' : Math.round(payload.length / 1024) + 'KB';
    host.innerHTML =
      '<div style="border:1px solid ' + GREEN + ';border-left:5px solid ' + GREEN +
      ';border-radius:10px;padding:12px 14px;margin:10px 0;font-size:12.6px;line-height:1.7">' +
      '<div style="font-weight:700;color:' + GREEN + ';margin-bottom:4px">📋 ここの中身を全部コピーして貼ってください</div>' +
      '<div style="opacity:.85;margin-bottom:7px">' + n + '件 / ' + kb +
      '　savedAt ' + savedAt + '　<b>枠を長押し→全選択→コピー</b>（クリップボードが自動で入らない端末向け）</div>' +
      '<textarea id="stateBoxTa" readonly style="width:100%;height:150px;font-family:monospace;font-size:11px;' +
      'padding:8px;border:1px solid ' + GREEN + ';border-radius:7px;background:rgba(255,255,255,.6);color:#1b1610"></textarea>' +
      '<div style="margin-top:7px"><button onclick="ccfState.copyBox(this)" style="padding:7px 15px;border:1px solid ' +
      GREEN + ';background:' + GREEN + ';color:#fff;border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer;' +
      'font-family:inherit">📋 コピー</button></div></div>';
    var ta = document.getElementById('stateBoxTa');
    if (ta) { ta.value = payload; try { ta.focus(); ta.select(); } catch (e) {} }
  }

  /* execCommand は古いが、iframe でも file:// でも動く最後の砦 */
  function copyBox(btn) {
    var ta = document.getElementById('stateBoxTa'); if (!ta) return;
    var o = btn ? btn.textContent : '';
    var ok = false;
    try { ta.focus(); ta.select(); ta.setSelectionRange(0, ta.value.length); ok = document.execCommand('copy'); } catch (e) {}
    if (!ok) { try { navigator.clipboard.writeText(ta.value); ok = true; } catch (e) {} }
    if (btn) { btn.textContent = ok ? '✓ コピーした' : '手で選択してください';
               setTimeout(function () { btn.textContent = o; }, 2600); }
  }

  /* 帯の描画。**手順を4段の番号つきで出す**（v9.9.132・ユーザー「これをもっとわかるようにして」）。
     ここが単一実装で、index.html(門の頭) と portfolio.html(Ⅶ資産) の両方が同じものを描く。
     ⚠ 色は変数名で渡さない——index.html は --fail/--pass、portfolio.html は --rust/--jade と
        名前が違うので、変数名で書くと**片方のページだけ色が付かない**（v9.9.108 と同型の事故）。 */
  var RED = '#b04a2c', GREEN = '#2f7a53', DIM = 'rgba(128,120,105,.95)';

  function stepHTML(col) {
    var c = collect(), core = collect(true);
    var keys = Object.keys(core.data).map(function (k) {   // 見出しに出す品目は**決定だけ**の側
      return k.indexOf('g7log:') === 0 ? '検証履歴' : ({
        'pf:portfolio': '株数', 'pf:net': 'ETFの買付記録',
        'pf:weights': '目標ウェイト', 'pf:sold': '売却記録',
        'pf:monthly_total': '今月の入金総額',
        'pf:monthly': '今月の個別枠', 'pf:monthly_net': '今月のETF枠', 'g7ignite:map': '点灯日'
      }[k] || k);
    });
    var uniq = keys.filter(function (v, i) { return keys.indexOf(v) === i; });
    var b = function (label, fn) {
      return '<button onclick="' + fn + '" style="padding:8px 16px;border:1px solid ' + col +
        ';background:' + col + ';color:#fff;border-radius:8px;font-size:13px;font-weight:600;' +
        'cursor:pointer;font-family:inherit;white-space:nowrap">' + label + '</button>';
    };
    var li = function (n, t, extra) {
      return '<div style="display:flex;gap:10px;align-items:flex-start;margin:9px 0">' +
        '<span style="flex:0 0 auto;width:22px;height:22px;border-radius:50%;background:' + col +
        ';color:#fff;font-size:12px;font-weight:700;display:grid;place-items:center;margin-top:1px">' + n + '</span>' +
        '<span style="flex:1;min-width:0">' + t + (extra ? '<div style="margin-top:7px">' + extra + '</div>' : '') + '</span></div>';
    };
    var kb = function (o) { var n = JSON.stringify(o).length;
      return n < 1024 ? '1KB未満' : '約' + Math.round(n / 1024) + 'KB'; };
    var kbAll = kb(c.data), kbCore = kb(core.data);
    return li(1, '<b>書き出す</b>。<span style="opacity:.85">端末に落ち、<b>クリップボードにも入る</b>。</span>' +
                 '<div style="margin-top:5px;font-size:11.8px;opacity:.9">' +
                 '<b>決定だけ</b>＝' + core.n + '件 / <b>' + kbCore + '</b>（' + (uniq.join('・') || '—') + '）' +
                 '　／　<b>履歴も</b>＝' + c.n + '件 / ' + kbAll + '（＋検証履歴）</div>',
              b('📤 ① 決定だけ（小）', 'ccfState.export(this,true)') +
              ' <button onclick="ccfState.export(this)" style="margin-left:6px;padding:8px 14px;border:1px solid ' + col +
              ';background:transparent;color:' + col + ';border-radius:8px;font-size:12.5px;cursor:pointer;' +
              'font-family:inherit;white-space:nowrap">履歴も（大）</button>') +
           li(2, '<b>その中身を Claude に貼る</b>。<span style="opacity:.85">' +
                 '<b>貼るなら「決定だけ（小）」</b>——大きいほうは長すぎて<b>途中で切れます</b>（実測）。' +
                 '検証履歴ごと入れたいときは、落ちたファイルを repo 直下の ' +
                 '<code style="font-size:11.5px">state.json</code> に置いてコミット。</span>') +
           li(3, '<b>Claude が検査して commit・push する</b>。<span style="opacity:.85">' +
                 '<code style="font-size:11.5px">night/validate_state.py</code> で形を確かめてから入れる。</span>') +
           li(4, 'ここへ戻って <b>入れた</b> を押す。<span style="opacity:.85">この帯が消える。' +
                 '押し忘れても壊れない——帯が出続けるだけ。</span>',
              b('✓ ④ 入れた', 'ccfState.done(this)'));
  }

  function banner(elId) {
    var el = document.getElementById(elId); if (!el) return;
    var s = last;
    if (!s) { el.innerHTML = ''; return; }
    var head = '', col = RED, act = false;
    if (s.verdict === 'dirty') {
      head = '手元の決定が、<b>まだ repo に入っていません</b>';
      act = true;
    } else if (s.verdict === 'uninit') {
      head = 'repo の state.json は<b>まだ空</b>——株数も売却記録も<b>この端末にしかありません</b>';
      act = true;
    } else if (s.verdict === 'stale') {
      /* 2026-08-11: **赤い4手の帯を出さない**。
         decide() は dirty を stale より先に見るので、**stale は必ず「手元に未書き出しは無い」**
         の意味になる＝人がやることが何も無い。それを赤で出して4手を並べるのは、
         鳴りすぎる警報（＝鳴らないのと同じ）そのものだった。
         情報は消さない——**灰色の一行**にして、押すものは出さない。 */
      el.innerHTML = '<div style="border:1px dashed ' + DIM + ';border-radius:9px;padding:8px 12px;' +
        'margin:10px 0;font-size:12.2px;line-height:1.6;color:' + DIM + '">' +
        'repo の state.json（' + (s.savedAt || '').slice(0, 10) + '）は手元の記録（' +
        (s.mine || '').slice(0, 10) + '）より古いので<b>取り込みません</b>。' +
        '手元に未書き出しの決定はありません＝<b>やることはありません</b>。' +
        '入れ直すなら Ⅶ 保有 の「📤 決定だけ」から。</div>';
      return;
    } else if (s.verdict === 'adopt') {
      el.innerHTML = '<div style="border:1px solid ' + GREEN + ';border-left:5px solid ' + GREEN +
        ';border-radius:9px;padding:10px 14px;margin:10px 0;font-size:12.8px;line-height:1.7">' +
        '<b style="color:' + GREEN + '">✓ repo の state.json から ' + s.applied + '件を取り込みました</b>' +
        '<span style="opacity:.8">（' + (s.savedAt || '').slice(0, 10) + '）——この端末は repo に追いつきました。</span></div>';
      return;
    } else { el.innerHTML = ''; return; }   // same / none は黙る
    if (!act) { el.innerHTML = ''; return; }
    /* ★2026-08-17（ユーザー「これが全部のタブで勝手にでる。そもそもいるの？」）:
       **一行に畳む。** 旧版は4手を常時展開しており、携帯では**画面の大半を占めていた**
       ——しかも「決定が入っていません」としか言わず、**何が未書き出しかを出さなかった**ので、
       読み手には本物か誤検知かが判らなかった。
       ⚠ 消しはしない——守っているのは**株数と売却記録**で、これは out/ に正本が無く
         localStorage が消えたら戻らない唯一のデータ（holdings.json は銘柄名しか持たない）。
       ⇒ **何が未書き出しかを名指しし、手順は畳む。** 全タブに出るのは v9.9.132 の意図どおり
         （Ⅳ台帳の中に置いていたら既定タブで見えなかった）。 */
    var names = (s.pend && s.pend.length) ? s.pend.join('・')
              : (s.pend === null ? null : null);
    var what = names ? ('<b>' + names + '</b>が未書き出し')
             : (s.verdict === 'uninit'
                ? '<b>repo の state.json がまだ空</b>——株数も売却記録もこの端末にしかありません'
                : '手元の決定が repo に入っていません');
    el.innerHTML = '<details style="border:1px solid ' + col + ';border-left:5px solid ' + col +
      ';border-radius:10px;padding:9px 14px;margin:10px 0;font-size:12.6px;line-height:1.7">' +
      '<summary style="cursor:pointer;color:' + col + ';font-weight:600;list-style:none">' +
      '⚠ ' + what + '　<span style="font-weight:400;font-size:11.5px;opacity:.85">' +
      '——押すと直し方</span></summary>' +
      '<div style="color:' + DIM + ';font-size:12px;margin:8px 0 4px">' +
      '門は静的ページなので<b>ブラウザから repo へ直接は書けません</b>（鍵を置かない設計）。' +
      'だから最後の一歩だけ人の手が要ります——<b>GitHub の画面で1回押すだけ</b>の道（下の緑の枠）と、Claude に頼む道（4手）があります。' +
      '<br>※<b>点灯日と目標ウェイトは機械が書く記録</b>なのでここでは数えません（鮮度は⚙自動化の回転盤が測る）。' +
      '</div>' +
      /* ★v9.9.210: いちばん簡単な道（Issue 経由）。開いたときに用意する＝閉じたままの帯のたびに repo を読みに行かない */
      '<div style="margin:8px 0 10px;padding:9px 11px;border:1px solid ' + GREEN + ';border-left:5px solid ' + GREEN + ';border-radius:8px">' +
      '<b style="color:' + GREEN + '">いちばん簡単な道</b><span style="opacity:.85">（この端末の値のほうが正しいとき・鍵は要りません）</span>' +
      '<div class="ccfIssueBox" id="stateIssueBox" style="margin-top:7px"></div></div>' +
      /* 逆向き（repo が正しいとき）の道。4手より先に置く——こちらのほうが多い（別セッションが保有を直す運用） */
      '<div style="margin:8px 0 10px;padding:9px 11px;border:1px solid ' + DIM + ';border-radius:8px">' +
      '<b>repo の保有のほうが正しいとき</b>（Claude が証券会社の画面から保有を直した後など）は、こちら：<br>' +
      '<button onclick="ccfState.adoptRepo(this)" style="margin-top:6px;padding:7px 13px;border-radius:8px;border:1px solid ' + col +
      ';background:#fff;color:' + col + ';font-weight:700;cursor:pointer">⭳ repo の保有で上書きする</button>' +
      '<div style="font-size:11.5px;opacity:.85;margin-top:4px">株数と売却記録だけを置き換えます（今月の入金額などは残す）。</div></div>' +
      '<div style="font-size:12px;margin:4px 0">この端末の値のほうが正しいときは、Claude に頼む4手でも入れられる：</div>' +
      stepHTML(col) + '</details>';
    var det = el.querySelector('details');
    if (det) det.addEventListener('toggle', function () {
      var box = det.querySelector('.ccfIssueBox');
      if (det.open && box && !box.__ccfTok) issueWidget(box);     // 最初に開いたときに用意する（開き直すたびに作り直さない）
    });
  }

  /* ★2026-09-23 新設（ユーザー「総資産がまちがってる」→「やって」）: **repo の保有で手元を上書きする逆向きの道**。
     dirty のとき decide() は repo を採用しない（手元の未書き出しを守るため）。だが**正しいのが repo 側**のとき
     （別セッションが楽天の画面から保有を直して commit した・この端末には古い株数が残っている）、
     旧版には手元を捨てて repo に合わせる手段が**一つも無く**、帯の4手は逆向き（手元→repo）しか案内しなかった。
     実害: 端末の総資産が売却済みの行（RMD/IRMD 等）や二重計上（MSFT 11株）のまま計算され続けた。
     ⇒ **人が確認ダイアログで明示に選んだときだけ**、株数(pf:portfolio)と売却記録(pf:sold)を repo の値で置き換える。
       今月の入金額など他の決定は**触らない**（残す）。置き換える前の値は ccf:replacedBackup に1件だけ退避する＝戻せる。 */
  var REPLACE_KEYS = ['pf:portfolio', 'pf:sold'];
  function adoptRepo(btn) {
    var ok = true;
    try { ok = window.confirm('この端末の「株数」と「売却記録」を、repo（state.json）の値で置き換えます。\n' +
      '今月の入金額などほかの値はそのまま残します。置き換える前の値は端末内に1件だけ控えを取ります。\n\n置き換えますか？'); } catch (e) {}
    if (!ok) return;
    var o = btn ? btn.textContent : '';
    if (btn) btn.textContent = '読み込み中…';
    fetch('state.json?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (st) {
        if (!st || st.fmt !== 'ccf-state' || !st.data) {
          if (btn) { btn.textContent = 'repo の state.json が読めない'; setTimeout(function () { btn.textContent = o; }, 2500); }
          return;
        }
        var d = st.data, bak = { at: new Date().toISOString(), data: {} }, n = 0;
        REPLACE_KEYS.forEach(function (k) { try { bak.data[k] = localStorage.getItem(k); } catch (e) {} });
        quiet(function () {
          try { localStorage.setItem('ccf:replacedBackup', JSON.stringify(bak)); } catch (e) {}
          REPLACE_KEYS.forEach(function (k) {
            if (d[k] == null) return;             // repo に無いキーは触らない（空で上書きしない）
            try { localStorage.setItem(k, d[k]); n++; } catch (e) {}
          });
        });
        // repo に追いついた＝以後は repo の更新を自動で受け取れるようにする
        try { if (st.savedAt) localStorage.setItem(SAVED_AT, st.savedAt); localStorage.removeItem(DIRTY); sentClear(); } catch (e) {}
        if (btn) btn.textContent = '✓ ' + n + '件を置き換えました——再読み込みします';
        setTimeout(function () { try { location.reload(); } catch (e) {} }, 900);
      });
  }

  /* ★2026-10-10 撤去（ユーザー「なんか鍵がどうとかはいらない」）: 2026-09-23 に入れた「門から repo の state.json を直接保存する道」
     （GitHub の鍵〔fine-grained token〕を端末の localStorage に置いて、GitHub API で state.json を書く）を**道ごと外した**。
     鍵を置く道は、端末を触れる人・ページに入った悪意あるコードが repo へ書けてしまう代償があった。
     ⇒ 門→repo は、この冒頭の設計どおり**人の手を一歩だけ挟む**道にした——📤 書き出す → Claude に「反映して」か、
       v9.9.210 の「🚀 GitHub を開いて反映する」（下の「Issue 経由」の節・鍵なし）。
       ブラウザの画面（🏦保有・総資産・前日比・買付順位・銘柄の詳細）は、保有が書き換わった時点で上の合図で**自動で**つくり直される。
       自動にならないのは、repo の state.json から CI が計算する 📈成績 だけ（repo に入るまで古い保有のまま＝📈成績の先頭に差を名指しで出す）。 */

  /* ④ 「入れた」。**押すのは人**＝嘘をつけば盤(ops_status)が古いままになるだけで、データは消えない。 */
  function done(btn) {
    var o = btn ? btn.textContent : '';
    /* 2026-08-11 是正: **押した時刻を書かない**。
       「入れた」は『repo が正本になった』の意味なので、**repo を読み直してそこに書いてある
       savedAt に合わせる**のが正しい。押した時刻を書くと repo より必ず新しくなり、以後ずっと
       『repo の state.json が手元より古い』と鳴り続ける（実害: 2026-08-11 の画面）。
       しかも**この帯自身が「④ ここへ戻って押す」と案内している**＝手順どおりにやると必ずこうなる
       ——戻ってきた時点で last.pendingSavedAt は失われており、fallback の new Date() が書かれていた。
       ⚠ GitHub Pages の反映待ちで古い state.json が返っても害はない——repo と手元が揃うだけで、
       新しいものが届いたら次回 adopt される。 */
    if (btn) btn.textContent = '確認中…';
    var fin = function (msg) {
      if (btn) btn.textContent = msg;
      setTimeout(function () {
        ['stateBar'].forEach(function (id) { try { banner(id); } catch (e) {} });
        if (btn) btn.textContent = o;
      }, 900);
    };
    load().then(function (s) {
      if (s && s.savedAt) { markCommitted(s.savedAt); last = { verdict: 'same', savedAt: s.savedAt, mine: s.savedAt }; }
      else { if (last && last.pendingSavedAt) markCommitted(last.pendingSavedAt); last = { verdict: 'same' }; }
      fin('✓ 記録した');
    }).catch(function () {
      if (last && last.pendingSavedAt) markCommitted(last.pendingSavedAt);
      last = { verdict: 'same' };
      fin('✓ 記録した');
    });
  }

  /* ============================================================================
     ★v9.9.210（2026-10-10 ユーザー明示指示「案1でやってマージして」）: **Issue 経由で repo の state.json を更新する道**
     ----------------------------------------------------------------------------
     冒頭に書いたとおり、門（静的ページ）からは鍵なしで repo へ書けない。鍵を端末に置く道は v9.9.209 で撤去した。
     そこで「**人が GitHub で1回押す**」だけで入る道を足した（鍵は要らない・GitHub にログインしていれば足りる）:
       ① 門が、端末の決定と repo の差から **「新規 Issue」のリンク**を作る（本文に依頼が入っている）= prepareIssue / issueWidget
       ② 人がリンクを開いて「Submit new issue」を1回押す
       ③ `.github/workflows/state_from_issue.yml`（night/apply_state_issue.py）が検査して state.json を更新・push し、
          📈成績（returns.yml）を起こし、結果を Issue にコメントして閉じる
       ④ 戻ってきたら、門が repo を読み直して追いつく（watchSync・load の取り込み）
     ⚠ これは main への自動 push の新設（2026-09-23 に Routine の自動 push がアカウント停止の原因になった経緯により、
       ユーザーの明示指示が要った）。止めるなら state_from_issue.yml を消す（門のリンクは押しても何も起きなくなる）。

     ■ 守り（ここが本体）
       (1) **公開される前に自由記述を止める**（rule 9「個人の名前を repo に書かない」）。Issue は作られた瞬間に公開される。
           端末の localStorage には名前を消す前の古い文が残っていることがある。→ 自由記述の欄（note / memo / src / who）は、
           **repo に既にある文（＝既に公開）**か**門が機械で作る定型文**だけ通し、それ以外が1つでもあればリンクを作らない（unseenText）。
           名前の一覧は持たない（持てば対応表になる）。**「既に公開されているか」だけで決める**。
           サーバー側（apply_state_issue.py）にも同じ検問があり、二つの実装は共有ベクトル night/state_issue_vectors.json で突き合わせる。
       (2) **CAS**: repo が、この端末の最後の同期より後に（別の端末や Claude に）更新されていれば、**送らない**。
           自分の前の送信の上に重ねるのは安全（SENT に値のハッシュを控える）。依頼には「どの repo の値の上に作ったか」(bases) を入れ、
           サーバーも今の repo の値と違えば何もしない。**新しいほうを古いほうが黙って潰す経路を作らない**（冒頭の掟）。
       (3) 送るのは**人の決定のうち repo と違うものだけ**（機械の書き戻し fx/npx/npxAuto だけの差は数えない＝sameDecision）。
           機械しか書かないキー（目標ウェイト・点灯日）は、人の決定を送るときに限り同乗させる（repo の写しを新鮮に保つ。URL が長すぎれば外す）。
       (4) 本文は deflate+base64url（CompressionStream が無ければ素のまま）。sha256 で完全性を守る。URL は 7000 字まで（GitHub は約8KB）。
     ■ 限界（正直に）
       ・GitHub にログインしていない端末では、ログイン画面を挟む。Issue を押さなければ何も起きない（門は dirty のまま＝赤い帯が残る）。
       ・古い自由記述が端末にあると検問が止める。その場合は従来どおり 📤 書き出す → Claude に貼る（目で確かめて入れる道は残してある）。
       ・Pages の反映に1〜3分かかるので、戻ってすぐは「まだ」と出ることがある（見張りが自動で確認を続ける）。 */
  var ISSUE_FMT = 'ccf-state-issue';
  var ISSUE_TITLE = '[ccf-state]';
  var MAX_URL = 7000;                    // GitHub の「新規 Issue」リンクは約8KBまで。余裕を見て7000字
  var SENT = 'ccf:stateSent';            // {キー:[自分が送った値のハッシュ…]}——repo の値がこれなら、自分の前の送信の上に重ねてよい
  var SENT_AT = 'ccf:stateSentAt';       // 最後にリンクを作った時刻（ms）。反映待ちの見張りの目印
  var SENT_WINDOW = 30 * 60 * 1000;      // この間は「反映待ち」として見張る
  var WATCH_EVERY = 20 * 1000, WATCH_MAX = 8 * 60 * 1000;
  var HUMAN = EXACT.filter(function (k) { return !DERIVED_KEY[k]; });
  var DERIVED_LIST = EXACT.filter(function (k) { return !!DERIVED_KEY[k]; });

  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function labelOf(k) { return LABEL[k] || k; }

  /* ── 自由記述の検問（サーバーの night/apply_state_issue.py の find_unseen_text と同じ規則・同じ表）──
     STRICT の欄は「repo に既にある文」か「門が作る定型文」だけ通す。nm（会社名・ファンド名）は公開情報なので自由。
     それ以外の文字列は、ASCII か、既知の区分名か、repo に既にある文なら通す。今月の入金額は数字だけ。 */
  var STRICT_FIELDS = { note: 1, memo: 1, src: 1, who: 1 };
  var FREE_FIELDS = { nm: 1 };
  var PLAIN_NUMBER = { 'pf:monthly_total': 1, 'pf:monthly': 1, 'pf:monthly_net': 1 };
  var ENUM_OK = ['個別', 'ETF', '投資信託', '暗号資産', '成長', 'つみたて', '特定', 'iDeCo', 'こどもNISA', '取引所', '子ども'];
  var G_ACCT = '(?:成長|つみたて|特定|iDeCo|こどもNISA|取引所)', G_WHO = '(?:[A-Z]|子ども)';
  var SRC_TPL = new RegExp('^門の🏦保有で記録(?:（約定日 \\d{4}-\\d{2}-\\d{2}）)?(?:（' + G_WHO + '(?:・' + G_ACCT + ')?）|（' + G_ACCT + '）)?$');
  var SELL_NOTE_TPL = /^\d{4}-\d{2}-\d{2} [0-9][0-9.,]*(?:株|口| [A-Z]{2,6})売却（門で記録）$/;
  var MEMO_AUTO_TPL = /^受取額は見積もり（(?:口数×基準価額|株数×単価×ドル円)）$/;
  var WHO_TPL = new RegExp('^' + G_WHO + '$');
  var SEG_SEP = '　';                // 全角空白（note / memo は定型文をこれでつなぐ）

  function guardLeaves(key, value) {     // (道筋, 欄の名前, 文) を深さ優先・挿入順で集める。文字列の葉だけ
    var o; try { o = JSON.parse(value); } catch (e) { o = value; }
    var out = [];
    (function walk(x, path, field) {
      if (typeof x === 'string') out.push([path, field, x]);
      else if (Array.isArray(x)) { for (var i = 0; i < x.length; i++) walk(x[i], path + '[' + i + ']', field); }
      else if (x && typeof x === 'object') { for (var k in x) if (own(x, k)) walk(x[k], path + '.' + k, k); }
    })(o, '', '');
    return out.map(function (r) { return [key + ':' + r[0].replace(/^\.+/, ''), r[1], r[2]]; });
  }
  function publicSets(repoData) {        // repo の state.json に既にある文（＝既に公開）
    var full = new Set(), segs = new Set();
    for (var k in repoData) {
      if (!own(repoData, k) || typeof repoData[k] !== 'string') continue;
      guardLeaves(k, repoData[k]).forEach(function (lf) {
        full.add(lf[2]);
        if (lf[1] === 'note' || lf[1] === 'memo') lf[2].split(SEG_SEP).forEach(function (seg) { seg = seg.trim(); if (seg) segs.add(seg); });
      });
    }
    return { full: full, segs: segs };
  }
  function scanUnseen(data, repoData) {  // [{path, text}]——repo に無い自由記述の場所
    var ps = publicSets(repoData || {}), bad = [];
    Object.keys(data || {}).forEach(function (k) {
      guardLeaves(k, data[k]).forEach(function (lf) {
        var path = lf[0], field = lf[1], s = lf[2];
        if (own(STRICT_FIELDS, field)) {
          if (ps.full.has(s)) return;
          if (field === 'who' && WHO_TPL.test(s)) return;
          if (field === 'src' && SRC_TPL.test(s)) return;
          if (field === 'note' || field === 'memo') {
            var parts = s.split(SEG_SEP).map(function (x) { return x.trim(); }).filter(function (x) { return x; });
            var pat = field === 'note' ? SELL_NOTE_TPL : MEMO_AUTO_TPL;
            if (parts.every(function (x) { return ps.segs.has(x) || pat.test(x); })) return;
          }
          bad.push({ path: path, text: s });
        } else if (own(FREE_FIELDS, field)) { return; }
        else if (own(PLAIN_NUMBER, k)) { if (!/^[0-9.,]*$/.test(s)) bad.push({ path: path, text: s }); }
        else if (/^[\x00-\x7f]*$/.test(s) || ENUM_OK.indexOf(s) >= 0 || ps.full.has(s)) { return; }
        else bad.push({ path: path, text: s });
      });
    });
    return bad;
  }
  function unseenText(data, repoData) { return scanUnseen(data, repoData).map(function (b) { return b.path; }); }
  function guardConsts() {               // 検問の表（Python 側と同じか、night/check_state_issue.js が突き合わせる）
    return { strict: Object.keys(STRICT_FIELDS).sort(), free: Object.keys(FREE_FIELDS).sort(), enum: ENUM_OK.slice().sort(),
             plain: Object.keys(PLAIN_NUMBER).sort(), sep: SEG_SEP };
  }

  /* ── 符号化（SubtleCrypto の sha256・CompressionStream の deflate）── */
  function utf8(s) { return new TextEncoder().encode(s); }
  function sha256hex(s) {
    try {
      if (!(window.crypto && crypto.subtle && crypto.subtle.digest && window.TextEncoder)) return Promise.reject(new Error('nocrypto'));
      return crypto.subtle.digest('SHA-256', utf8(s)).then(function (b) {
        var a = new Uint8Array(b), h = '';
        for (var i = 0; i < a.length; i++) h += (a[i] < 16 ? '0' : '') + a[i].toString(16);
        return h;
      });
    } catch (e) { return Promise.reject(new Error('nocrypto')); }
  }
  function streamBytes(u8, fmt) {
    try {
      var cs = new CompressionStream(fmt), w = cs.writable.getWriter();
      w.write(u8).catch(function () {}); w.close().catch(function () {});      // 待たない（読み手が居ないと詰まる）
      return new Response(cs.readable).arrayBuffer().then(function (b) { return new Uint8Array(b); });
    } catch (e) { return Promise.reject(e); }
  }
  function encodeBlock(u8) {             // 符号の頭: z=raw deflate / d=zlib / p=素のまま（サーバーの decode_block と対）
    var plain = function () { return { enc: 'p', bytes: u8 }; };
    if (typeof CompressionStream !== 'function') return Promise.resolve(plain());
    return streamBytes(u8, 'deflate-raw').then(function (b) { return { enc: 'z', bytes: b }; }, function () {
      return streamBytes(u8, 'deflate').then(function (b) { return { enc: 'd', bytes: b }; }, plain);
    });
  }
  function b64url(u8) {
    var s = '';
    for (var i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192));
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  /* 「新規 Issue」の宛先。公開URL（<owner>.github.io/<repo>/）から導く。導けないとき（手元の確認など）は既定。 */
  function issueNewUrl() {
    var m = (location.hostname || '').match(/^([^.]+)\.github\.io$/i), seg = ((location.pathname || '').split('/')[1] || '');
    if (m && /^[A-Za-z0-9_-]+$/.test(seg)) return 'https://github.com/' + m[1] + '/' + seg + '/issues/new';
    return 'https://github.com/touchme1956/ccf-gate/issues/new';
  }
  function stamp() {
    var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
    return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function readSent() { try { var o = JSON.parse(localStorage.getItem(SENT) || '{}'); return (o && typeof o === 'object' && !Array.isArray(o)) ? o : {}; } catch (e) { return {}; } }
  function sentAt() { try { return +localStorage.getItem(SENT_AT) || 0; } catch (e) { return 0; } }
  function rememberSent(hashes) {        // hashes: {キー: リンクに入れた値の sha256}
    var o = readSent();
    Object.keys(hashes).forEach(function (k) {
      var prev = Array.isArray(o[k]) ? o[k].filter(function (x) { return x !== hashes[k]; }) : [];
      o[k] = [hashes[k]].concat(prev).slice(0, 3);
    });
    try { localStorage.setItem(SENT, JSON.stringify(o)); localStorage.setItem(SENT_AT, String(Date.now())); } catch (e) {}
  }
  function sentClear() { try { localStorage.removeItem(SENT); localStorage.removeItem(SENT_AT); } catch (e) {} }

  /* prepareIssue() — 端末の決定と repo の差から、Issue のリンクを作る。
     戻り値（Promise）: {ok:true, url, keys, labels, len, derived}
                      {ok:false, why:'none'}                      送るものが無い（repo と同じ）
                      {ok:false, why:'fetch'}                     repo の state.json が読めない
                      {ok:false, why:'behind', labels}            repo が先に更新されている（送ると新しいほうを消す）
                      {ok:false, why:'text', paths, sample}       repo に無い自由記述がある（公開しない）
                      {ok:false, why:'size', len}                 リンクに入りきらない
                      {ok:false, why:'nocrypto'|'error'}          検算・符号化ができない */
  function prepareIssue() {
    var mineOf = function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } };
    return fetch('state.json?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; }, function () { return null; })
      .then(function (s) {
        if (!s || s.fmt !== 'ccf-state' || !s.data || typeof s.data !== 'object') return { ok: false, why: 'fetch' };
        var repo = s.data, repoSaved = s.savedAt || null, k;
        for (k in repo) if (own(repo, k) && typeof repo[k] !== 'string') return { ok: false, why: 'fetch' };   // 読めない形は触らない
        var differs = function (key) {
          var mine = mineOf(key); if (mine == null) return false;            // 端末に無いキーは送らない（Issue では消さない）
          var theirs = own(repo, key) ? repo[key] : null;
          return theirs == null || !sameDecision(key, mine, theirs);
        };
        var human = HUMAN.filter(differs), derived = DERIVED_LIST.filter(differs);
        if (!human.length) return { ok: false, why: 'none' };                // 機械しか書かないキーだけの差は、人の決定ではない
        var devSaved = localSavedAt(), sent = readSent();
        return Promise.all(human.concat(derived).map(function (key) {
          var theirs = own(repo, key) ? repo[key] : null;
          return Promise.all([theirs == null ? '-' : sha256hex(theirs), sha256hex(mineOf(key))]).then(function (h) {
            return { k: key, theirs: theirs, base: h[0], mine: h[1] };
          });
        })).then(function (rows) {
          var by = {}; rows.forEach(function (r) { by[r.k] = r; });
          /* 上書きしてよいか: repo に無いキー／この端末が最後に同期した repo のまま／repo の値が「自分が前に送った値」 */
          var safe = function (r) {
            return r.theirs == null || (!!repoSaved && !!devSaved && repoSaved === devSaved) ||
                   (Array.isArray(sent[r.k]) && sent[r.k].indexOf(r.base) >= 0);
          };
          var behind = human.filter(function (key) { return !safe(by[key]); });
          if (behind.length) return { ok: false, why: 'behind', labels: behind.map(labelOf) };
          /* 検問: 人の決定に repo に無い自由記述があれば、リンクを作らない。同乗させる機械のキー（目標ウェイト・点灯日）に未知の文があるときは、
             それだけ外す（同乗は任意＝その写しのために人の決定まで止めない）。 */
          var cand = {}; human.forEach(function (key) { cand[key] = mineOf(key); });
          var bad = scanUnseen(cand, repo);
          if (bad.length) return { ok: false, why: 'text', paths: bad.map(function (b) { return b.path; }), sample: bad[0].text };
          var useDerived = derived.filter(function (key) {
            if (!safe(by[key])) return false;
            var one = {}; one[key] = mineOf(key);
            if (scanUnseen(one, repo).length) return false;
            cand[key] = one[key];
            return true;
          });
          var labels = human.map(labelOf);
          var make = function (keys) {
            var dm = {}, bs = {};
            /* 前提（bases）: 今読んだ repo の値に加え、**自分が前に送った値**も並べる。Pages の反映が遅れて古い state.json を読んだ日に、
               前の送信がもう入っていても、サーバーの CAS が「repo が先に変わった」と誤って止めないように（自分の送信の上に重ねるのは安全）。 */
            keys.forEach(function (key) {
              dm[key] = cand[key];
              var mine = Array.isArray(sent[key]) ? sent[key] : [];
              bs[key] = [by[key].base].concat(mine.filter(function (h) { return h !== by[key].base; })).slice(0, 4);
            });
            var dataJson = JSON.stringify(dm);
            return sha256hex(dataJson).then(function (sha) {
              var payload = { fmt: ISSUE_FMT, ver: 1, at: new Date().toISOString(), bases: bs, dataJson: dataJson, sha: sha };
              return encodeBlock(utf8(JSON.stringify(payload))).then(function (e) {
                var title = ISSUE_TITLE + ' ' + labels.slice(0, 3).join('・') + (labels.length > 3 ? ' ほか' : '') + ' ' + stamp();
                var body = '門の「人の決定」を repo の state.json に入れる依頼です。\n' +
                           'このまま「Submit new issue」を押してください（数十秒で自動で入り、この Issue は閉じます）。\n\n' +
                           '```ccf-state\n' + e.enc + '.' + b64url(e.bytes) + '\n```\n';
                return { url: issueNewUrl() + '?title=' + encodeURIComponent(title) + '&body=' + encodeURIComponent(body), keys: keys };
              });
            });
          };
          return make(human.concat(useDerived)).then(function (b) {
            return (b.url.length > MAX_URL && useDerived.length) ? make(human) : b;     // 長すぎれば同乗の分を外す
          }).then(function (b) {
            if (b.url.length > MAX_URL) return { ok: false, why: 'size', len: b.url.length };
            var h = {}; b.keys.forEach(function (key) { h[key] = by[key].mine; });
            rememberSent(h);
            return { ok: true, url: b.url, keys: b.keys, labels: labels, len: b.url.length, derived: b.keys.length > human.length };
          });
        });
      })
      .catch(function (e) {
        var m = String((e && e.message) || e);
        return { ok: false, why: m === 'nocrypto' ? 'nocrypto' : 'error', msg: m };
      });
  }

  /* ── 画面の部品: 「🚀 GitHub を開いて反映する」。banner（赤い帯）・記録の直後・📈成績の差の表示 の3か所が同じものを出す（単一実装）── */
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var BTN_GO = 'display:inline-block;padding:9px 16px;border:1px solid ' + GREEN + ';background:' + GREEN +
               ';color:#fff;border-radius:9px;font-size:13px;font-weight:700;text-decoration:none;cursor:pointer;font-family:inherit;text-shadow:none';
  var BTN_SUB = 'padding:5px 11px;border:1px solid ' + DIM + ';background:transparent;color:inherit;border-radius:7px;font-size:12px;cursor:pointer;font-family:inherit';
  function exportBtn() { return '<button onclick="ccfState.export(this,true)" style="' + BTN_SUB + '">📤 書き出す</button>'; }
  var FALLBACK = '「📤 書き出す」を Claude に貼って「反映して」と頼む道は、これまでどおり使えます。';
  function issueHTML(r) {
    var wrap = function (inner, col) { return '<div style="font-size:12.3px;line-height:1.75;color:inherit' + (col ? ';border-left:3px solid ' + col + ';padding-left:9px' : '') + '">' + inner + '</div>'; };
    if (r.ok) {
      return '<a class="ccfIssueGo" target="_blank" rel="noopener noreferrer" onclick="ccfState.issueOpened(this)" onauxclick="ccfState.issueOpened(this)" style="' + BTN_GO + '">🚀 GitHub を開いて反映する</a>' +
        '<div style="font-size:11.8px;line-height:1.75;margin-top:7px">GitHub が開いたら、<b>「Submit new issue」を1回押すだけ</b>です（内容は変えないでください）。' +
        '数十秒で repo に入り、📈成績も数分で作り直されます。GitHub にログインしている端末なら、<b>鍵は要りません</b>。<br>' +
        '送る内容: <b>' + esc(r.labels.join('・')) + '</b>' + (r.derived ? '（＋目標ウェイト・点灯日の写し）' : '') + '</div>' +
        '<div style="margin-top:7px"><button onclick="ccfState.checkSync(this)" style="' + BTN_SUB + '">↻ 反映できたか確認</button> ' +
        '<span class="ccfIssueMsg" style="font-size:11.8px;opacity:.9"></span></div>';
    }
    switch (r.why) {
      case 'none': return wrap('✓ <b>送るものはありません</b>——この端末の決定は repo と同じです。');
      case 'fetch': return wrap('⚠ repo の state.json が読めませんでした（通信を確かめてください）。 <button onclick="ccfState.issueWidget(this.closest(\'.ccfIssueBox\'))" style="' + BTN_SUB + '">もう一度</button>', RED);
      case 'behind': return wrap('⚠ repo が、この端末より<b>先に更新されています</b>（別の端末や Claude が入れた）。このまま送ると新しいほうを消してしまうので<b>止めました</b>。' +
          '<br>対象: <b>' + esc((r.labels || []).join('・')) + '</b><br>この端末の値のほうが正しいときは、' + exportBtn() + ' → Claude に貼って「repo の更新も見て反映して」と頼んでください。', RED);
      case 'text': return wrap('⚠ <b>名前などの自由記述が入っているかもしれない記録</b>があるので、公開の Issue には<b>載せません</b>（この repo は公開で、名前を載せない決まりです）。' +
          '<br>場所（この端末の中だけの表示）: <code style="font-size:11px">' + esc((r.paths || []).slice(0, 3).join(' / ')) + ((r.paths || []).length > 3 ? ' ほか' + ((r.paths || []).length - 3) + 'か所' : '') + '</code>' +
          (r.sample ? '<br>例: 「' + esc(String(r.sample).slice(0, 24)) + (String(r.sample).length > 24 ? '…' : '') + '」' : '') +
          '<br>' + exportBtn() + ' → Claude に貼ってください（Claude が目で確かめて入れます）。', RED);
      case 'size': return wrap('⚠ 記録が大きく、リンクに入りきりません（' + (r.len || '') + '字・上限 ' + MAX_URL + '字）。' + exportBtn() + ' → Claude に貼って「反映して」にしてください。', RED);
      case 'nocrypto': return wrap('⚠ このブラウザでは、依頼の検算（暗号の機能）が使えません。https の門（公開URL）で開くと使えます。今回は ' + exportBtn() + ' を使ってください。', RED);
      default: return wrap('⚠ 用意できませんでした' + (r.msg ? '（' + esc(String(r.msg).slice(0, 60)) + '）' : '') + '。' + FALLBACK + ' ' + exportBtn(), RED);
    }
  }
  var widgetSeq = 0;
  function renderIssue(host, r) {
    host.innerHTML = issueHTML(r);
    if (r.ok) { var a = host.querySelector('a.ccfIssueGo'); if (a) a.href = r.url; }
  }
  function issueWidget(host) {
    if (!host) return;
    try { host.classList.add('ccfIssueBox'); } catch (e) {}
    var tok = ++widgetSeq; host.__ccfTok = tok;
    host.innerHTML = '<div style="font-size:12px;color:' + DIM + '">⏳ 反映の用意をしています…</div>';
    prepareIssue().then(function (r) { if (host.__ccfTok === tok) renderIssue(host, r); });
  }
  function syncedHTML() {
    return '<div style="font-size:12.3px;line-height:1.75;border-left:3px solid ' + GREEN + ';padding-left:9px">✓ <b>repo に入りました</b>——この端末と repo の決定が同じになりました。' +
           '📈成績は、repo に入ってから数分で作り直されます。</div>';
  }

  /* ── 反映待ちの見張り: リンクを開いたあと戻ってきたら、repo を読み直して追いつく ── */
  var watchTimer = null, watchT0 = 0;
  function watchActive() { var t = sentAt(); return isDirty() && t > 0 && (Date.now() - t) < SENT_WINDOW; }
  function stopWatch() { if (watchTimer) { clearInterval(watchTimer); watchTimer = null; } }
  function fireSynced() {
    try { window.dispatchEvent(new CustomEvent('ccf:synced')); } catch (e) {}
    try { var hs = document.querySelectorAll('.ccfIssueBox'); for (var i = 0; i < hs.length; i++) { hs[i].__ccfTok = ++widgetSeq; hs[i].innerHTML = syncedHTML(); } } catch (e) {}
  }
  function syncCheck() {                 // repo を読み直し、手元の決定が repo に追いついたか（追いついていれば true）
    var sig = function () { return last ? [last.verdict, (last.pend || []).join('|'), last.dirty ? 1 : 0].join(':') : ''; };
    var before = sig();
    return load().then(function () {
      var ok = !isDirty();
      if (sig() !== before || ok) { try { banner('stateBar'); } catch (e) {} }    // 変わらないのに作り直すと、開いている「直し方」が閉じてしまう
      if (ok) { stopWatch(); fireSynced(); }
      return ok;
    }, function () { return false; });
  }
  function watchTick() { if (!watchActive()) { stopWatch(); return; } syncCheck(); }
  function startWatch() {
    stopWatch();
    if (!watchActive()) return;
    watchT0 = Date.now();
    watchTimer = setInterval(function () { if (Date.now() - watchT0 > WATCH_MAX) { stopWatch(); return; } watchTick(); }, WATCH_EVERY);
  }
  function issueOpened(a) {              // リンクを押した（新しいタブで GitHub が開く）
    startWatch();
    try { var host = a && a.closest ? a.closest('.ccfIssueBox') : null, m = host && host.querySelector('.ccfIssueMsg');
          if (m) m.textContent = '開きました。「Submit new issue」を押したら、この画面に戻ってください——入ったか自動で確認します。'; } catch (e) {}
  }
  function checkSync(btn) {              // 「↻ 反映できたか確認」
    var host = btn && btn.closest ? btn.closest('.ccfIssueBox') : null, msg = host ? host.querySelector('.ccfIssueMsg') : null, o = btn ? btn.textContent : '';
    if (btn) btn.textContent = '確認中…';
    syncCheck().then(function (ok) {
      if (btn) btn.textContent = o;
      if (!ok && msg) msg.textContent = 'まだ入っていません。GitHub で「Submit new issue」を押しましたか？ 押したあと、入るまで数分かかります（自動で確認を続けます）。';
      if (!ok) startWatch();
    });
  }
  try {
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && watchActive()) { watchTick(); startWatch(); }
    });
    // 別の文書（🏦保有の iframe・別のタブ）が同期を終えたら、こちらも読み直して知らせる（SENT_AT が消えるのが合図）
    window.addEventListener('storage', function (e) {
      if (e.key === SENT_AT && e.newValue == null) load().then(function () { fireSynced(); });
    });
    if (watchActive()) startWatch();   // 再読み込みしても、反映待ちなら見張りを続ける
  } catch (e) {}

  window.ccfState = { load: load, export: exportFile, banner: banner, quiet: quiet, done: done, copyBox: copyBox, adoptRepo: adoptRepo,
                      markCommitted: markCommitted, decide: decide, collect: collect,
                      isDirty: isDirty, keys: { exact: EXACT, prefix: PREFIX },
                      prepareIssue: prepareIssue, issueWidget: issueWidget, issueOpened: issueOpened, checkSync: checkSync, syncCheck: syncCheck,
                      unseenText: unseenText, guardConsts: guardConsts, sameDecision: sameDecision,
                      get last() { return last; } };
})();
