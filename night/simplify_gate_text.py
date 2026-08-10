#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/simplify_gate_text.py — **門の画面から「読む必要のない字」を外す**（2026-08-10新設）

ユーザー指示「もっとサイトをわかりやすくしたい。無駄な文字や表記を、なくしたい」。

何をするか（表示だけ。**採点・規則・閾値・売却規律には一切触れない**）:
  ① 画面に出る版番号 v9.9.xx を外す——改版履歴は読者の判断に一切効かない。
     ただし **コード注釈（<script> / <!-- -->）の版番号は残す**＝技術者向けの証跡は資産。
     採点機の見出しのバッジ1つだけは残す（どの版を見ているかは要る／audit_docs も見る）。
  ② 見出しから条件の全文再掲を外す（「投下可（Ω75+ × 堀70+ × …）」→「投下可」）。
     条件は直下の一行が言う。見出しは名前を言う場所。
  ③ **長い根拠・経緯を <details class="why"> で畳む**。**消さない**——
     index.html にしか無い記述があり、ここは正本だから（CLAUDE.md にも無い実測がある）。
     畳むのは「読む順」の問題であって、記録を捨てる話ではない。
  ④ 同じ規則の再掲を畳む（売却規律S1/S2/S3は同一ページに3回書かれていた。
     うち2回は本文自身が「全文は下段IPS③」と重複を認めている）。
  ⑤ 既存の誤記の是正（キリル文字 риск → リスク／配分式が旧版のまま残っていた1箇所）。

なぜスクリプトなのか:
  対象が 100 箇所を超え、手作業だと**取りこぼしと途中の壊れ**が必ず出る（実際、
  対話的に進めた初回は details の入れ子で DOM を壊した）。**再実行できる形**にしておけば、
  壊れたらいつでも `git checkout index.html && python3 night/simplify_gate_text.py` で
  同じ状態に戻せる。

使い方: python3 night/simplify_gate_text.py [--check]
  --check … 変換せずに、当てる予定の箇所が全部見つかるかだけ検査する（終了コード1で失敗）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
CHECK = '--check' in sys.argv

# 採点機の見出しに出るバッジ（どの版を見ているか）。ここだけは残す。
BADGE = re.compile(r'<span style="font-size:\.5em;color:var\(--mut\)">v9\.9\.\d+</span>')
NEWVER = 'v9.9.134'   # この掃除そのものの版（バッジと本文の版表示を揃える）

problems = []


def need(cond, msg):
    if not cond:
        problems.append(msg)
    return cond


# ── ① 版番号の掃除 ───────────────────────────────────────────────────
def strip_versions(t):
    t = re.sub(r'[（(]\s*v9\.9\.\d+\s*[）)]', '', t)              # （v9.9.NN）ごと消す
    t = re.sub(r'([（(])\s*v9\.9\.\d+\s*[・､、]\s*', r'\1', t)     # （v9.9.NN・中身）→（中身）
    t = re.sub(r'[・、]\s*v9\.9\.\d+(?=\s*[）)、。・])', '', t)     # 末尾に付く「・v9.9.NN」
    t = re.sub(r'v9\.9\.\d+\s*で', '', t)                        # 「v9.9.NNで廃止」→「廃止」
    t = re.sub(r'\s*v9\.9\.\d+\s*', '', t)                       # 残った裸の版番号
    # 掃除の後片付け
    t = re.sub(r'[（(]\s*[・､、]\s*', lambda m: m.group(0)[0], t)
    t = re.sub(r'[（(]\s*[）)]', '', t)
    t = re.sub(r'[・、]\s*[）)]', lambda m: m.group(0)[-1], t)
    t = re.sub(r'[・]{2,}', '・', t)
    t = re.sub(r'(（(?:<[^>]+>)*) +(?=[^\s<])', r'\1', t)          # 「（ 文字」の余分な空白
    J = r'[ぁ-んァ-ヶ一-龥、。・（）「」]'
    t = re.sub(r'(?<=%s) {2,}(?=%s)' % (J, J), '', t)             # 和文中の連続空白
    return t


