#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_mech_diff.py — **台帳に刻んだ機構文が、最新の原本にまだ在るか**（2026-08-11新設）

■ なぜ要るか（この台帳で最も重い一点）
  2026-08-05 の全数検算で確立した事実:「**irr欄の測定精度がそのまま門の精度になる**」。
  歴史検証がこの台帳で唯一「効く」と出した変数が irr=85 だからで、
  その85は**原本の文そのもの**（顧客の側が再認定の費用を負う、という断定）で決まる。
  ところが——**その文を機械で見張るものが一つも無かった。**
  新しい10-Kが出れば `enqueue_reaudit` が再審査を積むが、**読むのは人**。
  実際 LRCX の機構文が「一字同文で現存」と確認できたのは、2026-08-07 に人が読んだから。
  年に一度でも機械が差分を取れば、この欄の劣化が**声を上げる**ようになる。

■ ⚠ これは片側の検査であり、その片側性こそが正しい
  **文が消えたら赤信号。文が在っても安全ではない。**
  歴史で唯一壊れた85（CMTL・−17.2%/年・DD−96%）は**機構文を残したまま壊れた**。
  だから「在る」を合格の証拠に使ってはいけない——この道具は**消えたことだけを検出する**。
  ＝関門の作法（買わない理由は出す／買ってよい理由は出さない）と同じ向き。

■ 判定は一切変えない（読むだけ）
  Ω・採点式・四関門・堀の関門・売却規律・配分・別枠85 のどれにも触らない。
  出すのは out/irr85_mech_diff.json と画面だけ。消えていたら**門2再審査へ回す**のが人の仕事。

■ どう照合するか（ここが実装の全部）
  台帳の `_meta.evidence.irr` には原本の引用が『…』や ** ** で入っている。
  そこから**英文の引用だけ**を取り出し、最新の年次報告(10-K/20-F/40-F)の本文と照合する。
  ⚠素朴な文字列一致は必ず失敗する——引用には強調の `**`、省略の `…`、全角記号、
  改行由来の空白の揺れが混ざる。よって:
    (1) `**` と全角引用符を落とし、`…`/`...` で**断片へ割る**（省略をまたいで一致を求めない）
    (2) 空白・引用符・ダッシュを正規化し、**小文字化して**比較する
    (3) 断片が短すぎる（40字未満）ものは**照合に使わない**——偶然一致するため
    (4) 完全一致しなければ**語の連なり**で最長一致率を出す（言い換えは「弱まった」として警告）
  一致率の刻みは**新しい定数を作らない**——1.0=一字同文／0.8以上=ほぼ同文／それ未満=要確認。

使い方:
  python3 night/irr85_mech_diff.py            全 irr=85（既定）
  python3 night/irr85_mech_diff.py --t CW     1社だけ
  python3 night/irr85_mech_diff.py --json     out/irr85_mech_diff.json を書く
