#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_docs.py — **説明文とコードの整合検査**（2026-08-06新設）

なぜ要るか:
  この repo が繰り返し踏んでいる失敗の型は、CLAUDE.md 自身が名前を付けている——
  **「規則を変えたら、規則を人に教える文も全部 grep で洗う」**。
  実際に4回失敗している:
    (1) 日本株審査依頼文(ccfCopyAskJP)が廃止済みの旧JP規約を配り続けていた
    (2) 審査プロトコル正本(ccfAskText)のp2ルーブリックにp3のnde刻みが混入
    (3) 堀の線を75→70にしたのに審査依頼文テンプレ3箇所に75が残っていた
    (4) 買付順位の並び順が配分式と食い違っていた（v9.9.91で是正）
  いずれも「採点は正しいが、人に見せる文が古い」型。**採点が動かないので誰も気づかない。**

  2026-08-06の全点検でさらに3件見つかった（下の CHECKS に実装）:
    ・Ωの合成式の説明が**3本柱のまま**（コードは堀を足した4本柱・v9.9.36以降）
    ・質Qの説明が**3項のまま**（コードはv9.9.67でFを外して2項）
    ・配分式の説明に**E[r]の項が無い**（コードはv9.9.87で (Ω−70)×E[r]点÷50）

  値そのものは grep で追えるが、**「式の形」は grep で追えない**。だから
  「コード側の真の値を実際に読み出して、文中の主張と突き合わせる」形で書いてある。

思想:
  **採点ロジックには一切触れない。** この道具は読むだけで、何も書き換えない。
  検出したら人が直す。直し方まで出す（どの行の何を何に）。

使い方:
  python3 night/audit_docs.py           # 検査（失敗があれば終了コード1）
  python3 night/audit_docs.py --list    # 該当箇所の本文を出す