def clean_visible(s):
    """<script>/<style>/コメントの**外**だけを掃除する（注釈の版番号は資産なので残す）"""
    out, prev = [], 0
    spans, pos = [], 0
    for m in re.finditer(r'<script.*?</script>|<style.*?</style>|<!--.*?-->', s, flags=re.S):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(s)))
    for a, b in spans:
        out.append(s[prev:a])
        seg = s[a:b]
        mb = BADGE.search(seg)
        if mb:
            seg = strip_versions(seg[:mb.start()]) + mb.group(0) + strip_versions(seg[mb.end():])
        else:
            seg = strip_versions(seg)
        out.append(seg)
        prev = b
    out.append(s[prev:])
    return ''.join(out)


def clean_rendered_js(s):
    """<script>の中でも、**画面に組み立てられる文字列**からは版番号を外す。
       コメント行・行末コメントは触らない。"""
    L = s.split('\n')
    for i, l in enumerate(L):
        if BADGE.search(l):
            continue
        st = l.strip()
        if st.startswith('//') or st.startswith('*') or st.startswith('/*'):
            continue
        if 'v9.9.' not in l:
            continue
        # 画面に出るのは (a) HTMLを組み立てている行 か (b) 和文の文字列リテラルを渡している行。
        # (b) を落とすと sec('🟢 投下可（…）') のような**タグを含まない見出し**を取りこぼす。
        rendered = (re.search(r'<(b|div|span|h2|u|code|br)[ >]', l)
                    or re.search(r"""['"`][^'"`]*[ぁ-んァ-ヶ一-龥][^'"`]*['"`]""", l))
        if not rendered:
            continue
        parts = re.split(r'((?<![:\w])//)', l, maxsplit=1)
        L[i] = strip_versions(parts[0]) + ''.join(parts[1:])
    return '\n'.join(L)