"""
import json
import os
import re
import unicodedata
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'night'))
import irr85_extract as EX          # get / cik_of / latest_annual / text_of を再利用（二重実装を作らない）

AS_JSON = '--json' in sys.argv[1:]
ONE = None
RUNG = '85'          # 既定は85（この器が作られた理由）
BUYONLY = '--buy' in sys.argv[1:]
for i, a in enumerate(sys.argv[1:]):
    if a == '--t' and i + 2 <= len(sys.argv[1:]):
        ONE = sys.argv[i + 2].upper()
    if a == '--rung' and i + 2 <= len(sys.argv[1:]):
        RUNG = sys.argv[i + 2]


def buy_band():
    """買付圏（🟢投下可 ＋ 🔵次点）を score_all から読む。**判定を再実装しない**。

    ★なぜ irr=70 では全社を対象にしないか（85 とは事情が違う）:
      85 は台帳に15社しかないので全数を見張れる。**70 は213社**あり、全数を対象にすると
      作業リストが埋まって「鳴りすぎる警報は鳴らないのと同じ」になる。
      一方で 70 の誤りが**現に費用を生む場所は買付圏だけ**——実測(shadow_irr_step)で
      判定圏の 70→50 は**投下可を10社→5社**にするが、50→70 も 85→70 も**0社しか動かさない**
      ＝**コストは 70→50 の一方向で、しかも買付圏に集中している**。
    """
    p = os.path.join('out', 'score_all.json')
    if not os.path.exists(p):
        return None
    rs = json.load(open(p, encoding='utf-8'))
    rs = rs['rows'] if isinstance(rs, dict) else rs
    buy = [r for r in rs if r.get('buy')]
    # 次点＝四関門を通っているが席に入っていない社（score_all の quali/buy で判る）
    nxt = [r for r in rs if r.get('quali') and not r.get('buy')]
    return {(r.get('t') or (r.get('nm') or '').split()[0]) for r in buy + nxt}

MIN_FRAG = 40          # これ未満の断片は照合に使わない（偶然一致する）
NEAR = 0.80            # 語の連なりの一致率がこれ以上なら「ほぼ同文」


def norm(s):
    """照合用に正規化——強調・引用符・ダッシュ・空白の揺れを消して小文字化

    ⚠**`**` は空白でなく空文字へ落とす**（2026-08-11の誤検出で判った）。
      markdown の `**` は語に密着するので、空白へ置くと**句読点の直前に空白が入る**——
      `certification**.` → `certification .` となり、本文の `certification.` と一致しなくなる。
      実害: ST の機構文は原本に**一字同文で現存している**のに「消えた/書き換わった」と鳴った
      （最長一致68%）。**鳴りすぎる警報は鳴らないのと同じ**なので、片側検査ほど誤検出を許さない。
      念のため句読点の直前の空白も畳む（引用の作法が変わっても壊れないように）。"""
    s = s.replace('**', '')
    s = re.sub(r'[“”„«»＂"\'’‘`]', ' ', s)
    # ⚠ダッシュ類は Unicode に十数種ある。**取りこぼすと誤検出が出る**（2026-08-19の実害）——
    #   RMD の原本は `cloud‑connected` に **U+2011 NON-BREAKING HYPHEN** を使っており、
    #   この一文字が対象外だったせいで機構文の一致が **28%** まで落ち、
    #   「消えた」側に見えていた（実際は一字も消えていない・数字が 30→35 million に伸びただけ）。
    #   `**` の取りこぼしで ST が誤検出した(2026-08-11)のと**同じ族の欠陥**。
    #   ⇒ 個別の文字を並べるのをやめ、**Unicode のダッシュ句読点(Pd)をまとめて**畳む。
    s = ''.join('-' if unicodedata.category(c) == 'Pd' else c for c in s)
    s = re.sub(r'[–—−ー\-]+', '-', s)
    s = re.sub(r'[\s　]+', ' ', s)
    s = re.sub(r'\s+([,.;:)])', r'\1', s)
    s = re.sub(r'([(])\s+', r'\1', s)
    return s.lower().strip()


def quotes_of(ev):
    """根拠テキストから**英文の引用だけ**を取り出し、省略記号で断片へ割る"""
    if not ev:
        return []
    out = []
    # 『…』／「…」／'…'（全角・半角）に囲まれた塊を拾う
    for m in re.finditer(r'[『「](.+?)[』」]', ev, re.S):
        out.append(m.group(1))
    frags = []
    for q in out:
        for part in re.split(r'…+|\.\.\.+', q):
            p = part.strip(' 　*・,')
            # 英文であること（ラテン文字が主体）＋十分な長さ
            letters = sum(ch.isascii() and ch.isalpha() for ch in p)
            if letters >= MIN_FRAG and letters / max(len(p), 1) > 0.5:
                frags.append(p)
    # 長い順（強い証拠から当てる）・重複を落とす
    seen, uniq = set(), []
    for f in sorted(frags, key=len, reverse=True):
        k = norm(f)
        if k in seen:
            continue
        seen.add(k); uniq.append(f)
    return uniq[:6]


def best_run(frag, body):
    """完全一致しないとき、語の連なりの最長一致率と**どこで切れたか**を返す

    ⚠ **切れた箇所を返すのが本体**。初版は率だけ返し、画面には引用の先頭180字を出していたので
      **一致した部分ばかり見せて、壊れた部分を隠していた**（ST の誤検出でそれに気づけなかった）。
      検査は「鳴った理由」を見せなければ、鳴っていないのと同じ。"""
    w = norm(frag).split()
    if not w:
        return 0.0, ''
    best, at = 0, 0
    for i in range(len(w)):
        # i から始まる最長の連なりを素直に伸ばす（断片は数十語なので十分速い）
        j = i
        while j < len(w) and (' ' + ' '.join(w[i:j + 1]) + ' ') in body:
            j += 1
        if j - i > best:
            best, at = j - i, j
    tail = ' '.join(w[max(0, at - 5):at + 8]) if best < len(w) else ''
    return round(best / len(w), 3), tail


NUMRE = re.compile(r'[\d][\d,.\u00a0]*')


def num_masked(frag, body):
    """★数字を伏せて照合し直す。**「消えた」と「数字が更新された」を分ける。**

    実測でこの穴を踏んだ: RMD の70の根拠は
      『leverage our installed base of **more than 30 million** patients ... on AirView
        and over **10 million** patients registered to our myAir platform』
    だが最新10-K(filed 2026-08-13)では **35 million / 12 million** になっており、
    逐語一致が **28%** まで落ちて「消えた」側に見えた。
    ⚠ **実際は消えていない。伸びていた。**

    ここが厄介なのは向きで——実数を開示している機構文ほど強い根拠なのに、
    **事業が伸びるほどこの検査に落ちる**。つまり**最も良い証拠を最も罰する**検査になっていた。
    ⇒ 数字を伏せた形が高一致なら「数字が更新された」として別に出し、
       **旧→新の数字を必ず並べる**（黙って通すと、事業が縮んで数字が下がった場合まで見逃す）。
    """
    # ⚠**伏せた後に必ず正規化し直す**。body は既に正規化済みなので、そこへ ' # ' を差し込むと
    #   `... than  #  million ...` と**空白が二重になる**。片側だけ norm() を掛けると
    #   一致率が 0.36 のまま落ちて「数字が更新された」を検出できない（2026-08-19に実際に踏んだ）。
    fa, ba = norm(NUMRE.sub(' # ', frag)), norm(NUMRE.sub(' # ', body))
    hit = (' ' + fa + ' ') in ba or fa in ba
    if not hit:
        r, _ = best_run(fa, ba)
        if r < 0.9:
            return None
    olds = [x.strip() for x in NUMRE.findall(frag) if len(x.strip()) > 1]
    # ★新しい数字は「伏せた形が一致した位置」の**正規化済み本文**から取る。
    #   ⚠生の body から取ってはいけない——正規化で長さが変わっているので位置が合わず、
    #   まったく別の段落の数字を「新しい値」として並べることになる（実際に空で返っていた）。
    news = []
    # ★位置は**正規化済みの本文そのもの**で探す。伏せた文字列 ba は ' # ' への置換で
    #   長さが変わっているので、そこで得た位置を norm(body) に当てると別の段落を読む。
    #   head は最初の数字より前なので数字を含まず、両方に同じ形で存在する。
    nb = norm(body)
    head = fa.split(' # ')[0][-60:]
    j = nb.find(head)
    if j >= 0:
        seg = nb[j:j + len(frag) + 160]
        news = [x.strip() for x in NUMRE.findall(seg) if len(x.strip()) > 1][:len(olds)]
    return {'old': olds[:4], 'new': news[:4]}


def sibling_body(cik, url):
    """同じ提出物の中で**最大の .htm**（主文書を除く）を読む。見つからなければ None。

    ⚠ いつも読むのではなく「本体で当たらなかったとき」だけ呼ぶ——
      無条件に足すと、無関係な添付（報酬契約・子会社一覧）の語で偶然一致して
      **「在る」を偽造する**。この器は片側の検査なので、偽の「在る」がいちばん危ない。
    """
    try:
        acc = url.rsplit('/', 2)[-2]
        prim = url.rsplit('/', 1)[-1]
        idx = json.loads(EX.get(f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/index.json'))
        cand = [it for it in idx['directory']['item']
                if it['name'].endswith('.htm') and it['name'] != prim
                and not it['name'].startswith('R') and int(it.get('size') or 0) > 500_000]
        if not cand:
            return None
        big = max(cand, key=lambda x: int(x.get('size') or 0))
        u = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{big['name']}"
        return norm(EX.text_of(u)), big['name']
    except Exception:
        return None


def main():
    BAND = buy_band() if BUYONLY else None
    if BUYONLY and BAND is None:
        print('⚠ out/score_all.json が無いので買付圏を絞れない。'
              '**全社を対象にしたと誤解しないよう中止する**（0件を「異常なし」と読ませない）')
        return 1
    packs = []
    for f in sorted(os.listdir('out')):
        if not f.endswith('_gate_pack.json'):
            continue
        d = json.load(open('out/' + f, encoding='utf-8'))
        dd = d.get('data') or d
        if str(dd.get('irr')) != str(RUNG):
            continue
        t = f.split('_gate_pack')[0]
        if ONE and t != ONE:
            continue
        if BUYONLY and BAND is not None and t not in BAND:
            continue
        packs.append((t, d))

    label = f'irr={RUNG}' + ('・買付圏(投下可+次点)のみ' if BUYONLY else '')
    print(f'■ 機構文の年次diff（{label}・{len(packs)}社）'
          ' — **台帳に刻んだ引用が、最新の原本にまだ在るか**')
    print('  ⚠片側の検査: **消えたら赤信号／在っても安全ではない**')
    print('    （歴史で唯一壊れた85=CMTL は機構文を残したまま壊れた。'
          '在ることを合格の証拠に使わない）\n')
    out, alerts = {}, []
    for t, d in packs:
        ev = ((d.get('_meta') or {}).get('evidence') or {}).get('irr') or ''
        rd = str((d.get('_meta') or {}).get('reportDate') or '')[:10]
        frags = quotes_of(ev)
        rec = dict(pack_report=rd, n_quotes=len(frags))
        if not frags:
            rec['verdict'] = '照合不能'
            rec['why'] = '根拠に英文の引用が無い（要約だけ）＝差分を取る対象が無い'
            out[t] = rec
            print(f'  {t:6s} 照合不能  根拠に英文の引用が無い（要約のみ・{len(ev)}字）')
            alerts.append((t, 'quote'))
            continue
        try:
            cik = EX.cik_of(t)
            fi = EX.latest_annual(cik)
            body = ' ' + norm(EX.text_of(fi['url'])) + ' '
            rec['body_doc'] = fi['url'].rsplit('/', 1)[-1]
        except SystemExit as e:
            rec['verdict'] = '照合不能'; rec['why'] = f'原本が取れない（{e}）'
            out[t] = rec
            print(f'  {t:6s} 照合不能  原本が取れない（ADR/日本株など）')
            continue
        rec.update(form=fi['form'], filed=fi['filed'], report=fi['report'], url=fi['url'],
                   newer_than_pack=(fi['report'] > rd))
        # ★20-F は「本体は薄い殻で、中身は添付のアニュアルレポート」のことがある。
        #   実測 RELX: 本体 relx-...x20f.htm 2.1MB に対し ex15d2 が **6.6MB**——
        #   本体だけ読むと C.L.U.E./Westlaw が0回になり「機構文が消えた」と**誤報する**。
        #   ⚠これは「消えた」ではなく**同じ提出物の別のファイルに在る**だけ。
        #   ⇒ 本体で当たらなかったときに限り、同じ accession の中で最大の .htm も見る。
        #   （ASML/SAP/RACE は自己完結なので発火しない＝いつも添付を読むわけではない）
        if any(((' ' + norm(fr) + ' ') not in body and norm(fr) not in body) for fr in frags):
            ex = sibling_body(cik, fi['url'])
            if ex:
                body += ' ' + ex[0] + ' '
                rec['also_read'] = ex[1]

        res = []
        for fr in frags:
            exact = (' ' + norm(fr) + ' ') in body or norm(fr) in body
            if exact:
                r, tail = 1.0, ''
            else:
                r, tail = best_run(fr, body)
            row = dict(frag=fr[:180], match=r, broke_at=tail)
            if not exact and r < 0.8:
                nm_ = num_masked(fr, body)
                if nm_:
                    row['numbers_updated'] = nm_
            res.append(row)
        rec['fragments'] = res
        top = max(r['match'] for r in res)
        low = min(r['match'] for r in res)
        rec['best_match'] = top
        rec['min_match'] = low
        # ⚠**verdict は max のまま**——根拠には**他社の比較引用**が混ざる
        #   （CW に TDG の文、HXL に LOAR/RBC の文、KRMN に LOAR の文…「同型」を論じるため）。
        #   他社の文はこの社の原本には原理的に無いので、min で裁くと必ず誤検出する。
        #   ＝**鳴りすぎる警報は鳴らないのと同じ**（片側検査ほど誤検出を許さない）。
        rec['low_frags'] = [dict(match=r['match'], frag=r['frag'],
                                 numbers_updated=r.get('numbers_updated'))
                            for r in res if r['match'] < NEAR]
        if top >= 1.0:
            rec['verdict'] = '✓一字同文'
        elif top >= NEAR:
            rec['verdict'] = '△ほぼ同文'
        else:
            rec['verdict'] = '⚠消えた/書き換わった'
            alerts.append((t, 'gone'))
        newer = '（パックより新しい原本）' if rec['newer_than_pack'] else ''
        print(f"  {t:6s} {rec['verdict']:<12s} 最長一致 {top:.0%}"
              f"  {fi['form']} {fi['report']} filed {fi['filed']} {newer}")
        if top < NEAR:
            for r in res:
                # **切れた箇所**を出す（引用の先頭ではなく、一致が途切れた語のまわり）
                print(f'         一致{r["match"]:.0%}  切れた箇所: 「…{r["broke_at"]}…」')
        elif rec['low_frags']:
            # ★2026-08-12 追加。**verdict が緑でも、欠けた断片は必ず名指しで出す。**
            #   実害で判った——ENTG は台帳の4断片のうち **2018年ビンテージで85を支えた当の文**
            #   『high customer re-formulation and qualification change costs』が2025年10-Kから
            #   **消えている**（一致14%）のに、max=100% で ✓一字同文 と表示されていた。
            #   ＝この道具の存在理由（消えたら赤信号）を、集計の仕方が自分で打ち消していた。
            for r in rec['low_frags']:
                nu = r.get('numbers_updated')
                if nu:
                    print(f'         ↗数字が更新された 一致{r["match"]:.0%}: 「{r["frag"][:80]}…」')
                    print(f'            旧 {nu["old"]} → 新 {nu["new"]}  '
                          '＝**機構文は消えていない**（伸びた/縮んだのは実数）')
                else:
                    print(f'         ⚠要確認 一致{r["match"]:.0%}: 「{r["frag"][:96]}…」')
            if any(not r.get('numbers_updated') for r in rec['low_frags']):
                print('           ↑ 他社の比較引用ならこれで正常。**この社自身の機構文なら消えている**')
        out[t] = rec

    gone = [t for t, k in alerts if k == 'gone']
    noq = [t for t, k in alerts if k == 'quote']
    print(f"\n  対象 {len(out)}社　"
          f"✓一字同文 {sum(1 for r in out.values() if r.get('verdict')=='✓一字同文')} / "
          f"△ほぼ同文 {sum(1 for r in out.values() if r.get('verdict')=='△ほぼ同文')} / "
          f"⚠消えた {len(gone)} / 照合不能 {sum(1 for r in out.values() if r.get('verdict')=='照合不能')}")
    if gone:
        print(f'\n  ⚠⚠ **機構文が消えた/書き換わった {len(gone)}社**: {" ".join(gone)}')
        print('     → 門2再審査へ回すこと。irr の刻みが下がれば堀が動き、'
              '別枠85・席の優先の両方が外れる（判定はこの道具ではなく審査が下す）')
    lowlist = [t for t, r in out.items() if r.get('low_frags')]
    if lowlist:
        print(f'\n  ⚠ **verdict は緑だが欠けた断片を持つ {len(lowlist)}社**: {" ".join(lowlist)}')
        print('     verdict は max で裁く（根拠に他社の比較引用が混ざるので min では必ず誤検出する）。'
              'その代わり欠けた断片は必ず上に名指しで出す——**他社の引用なら正常／自社の機構文なら消えている**')
    if noq:
        print(f'\n  ・根拠に英文の引用が無い {len(noq)}社: {" ".join(noq)}')
        print('     ＝**差分を取る対象そのものが無い**。次の再審査で原本の一文を引用として刻むこと')
    if AS_JSON:
        p = 'out/irr85_mech_diff.json'
        json.dump(dict(generated=str(__import__('datetime').date.today()),
                       note=('台帳 _meta.evidence.irr の英文引用が最新の年次報告にまだ在るかを照合する。'
                             '**片側の検査**——消えたら赤信号／在っても安全ではない'
                             '（CMTL は機構文を残したまま −17.2%/年で壊れた）。判定には一切使わない。'),
                       gone=gone, no_quote=noq, items=out),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