"""
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')

VERBOSE = '--list' in sys.argv


def load():
    with open(HTML, encoding='utf-8') as f:
        return f.read()


def strip_tags(s):
    return ' '.join(re.sub(r'<[^>]+>', '', s).split())


def line_of(h, idx):
    return h.count('\n', 0, idx) + 1


def in_js_comment(h, idx):
    """その位置が JS の行コメント/ブロックコメントの中か（＝歴史記述として許容される場所か）"""
    seg = h[max(0, idx - 4000):idx]
    nl = seg.rfind('\n')
    if seg.rfind('//') > nl:
        return True
    return seg.rfind('/*') > seg.rfind('*/')


# ─────────────────────────────────────────────────────────────────────
# コード側の「真の値」を index.html から読み出す
# ─────────────────────────────────────────────────────────────────────
def read_code_facts(h):
    f = {}

    m = re.search(r'evalScore\s*=\s*gm\(\[Q,sustain,F,moatIdx\],\[([\d.,\s]+)\]\)', h)
    f['omega_weights'] = [float(x) for x in m.group(1).split(',')] if m else None

    m = re.search(r'let Q\s*=\s*gm\(\[([^\]]+)\],\[([\d.,\s]+)\]\)', h)
    f['q_terms'] = [t.strip() for t in m.group(1).split(',')] if m else None
    f['q_weights'] = [float(x) for x in m.group(2).split(',')] if m else None

    m = re.search(r'const P\s*=\s*gm\(\[[^\]]+\],\[([\d.,\s]+)\]\)', h)
    f['p_weights'] = [float(x) for x in m.group(1).split(',')] if m else None

    # 持続の二本柱の重み。**本文が「MOAT > ROIC」と語れるのはここが pm>pr のときだけ**。
    #   2026-08-07の精査で、見出し2箇所が「MOAT > ROIC」なのに実装は 47.5 : 52.5（ROICの方が重い）
    #   という矛盾が見つかった。数値は grep で追えるが、**大小関係の主張**は追えなかったので検査に足す。
    m2 = re.search(r'sustain\s*=\s*gm\(\[pm,pr\],\[([\d.]+),\s*([\d.]+)\]\)', h)
    f['pillar_weights'] = (float(m2.group(1)), float(m2.group(2))) if m2 else None

    m = re.search(r'function ccfAllocScore\(c\)\{(.*?)\n\}', h, re.S)
    f['alloc_src'] = m.group(1) if m else ''
    f['alloc_uses_er'] = bool(m and 'erP' in m.group(1))
    # 配分の錨（合成点が Ω から何を引くか）。v9.9.93 で 70 → 0（＝引かない）。
    #   ここを実際のコードから読むのが肝——「式の形」は grep で追えないので、
    #   本文が古い錨を語っていても値の grep では捕まらない（2026-08-06に実際に踏んだ）。
    if m:
        mm = re.search(r'\(\(c&&c\.s\)\|\|0\)\s*-\s*(\d+)', m.group(1))
        f['alloc_anchor'] = int(mm.group(1)) if mm else 0
    else:
        f['alloc_anchor'] = None

    m = re.search(r'const CCF_MOAT_GATE\s*=\s*(\d+)', h)
    f['moat_gate'] = int(m.group(1)) if m else None

    m = re.search(r'const perLim\s*=\s*grower\?(\d+):(\d+)', h)
    f['per_lim'] = (int(m.group(1)), int(m.group(2))) if m else None

    m = re.search(r'const perCeil\s*=\s*Math\.max\((\d+),Math\.min\((\d+),', h)
    f['per_ceil'] = (int(m.group(1)), int(m.group(2))) if m else None

    m = re.search(r'const evCeil\s*=\s*Math\.max\((\d+),Math\.min\((\d+),', h)
    f['ev_ceil'] = (int(m.group(1)), int(m.group(2))) if m else None

    m = re.search(r'const evLimit\s*=\s*\(roicV>=30\?(\d+):roicV<15\?(\d+):(\d+)\)', h)
    f['ev_limit'] = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    # v9.9.171: 席の数は **CCF_SEATS 一箇所**へ移した（呼び出し側は引数を省く）。
    #   ⚠ 旧実装は `maxN=maxN||10` の即値を読んでいたので、定数化した瞬間に None＝
    #   **この検査が黙って止まる**（fail-open）。定数を第一に読み、旧形も後方互換で見る。
    m = re.search(r"const\s+CCF_SEATS\s*=\s*(\d+)", h) \
        or re.search(r"ccfAllocTop\(cands,\s*maxN\)\{\s*maxN\s*=\s*maxN\s*\|\|\s*(\d+)", h)
    f['alloc_n'] = int(m.group(1)) if m else None

    # 表示バージョン（<h1>のバッジ）と、ファイル内に現れる最大バージョン
    m = re.search(r'採点機\s*<span[^>]*>v(9\.9\.\d+)</span>', h)
    f['badge_version'] = m.group(1) if m else None
    vs = [int(x) for x in re.findall(r'v9\.9\.(\d+)', h)]
    f['max_version'] = '9.9.%d' % max(vs) if vs else None

    return f


# ─────────────────────────────────────────────────────────────────────
# 検査
# ─────────────────────────────────────────────────────────────────────
def check(h, f):
    """戻り: [(severity, key, message, [(line, excerpt), ...])]"""
    out = []

    def prose_hits(pattern):
        """表示テキスト（JSコメント外）に現れる箇所だけを返す"""
        hits = []
        for m in re.finditer(pattern, h):
            if in_js_comment(h, m.start()):
                continue
            hits.append((line_of(h, m.start()),
                         strip_tags(h[max(0, m.start() - 110):m.start() + 150])))
        return hits

    # ① Ωの合成式が「3本柱」のまま
    if f['omega_weights'] and len(f['omega_weights']) == 4:
        hits = prose_hits(r'Q<sup>0\.40</sup>|Q0\.40・持続0\.35')
        if hits:
            w = f['omega_weights']
            out.append(('FAIL', 'omega_formula',
                        'Ωの合成式の説明が**3本柱**のまま。コードは4本柱 '
                        'gm([Q,sustain,F,moatIdx],%s)＝堀の直接項(.13)が説明から抜けている（v9.9.36で追加）'
                        % (w,), hits))

    # ② 質Q の説明が3項のまま
    if f['q_terms'] and len(f['q_terms']) == 2:
        hits = prose_hits(r'質Q〉＝過去P\(40%\)|過去P\(40%\)・現在\(35%\)')
        if hits:
            out.append(('FAIL', 'q_formula',
                        '質Qの説明が「過去P(40%%)・現在(35%%)・未来要約(25%%)」の3項のまま。'
                        'コードは v9.9.67 でFを外して2項 Q=gm([%s],%s)'
                        % (','.join(f['q_terms']), f['q_weights']), hits))

    # ③ 配分式に E[r] が書かれていない
    if f['alloc_uses_er']:
        hits = prose_hits(r'\(Ω−70\)\s*÷\s*Σ\(Ω−70\)')
        if hits:
            out.append(('FAIL', 'alloc_formula',
                        '配分式の説明に**E[r]の項が無い**。コードは 合成点=(Ω−70)×E[r]点÷50 で、'
                        'E[r]≤2%は自動でウェイト0になる。"(Ω−70)÷Σ(Ω−70)" は v9.9.70 時点の旧式',
                        hits))

    # ③-b 配分の錨が本文とコードで食い違う（v9.9.93で 70→0）
    if f.get('alloc_anchor') is not None:
        hist = re.compile(r'当時|旧|v9\.9\.(70|87)|——|従来')
        hits = [x for x in prose_hits(r'合成点\s*[=＝]\s*\(Ω−(\d+)\)')
                if not hist.search(x[1])]
        if f['alloc_anchor'] == 0 and hits:
            out.append(('FAIL', 'alloc_anchor',
                        '配分の合成点を「(Ω−70)×E[r]点」と説明しているが、コードは錨を外して '
                        'Ω×E[r]点÷50（v9.9.93）。錨は相対差を12.5倍に増幅していたので、'
                        'どちらで読むかで配分の理解が変わる', hits))
        elif f['alloc_anchor'] != 0:
            bad = [x for x in prose_hits(r'合成点\s*[=＝]\s*Ω\s*×\s*E\[r\]点') if not hist.search(x[1])]
            if bad:
                out.append(('FAIL', 'alloc_anchor',
                            'コードは錨 %d を引いているのに、本文は錨なし(Ω×E[r]点)と説明している'
                            % f['alloc_anchor'], bad))

    # ④ 「門X4条件」が**操作指示として**残っている（v9.9.84で遮断器E[r]≥0の1条件へ）
    #    歴史記述（「いつ・こう変えた」の形で経緯を語る文）は残すのが正しい——CLAUDE.md が明示。
    #    audit_gate.js の「✓検算済 と 未解決 を分ける」と同じ作法: 鳴りすぎる警報は鳴らないのと同じ。
    #    ⚠ 印は**日付でも版番号でもよい**。画面から版番号を外した（読者には改版履歴が要らない）ので、
    #      版番号だけを印にしていると、同じ歴史記述が翌日から操作指示に見える。検査の意図は
    #      「日付つきの経緯か、今の操作指示か」であって、印がどちらの綴りかではない。
    hist = re.compile(r'(?:v9\.9\.\d+|\d{4}-\d\d-\d\d).{0,80}?'
                      r'(?:にした|した——|へ改定|から連続|旧・|旧式|当時|実測)')
    #    ⚠ 綴りを列挙で持つと**書き方が1つ違うだけで素通りする**。実際 2026-08-10 に
    #      「門X（✦超未来の門）4条件」（中黒と「裁きⅠ」が無い形）が四関門の操作指示に
    #      残っていたのを、この検査は見逃していた。→ 「門X …（20字以内）… 4条件」で拾う。
    hits = [x for x in prose_hits(r'門X(?:（[^）]{0,20}）)?の?4条件')
            if not hist.search(x[1])]
    if hits:
        out.append(('WARN', 'gatex_4conditions',
                    '「門X4条件」が**操作指示の位置に**残存。v9.9.84 で遮断器 E[r]≥0 の1条件になった',
                    hits))

    # ⑤ 配分の「8/5/3%」が操作指示として残っている
    hits = [x for x in prose_hits(r'8/5/3')
            if not re.search(r'旧|従来|かつて|廃止|→\s*連続|から連続|時点|実測|そのもの|上限とし', x[1])]
    if hits:
        out.append(('WARN', 'alloc_8_5_3',
                    '段差配分「8/5/3%」が歴史記述の体裁を取らずに残っている。'
                    'v9.9.70 で連続式へ移行済み', hits))

    # ⑥ V0上限の固定値表記
    if f['per_ceil'] and f['ev_ceil']:
        hits = prose_hits(r'V0上限60/45|V0絶対上限60')
        if hits:
            out.append(('FAIL', 'v0_ceiling',
                        'V0上限を「60/45」と固定値で説明している。コードは質連動の動的上限 '
                        'perCeil=clamp(q*0.75,%d,%d) / evCeil=clamp(q*0.56,%d,%d)'
                        % (f['per_ceil'][0], f['per_ceil'][1], f['ev_ceil'][0], f['ev_ceil'][1]),
                        hits))

    # ⑦ EV/EBIT の論外線を単一値で断定している
    if f['ev_limit']:
        hits = prose_hits(r'EV/EBIT\s*&gt;\s*35倍')
        if hits:
            out.append(('WARN', 'ev_limit_single',
                        'EV/EBITの論外線を35倍と断定しているが、コードはROIC文脈で %d/%d/%d に分岐する'
                        '（roic≥30→%d / roic<15→%d / それ以外→%d）'
                        % (f['ev_limit'][1], f['ev_limit'][2], f['ev_limit'][0],
                           f['ev_limit'][0], f['ev_limit'][1], f['ev_limit'][2]), hits))

    # ⑧ 表示バージョンが古い
    if f['badge_version'] and f['max_version'] and f['badge_version'] != f['max_version']:
        idx = h.find('採点機 <span')
        out.append(('WARN', 'version_badge',
                    '画面に出るバージョンが v%s だが、ファイル内の最新は v%s'
                    % (f['badge_version'], f['max_version']),
                    [(line_of(h, idx) if idx > 0 else 0, '採点機 v%s' % f['badge_version'])]))

    # ⑧-b 版番号の歴史記述が書き換わっていないか（v9.9.158・2026-08-19新設）
    #   ★実害を踏んで足した検査——v9.9.157 の作業で `sed 's/v9.9.156/v9.9.157/'` を index.html 全体へ
    #   掛けたため、**過去の版を指す歴史記述まで7箇所が書き換わった**（📈トータルリターンの v9.9.155 は
    #   二段階でクロバーされ v9.9.157 になっていた）。版番号を「今の版」に揃えてよいのは**バッジだけ**で、
    #   本文とコード注釈の版番号は**いつ何が入ったかの記録**＝書き換えたら記録が消える。
    #   検査は git の直前コミットと突き合わせる：**バッジ以外の行で版番号の値が変わっていたら鳴らす**。
    #   ⚠ git が無い／初回コミットでは黙って飛ばす（測れないことを異常と言わない・ルール7）。
    #   ⚠**マージ中は飛ばす**——版番号は別セッションと**衝突する**ことがあり（実測: main が v9.9.156/157 を
    #   別の変更で使っていた）、そのときは**こちらを繰り下げるのが正しい作法**（v9.9.118→119 の前例）。
    #   マージ中に HEAD と比べても、相手側の行が丸ごと増えるので比較そのものが意味を持たない。
    #   飛ばしたことは**黙らずに出す**（鳴らない検査を残さない）。コミット後は MERGE_HEAD が消えるのでCIには出ない。
    try:
        import subprocess, os
        if os.path.exists(os.path.join(ROOT, '.git', 'MERGE_HEAD')):
            out.append(('WARN', 'version_history_merge',
                        'マージ中のため版番号の歴史検査を飛ばした'
                        '（版番号は別セッションと衝突しうる＝繰り下げが正当に起きる）', []))
            raise StopIteration
        prev = subprocess.run(['git', 'show', 'HEAD:index.html'],
                              capture_output=True, text=True, timeout=20)
        if prev.returncode == 0 and prev.stdout:
            vre = re.compile(r'v9\.9\.\d+')
            def _k(l): return vre.sub('§', l)
            pmap = {}
            for l in prev.stdout.split('\n'):
                if vre.search(l):
                    pmap.setdefault(_k(l), l)
            moved = []
            for i, l in enumerate(h.split('\n')):
                if not vre.search(l) or '採点機' in l:
                    continue
                o = pmap.get(_k(l))
                # ★**上がった側だけ鳴らす**。一括sed の署名は「古い版 → 今上げようとしている版」で
                #   必ず**増える**向き。逆に**減る**のは今回のような**修復**なので通す
                #   （行の他の文字が変わっていれば _k が一致せずそもそも検査に掛からない
                #    ＝ここへ来るのは「版番号だけが違う同一行」＝sed の署名そのもの）。
                def _mx(x): return max((int(v.rsplit('.', 1)[1]) for v in vre.findall(x)), default=0)
                if o and vre.findall(o) != vre.findall(l) and _mx(l) > _mx(o):
                    moved.append((i + 1, '%s → %s ｜ %s'
                                  % (','.join(vre.findall(o)), ','.join(vre.findall(l)),
                                     strip_tags(l.strip())[:70])))
            if moved:
                out.append(('FAIL', 'version_history_rewritten',
                            '版番号の歴史記述が直前コミットから書き換わっている'
                            '（版を上げてよいのは採点機のバッジだけ。一括sedは歴史記述を巻き込む）',
                            moved))
    except Exception:
        pass

    # ⑨ 堀の関門の線が文中と一致するか
    if f['moat_gate']:
        bad = []
        for m in re.finditer(r'絶対MOAT指数\s*(\d+)\s*(?:以上|\+)', h):
            if in_js_comment(h, m.start()):
                continue
            if int(m.group(1)) != f['moat_gate']:
                bad.append((line_of(h, m.start()),
                            strip_tags(h[max(0, m.start() - 80):m.start() + 90])))
        if bad:
            out.append(('FAIL', 'moat_gate_line',
                        '堀の関門の線が本文とコードで食い違う（コード CCF_MOAT_GATE=%d）' % f['moat_gate'],
                        bad))

    # ⑩ 投下可の枠数が文中と一致するか
    if f['alloc_n']:
        bad = []
        for m in re.finditer(r'(?:合成点上位|Ω上位|irr=85優先→Ω順の上位)(\d+)社', h):
            if int(m.group(1)) != f['alloc_n']:
                bad.append((line_of(h, m.start()),
                            strip_tags(h[max(0, m.start() - 80):m.start() + 90])))
        if bad:
            out.append(('FAIL', 'alloc_seats',
                        '投下可の枠数が本文とコードで食い違う（コード maxN=%d）' % f['alloc_n'], bad))

    # ⑧ 二本柱の大小関係の主張が、実装の重みと食い違う（2026-08-07新設）
    #    実害: 見出し「★ 持続の二本柱 ― MOAT > ROIC」が2箇所あったが、実装は pm .475 / pr .525
    #    ＝ROICのほうが重い。数値の grep では捕まらない「大小関係」の型。
    if f.get('pillar_weights'):
        pm, pr = f['pillar_weights']
        if pm <= pr:
            hits = prose_hits(r'MOAT\s*(?:&gt;|＞|>)\s*ROIC')
            if hits:
                out.append(('FAIL', 'pillar_order',
                            'MOAT>ROIC と書いてあるが実装の重みは MOAT %.3f ≤ ROIC %.3f' % (pm, pr), hits))
        if pr <= pm:
            hits = prose_hits(r'ROIC\s*(?:&gt;|＞|>)\s*MOAT')
            if hits:
                out.append(('FAIL', 'pillar_order',
                            'ROIC>MOAT と書いてあるが実装の重みは ROIC %.3f ≤ MOAT %.3f' % (pr, pm), hits))

    # ⑨ 堀が「格下げ・保険」と説明されているのに、実装では四関門の一つ（2026-08-07新設）
    #    実害: 冒頭の一文と柱の副題が「MOATは陳腐化保険へ格下げ」のまま残っていた。
    #    v9.9.36で堀はΩの直接項(.13)になり、v9.9.39で絶対MOAT指数70+が関門になっている。
    #    **概念の主張はどの数値 grep にも掛からない**ので、語そのものを見張る。
    if f.get('moat_gate') and f.get('omega_weights') and len(f['omega_weights']) == 4:
        hits = prose_hits(r'MOATは陳腐化保険|MOAT.{0,12}保険へ格下げ|陳腐化保険へ格下げ')
        if hits:
            out.append(('FAIL', 'moat_demoted',
                        '堀を「陳腐化保険へ格下げ」と説明しているが、実装では Ω の直接項(%.2f)かつ'
                        '関門(絶対MOAT指数%d+)＝格下げされていない'
                        % (f['omega_weights'][3], f['moat_gate']), hits))

    return out


def main():
    h = load()
    f = read_code_facts(h)

    print('■ 説明文とコードの整合検査（night/audit_docs.py）')
    print('  コード側の実測値:')
    print('    Ωの重み        %s  （4本＝Q/sustain/F/moatIdx）' % (f['omega_weights'],))
    print('    Qの項と重み     %s %s' % (f['q_terms'], f['q_weights']))
    print('    配分式にE[r]    %s' % ('あり' if f['alloc_uses_er'] else 'なし'))
    print('    堀の関門        %s' % f['moat_gate'])
    print('    投下可の枠数    %s' % f['alloc_n'])
    print('    PER論外線       通常%s / grower%s' % (f['per_lim'][1], f['per_lim'][0]) if f['per_lim'] else '')
    print('    表示バージョン   v%s（ファイル内最新 v%s）' % (f['badge_version'], f['max_version']))
    print()

    res = check(h, f)
    fails = [r for r in res if r[0] == 'FAIL']
    warns = [r for r in res if r[0] == 'WARN']

    if not res:
        print('✓ 説明文とコードの齟齬なし')
        return 0

    for sev, key, msg, hits in res:
        mark = '✗ 要修正' if sev == 'FAIL' else '⚠ 警告  '
        print('%s [%s] %s' % (mark, key, msg))
        print('        該当 %d箇所: 行 %s' % (len(hits), ', '.join(str(x[0]) for x in hits[:12])))
        if VERBOSE:
            for ln, ex in hits[:6]:
                print('          行%-6s …%s' % (ln, ex[:150]))
        print()

    print('要修正 %d件 / 警告 %d件' % (len(fails), len(warns)))
    print('※ この道具は読むだけで採点に一切触れない（絶対のルール1）')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