# ── ②〜⑤ 個別の置換 ──────────────────────────────────────────────────
# 掃除が残す破片・既存の誤記・見出しの整理。(旧, 新) で、旧が無ければ --check が落ちる。
REPLACEMENTS = [
    # 掃除の破片
    ('城60%（2026-08-03）', '城60%'),
    ('→（2026-08-03）で城60%へ実行済み', '→ 城60%へ実行済み'),
    ('（2026-07精査 →・2026-08-03に実測で更新し、', '（2026-07精査 → 実測で更新し、'),
    ('→（2026-08-03）で連続式 (Ω−70) へ実行済み', '→ 連続式 (Ω−70) へ実行済み'),
    ('残りをΩ順（/）', '残りをΩ順'),
    ('（滑走路）は 廃止</b>', '（滑走路）は廃止</b>'),
    ('堅実＝72以上</b>（再アンカー）', '堅実＝72以上</b>'),
    ('堀のふるいは追加＝採点は動かさず買付の土俵から降ろす',
     '堀のふるいは採点を動かさず買付の土俵から降ろす'),
    ('（ベト・／相手が主権政府なら', '（ベト／相手が主権政府なら'),
    ('<b>四関門（堀・点検を追加）</b>', '<b>四関門</b>'),
    ('（宣言を数学に一致——', '（宣言を数学に一致させた——'),
    ('（E[r]≥0・——旧4条件', '（E[r]≥0——旧4条件'),
    ('（。傾ける信号が実測で無いため等ウェイト）', '（傾ける信号が実測で無いため等ウェイト）'),

    # 既存の誤記（キリル文字が混入して読めなくなっていた）
    ('риск', 'リスク'),

    # 配分式が旧版（Ω按分）のまま取り残されていた。コードは等ウェイト（城60%÷社数）。
    # 同じページの他5箇所は既に「等ウェイト」と書いており、ここだけ古い。
    ('目標ウェイト: <b>城60% × Ω ÷ ΣΩ、1銘柄の上限8%</b>',
     '目標ウェイト: <b>城60% ÷ 投下可の社数（等ウェイト）、1銘柄の上限8%</b>'),

    # 見出しは「名前」だけにする。条件は直下の一行が言う。
    ('🟢 投下可（Ω75+〔irr=85は別枠〕 × 堀70+ × 点検0件・期末後の重大事象なし・納品検査FAIL0件 × <b>事業の収縮なし</b> × <b>irr=85優先→Ω順の上位10社（半導体連鎖は城の30%まで）</b>）</h2>',
     '🟢 投下可</h2>'),
    ('⛔ 堀不足で見送り（Ω75+だが絶対MOAT指数 &lt; 70、または存続級依存≥40%〔のベト〕）</h2>',
     '⛔ 堀不足で見送り</h2>'),
    ('⛔ 根拠の穴で見送り（納品検査 validate_packs の FAIL）</h2>',
     '⛔ 根拠の穴で見送り</h2>'),
    ('🔵 次点（四関門は通過・席順${MAXN+1}位以下＝買わない）</h2>',
     '🔵 次点</h2>'),
    # 見出しから外した条件を、直下の説明の冒頭へ短く戻す
    ('margin-bottom:6px">質・値段がどれだけ揃っても<b>買わない</b>組。',
     'margin-bottom:6px">Ω75+だが<b>絶対MOAT指数&lt;70</b>、または存続級依存≥40%（ベト）。質・値段がどれだけ揃っても<b>買わない</b>組。'),
    ('margin-bottom:6px"><b>値は入っているが根拠が無い</b>組。',
     'margin-bottom:6px">納品検査（validate_packs）がFAILした組＝<b>値は入っているが根拠が無い</b>。'),
    ('margin-bottom:6px">投下可の資格（Ω75+〔irr=85は別枠〕 ∧ 堀70+ ∧ 点検0件 ∧ 事業の収縮なし）は満たすが、',
     'margin-bottom:6px">四関門は通過したが席順${MAXN+1}位以下＝<b>買わない</b>。'),
    # 盤の見出しも同じ作法（条件は note 側へ）
    ("+ sec('🟢 投下可（四関門 × irr=85優先→Ω順の上位10社（半導体連鎖は城の30%まで））', buyHtml",
     "+ sec('🟢 投下可', buyHtml"),
    ("'買うのはここだけ。金額はⅥ買付順位の「今月の個別枠」で按分される')",
     "'買うのはここだけ（四関門を通り、席の上位10社に入った銘柄）。金額はⅥ買付順位の「今月の個別枠」で按分される')"),
    # ── 四関門の再掲がコードと食い違っていた（規則は変えない・文をコードへ合わせる）──
    #    実測: buyGate() は (Ω75+ or irr=85別枠) ∧ 堀 ∧ 点検err0 ∧ 未解決warn0
    #    ∧ 期末後なし ∧ 納品検査FAILなし ∧ 事業の収縮なし。門X4条件も遮断器E[r]≥0も既に無い。
    ('新規投下は四関門＝Ω75+ かつ 門X（✦超未来の門）4条件 かつ 絶対MOAT指数70+ かつ 点検の要修正0件</b>（価格ゲートは成長連動／堀のふるいは採点を動かさず買付の土俵から降ろす）。詳細は下段IPS①。',
     '新規投下は四関門＝Ω75+〔irr=85は別枠〕 かつ 絶対MOAT指数70+ かつ 点検の要修正0件 かつ 事業の収縮なし</b>（堀のふるいは採点を動かさず買付の土俵から降ろす）。詳細は下段IPS①。'),
    ('かつ 門X（✦超未来の門・裁きⅠ）の <b style="color:var(--gold-bright)">遮断器成立（E[r]≥0）</b>（2026-08-04 ユーザー明示指示「遮断器のみ実装しよう」。歴史検証の実測で価格・期待値の線は堀の中で選別力を持たず〔2013年703社: 安い側8.0%/年 vs 高い側8.5%・勝者13社中10社が線の外〕、旧4条件は勝者を弾く側に働いていた。残すのは「期待値がマイナス＝会社自身が減益を予想している型の極端」だけを弾く回路遮断器。E[r]の計算・表示・予実台帳は不変）',
     'かつ <b style="color:var(--gold-bright)">事業の収縮なし</b>（売上縮小 ∧ 営業利益率低下 でない）（<u>価格・期待値は合否から一切使わない</u>——歴史検証の実測で価格・期待値の線は堀の中で選別力を持たず〔2013年703社: 安い側8.0%/年 vs 高い側8.5%・勝者13社中10社が線の外〕、旧4条件（門X）も遮断器E[r]≥0も勝者を弾く側に働いていたため順に撤去した。代わりに置いたのがこの収縮の関門で、止めた群の恒久毀損はベースの5倍・止めた群の中央値も低い＝両方向とも正しい。E[r]の計算・表示・予実台帳は不変）'),
    ('価格ゲートは<b style="color:var(--gold-bright)">成長連動</b>で、実証成長×資本効率×堀無傷（grower）は一律の論外線',
     '価格の<b style="color:var(--gold-bright)">論外線（合否ではなく表示層の番人）</b>は成長連動で、実証成長×資本効率×堀無傷（grower）は一律の論外線'),
]

# ── ③④ 畳む（開始文字列, 終了文字列, 見出し, 終了を含むか）──────────────────
# **後ろから当てる**ので、前の置換で位置がずれない。入れ子は作らない。
FOLDS = [
    # Ⅵ 買付順位
    ('四関門を通過し、かつ<b>irr=85優先',
     '<b style="color:var(--gold-bright)">目標%</b>',
     '席の選び方——なぜ irr=85 を先に置くのか', False,
     '四関門（Ω75+〔irr=85は別枠〕・堀70+・点検0件・事業の収縮なし）を通り、<b>席の上位10社</b>に入った銘柄。買うのはここだけ。'),
    ('<b style="color:#c98c3c">各行の「倍率 N.Nx」',
     '<br><b style="color:#c98c3c">各行の「自己相対',
     '各行の「倍率 N.Nx」とは（合否には使わない）', False, None),
    ('<b style="color:#c98c3c">各行の「自己相対',
     '投下可の城内合計 ${cityFill',
     '各行の「自己相対 上位M%」とは（合否には使わない）', False, None),
    ('<b>価格の関門は門X 1本',
     '<br>各行の <span style="color:#8fc9a4">審査</span>',
     '価格・E[r]の扱い（なぜ合否に使わないのか）', False, None),
    ('【なぜ上限を置いたか】', '</span></div>`;',
     'なぜ半導体連鎖に上限を置くのか', False, None),
    ('堀は<b>深さ(支配シェア', '</div>`;',
     '堀の測り方と、数字が上がる道', False, None),
    ('台帳の上では、原本から測った値と', '</div>`;',
     'なぜ根拠の無い値を関門にしたのか', False, None),

    # Ⅰ 解説
    ('<span style="color:var(--gold-bright)">日本株は', '</span></div>',
     '規約の詳細と経緯（日本株門0・ROIC規約・堀のふるい ほか）', False, None),
    ('<b>v9.6＝欠測は保留', '門は失格を弾く番人であって',
     '旧版（v6.5〜v9.6）の改版履歴', False, None),
    ('旧式は Ω80/77/75 の線で8/5/3に割れ', '投下の四関門',
     'なぜ等ウェイトにしたか（旧式との実測比較・ケリー比率）', False, None),
    # 売却規律の再掲2箇所（正本＝IPS③は触らない）
    ('<b>S1 全売却検討</b>＝キル発生・スプレッド陥落・disrupt=threat・二本柱陥落　／　<b>S2 縮小検討</b>＝質スコア3期連続低下・キル前夜帯(nde',
     '保有比率超過<br>', 'S1/S2/S3 の中身', True, None),
    ('<b>S1 全売却検討</b>＝キル発生・スプレッド陥落・disrupt=threat・二本柱陥落　／　<b>S2 縮小検討</b>＝質スコア3期連続低下・キル前夜帯・erosion=active',
     '（詳細はIPS③）', 'S1/S2/S3 の中身', True, None),
]

WHY_CSS = """
/* ── 根拠の畳み（.why）────────────────────────────────────────────────
   規則そのものは常に見える。**なぜその規則なのか**（経緯・実測・却下した案）は
   畳んで置く。**消さない**——index.html にしか無い記述があり、ここは正本だから。
   畳むのは「読む順」の問題であって、記録を捨てる話ではない。 */
.why{margin:7px 0;border-left:2px solid var(--gold-line);padding-left:10px;}
.why>summary{cursor:pointer;list-style:none;color:var(--dim);font-size:11.5px;
  letter-spacing:.02em;padding:2px 0;transition:color .15s ease;}
.why>summary::-webkit-details-marker{display:none;}
.why>summary::before{content:"\\25B8 ";color:var(--gold);}
.why[open]>summary::before{content:"\\25BE ";}
.why>summary:hover{color:var(--gold-bright);}
.why-body{font-size:11.5px;color:var(--dim);line-height:1.85;margin-top:6px;}
</style>"""


def main():
    s = open(HTML, encoding='utf-8').read()
    before = len(s)

    # **一度きりの変換**（畳んだ後の文字列はもう見つからないので二度は当てられない）。
    # 二度目を「置換元が無い」という紛らわしい失敗にせず、適用済みだと言って何もしない。
    # やり直したいときは `git checkout index.html` してから回す。
    if '.why>summary' in s:
        print('既に適用済み（index.html に .why がある）。'
              'やり直すなら git checkout index.html してから回すこと。')
        return 0

    s = clean_visible(s)
    s = clean_rendered_js(s)

    for a, b in REPLACEMENTS:
        if not need(a in s, '置換元が見つからない: %s' % a[:60]):
            continue
        s = s.replace(a, b)

    # CSS を1回だけ入れる
    if need('.why>summary' not in s, '.why のCSSが既にある'):
        s = s.replace('</style>', WHY_CSS, 1)

    # 畳みは**後ろから**当てる（前の挿入で位置がずれないように）
    marks = []
    for a, b, label, incl, lead in FOLDS:
        x = s.find(a)
        if not need(x >= 0, '畳む開始が見つからない: %s' % a[:50]):
            continue
        y = s.find(b, x)
        if not need(y >= 0, '畳む終了が見つからない: %s' % b[:50]):
            continue
        marks.append((x, y + (len(b) if incl else 0), label, lead))
    # 入れ子・重なりが起きていないかを検査（初回はここで壊した）
    marks.sort()
    for i in range(1, len(marks)):
        need(marks[i][0] >= marks[i - 1][1],
             '畳む範囲が重なっている: %s と %s' % (marks[i - 1][2], marks[i][2]))

    if CHECK:
        if problems:
            print('✗ 当てられない箇所が %d 件' % len(problems))
            for p in problems:
                print('   -', p)
            return 1
        print('✓ 当てる予定の箇所はすべて見つかった（%d 置換 / %d 畳み）'
              % (len(REPLACEMENTS), len(marks)))
        return 0

    if problems:
        print('✗ 中止（当てられない箇所がある）:')
        for p in problems:
            print('   -', p)
        return 1

    for x, y, label, lead in reversed(marks):
        body = s[x:y]
        new = ((lead or '')
               + '<details class="why"><summary>%s</summary>' % label
               + '<div class="why-body">' + body + '</div></details>')
        s = s[:x] + new + s[y:]

    # details はブロック要素なので、直後に残った <br> が**空行になって見える**
    # （暗テーマの実機で発見）。畳んだ境界の <br> だけを落とす。
    s = s.replace('</details><br>', '</details>')

    # 版を上げる（audit_docs はバッジとファイル内最新版の一致を見る）
    s = BADGE.sub('<span style="font-size:.5em;color:var(--mut)">%s</span>' % NEWVER, s)
    s = s.replace('CCF \u03a9 \u63a1\u70b9\u6a5f', 'CCF \u03a9 \u63a1\u70b9\u6a5f')

    open(HTML, 'w', encoding='utf-8').write(s)
    print('index.html %d → %d 文字（−%d）／ 置換 %d 件・畳み %d 件'
          % (before, len(s), before - len(s), len(REPLACEMENTS), len(marks)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
