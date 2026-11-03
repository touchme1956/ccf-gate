#!/usr/bin/env python3
"""ami_digest.py — ETFの門（ami.html）の『📚 歴史検証』タブが読む要約を作る（2026-11-03新設・読むだけ）

これまでの歴史検証の出力（out/*.json）から、グラフにする数字だけを抜き出して out/ami_digest.json にまとめる。
**新しい計算はしない**——各カードの数字は元のファイルの値そのまま（丸めだけ）。元のファイルの形が変わって
読めなくなったカードは黙って消さず、`err` に理由を書いて画面に「読めなかった」と出す（v9.9.52 の作法）。
判定・配分には使わない。

カードの形: {id, title, q（問い）, a（答えの一言）, src（元のファイル）, date, chart, table?, notes?}
  chart = {type:'bar'|'hbar'|'scatter'|'tiles', …}
"""
import json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out', 'ami_digest.json')


def J(name):
    with open(os.path.join(ROOT, 'out', name + '.json'), encoding='utf-8') as f:
        return json.load(f)


def r1(x, n=1):
    return None if x is None else round(float(x), n)


CARDS = []


def card(fn):
    CARDS.append(fn)
    return fn


@card
def forms():
    d = J('ndx40_form_check')
    F = d['形ごとの物差し']
    rename = {'今': '前の形（10-29〜）', '案': '案（NDX40/SMH25/…/VBR10）', '芯の答え': '芯の答え',
              '案の隣 SMH→VBR': '★今の形（11-02〜）'}
    pts, rows = [], []
    for k, v in F.items():
        lab = rename.get(k, k.replace('案の隣 ', '案の隣: '))
        pts.append(dict(label=lab, x=v['元']['最大下落'], y=v['元']['P15π'], hl=k in rename, star=k == '案の隣 SMH→VBR'))
        if k in rename:
            rows.append([lab, v['名前'], v['元']['P15π'], v['元']['平均'], v['元']['最大下落'],
                         v['基礎率']['平均'], v['百年']['三十年の中央'], v['実績']['年15パーセント以上の割合']])
    rows.sort(key=lambda r: (not r[0].startswith('★'), r[0]))
    return dict(id='forms', title='配分の形ごとの物差し（今の形を決めたときの比べ）',
                q='NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15 は、隣の形と比べてどこにいるか',
                a='今の形は15%以上の確率をほとんど落とさずに最大下落を約6pt浅くし、100年の代用と基礎率の物差しで上がった。代わりに2000年以降の実績（年15%以上の窓）は下がる。',
                src='out/ndx40_form_check.json', date=d['generated'],
                chart=dict(type='scatter', points=pts, xlab='最大下落（%・右ほど浅い）', ylab='年率15%以上の確率 P15π（%）'),
                table=dict(head=['', '形', 'P15π', '平均の年率', '最大下落', '基礎率の平均', '100年30年中央', '実績 年15%以上の窓'], rows=rows))


@card
def worlds():
    d = J('etf_forward_rank')
    t = sorted(d['table'], key=lambda r: -r['平均(%/年)'])[:16]
    return dict(id='worlds', title='これからの ETF を4つの世界で並べる',
                q='直近26年・直近15年・100年の平均・機関の予想の4つの世界の平均で、どの ETF が上か',
                a=f"1位 {t[0]['t']}（{t[0]['ja']}）{t[0]['平均(%/年)']}%/年。ただし1位は直近15年の年30%に頼り、最悪の世界では順位が大きく下がる。",
                src='out/etf_forward_rank.json', date=d['generated'],
                chart=dict(type='hbar', labels=[f"{r['t']} {r['ja']}" for r in t],
                           series=[dict(name='4つの世界の平均', values=[r['平均(%/年)'] for r in t]),
                                   dict(name='最悪の世界', values=[r['最悪の世界(%/年)'] for r in t])], unit='%/年'))


@card
def century():
    d = J('industry_century')['results']
    rows = sorted(d['業種ごと（市場との差の大きい順）'].values(), key=lambda v: -v['市場との差'])
    pick = rows[:12] + rows[-6:]
    p = d['持続の確かめ（前半の勝者は後半も勝ったか）']
    return dict(id='century', title='100年で市場に勝ってきた業種（1926〜）',
                q='Ken French の49業種で、どの業種が100年で市場を上回ったか。前半の勝者は後半も勝ったか',
                a=f"前半（〜1975）の上位10のうち後半も市場に勝ったのは {p['前半の上位10のうち後半も市場に勝った数']} つだけ（前半と後半の順位の相関 {p['前半と後半の順位の相関']}）。両方で勝ったのは {'・'.join(d['前半も後半も市場に勝った100年組'])}。",
                src='out/industry_century.json', date=J('industry_century')['generated'],
                chart=dict(type='hbar', labels=[f"{v['業種']}" for v in pick],
                           series=[dict(name='市場との差', values=[v['市場との差'] for v in pick])], unit='%pt/年', diverge=True,
                           gapAfter=11))


@card
def techdecades():
    d = J('tech_persist')
    T = d['テック3業種(Hardw/Softw/Chips 等分)']
    ks = [k for k in T if k != '全期間']
    q1 = d['Q1_業種の持続']['次の10年']['全起点（重なる）']
    p = d['事後_過去10年1位の業種の次の10年']
    return dict(id='techdecades', title='テックは時代で勝ったり負けたり（1965〜）',
                q='テック3業種（コンピュータ・ソフト・半導体）の市場との差は、時代でどう振れたか',
                a=f"1990年代 +{T['1990-1999']['差']}・2000年代 {T['2000-2009']['差']}%pt/年。全期間では {T['全期間']['差']:+}。過去10年の上位5業種が次の10年も勝ったのは {round(q1['上位5 勝率']*100)}%、1位の業種は {round(p['勝率']*100)}%（中央 {p['中央']}%/年）。",
                src='out/tech_persist.json', date=d['generated'],
                chart=dict(type='bar', labels=ks, series=[dict(name='テック − 市場', values=[T[k]['差'] for k in ks])], unit='%pt/年', diverge=True),
                table=dict(head=['起点', '過去10年の1位', '次の10年の市場との差'], rows=[[a, b, c] for a, b, c in p['10年刻み']]))


@card
def peak():
    d = J('industry_peak')
    m = d['主_閾値5%・次の10年・山ごと']
    c = d['比較群_記録でない年(比重5%以上)・10年']
    rec = d['記録の後_5年以内にもう一度記録が来た割合(その時点の基礎率)']
    path = d['道筋_山ごと']
    ks = [k for k in path]
    return dict(id='peak', title='比重が「過去最大」になった業種のその後',
                q='市場の中の比重が100年で最大を付けた業種は、次の10年に市場に勝ったか（今のソフトウェアと半導体がそこにいる）',
                a=f"勝った山 {m['勝った山']}（中央 {m['中央値(%/年)']}%/年・比較群 {c['中央値(%/年)']}%/年）。ただし記録の後5年以内にもう一度記録が来たのは {round(rec['割合']*100)}%＝どれが最後の山かはその時点では分からない。",
                src='out/industry_peak.json', date=d['generated'],
                chart=dict(type='bar', labels=ks, series=[dict(name='市場との差の中央値', values=[path[k]['中央値(%/年)'] for k in ks])], unit='%/年', diverge=True,
                           sub=[f"勝ち {path[k]['勝った山']}" for k in ks]))


@card
def underwater():
    d = J('etf_long_windows')
    R = d['rows']
    D = d['★毎月積立(DCA)']['20y']
    ks = sorted(R, key=lambda k: -R[k]['水没_最長月数'])
    return dict(id='underwater', title='高値を取り戻すまでの最長の年数（水没）',
                q='自分の過去最高値を下回り続けた最長の期間は。20年の毎月の積立なら S&P500 に勝ったか',
                a=f"SMH {round(R['SMH']['水没_最長月数']/12,1)}年・XLK {round(R['XLK']['水没_最長月数']/12,1)}年・QQQ {round(R['QQQ']['水没_最長月数']/12,1)}年に対し SPY {round(R['SPY']['水没_最長月数']/12,1)}年。それでも20年の毎月の積立では SMH・XLK・QQQ はすべての窓で SPY を上回った（一括では負ける窓がある）。⚠ 天井の後に生まれた ETF は水没が短く見える。",
                src='out/etf_long_windows.json', date=d['generated'],
                chart=dict(type='hbar', labels=[f"{k}（{R[k]['開始']}〜）" for k in ks],
                           series=[dict(name='水没の最長', values=[round(R[k]['水没_最長月数'] / 12, 1) for k in ks])], unit='年'),
                table=dict(head=['ETF', '20年積立の窓', 'SPY に勝った割合', '倍率比の中央', '倍率比の最小'],
                           rows=[[k, v['n'], f"{round(v['勝率']*100)}%", v['倍率比_中央値'], v['倍率比_最小']] for k, v in D.items()]))


@card
def exposure():
    d = J('industry_exposure')
    mk = d['米国市場全体(French・2025年末)']
    now = d['今の保有']
    rows = (now.get('業種(French寄せ)') or now.get('業種(EDGAR)'))[:10]
    return dict(id='exposure', title='自分のお金の業種（ETF の中身まで分解）',
                q='今の保有をETFの中身まで分けると、どの業種にどれだけ入っているか',
                a=f"米国株全体ではソフトウェア＋半導体・電子部品が {mk['二つの合計(%)']}%。今の保有は二つで {round(sum(r['%'] for r in rows if r['業種'] in ('Softw','Chips')),1)}%。",
                src='out/industry_exposure.json', date=d['generated'],
                notes=[now.get('label', '')],
                chart=dict(type='hbar', labels=[r['ja'] for r in rows], series=[dict(name='今の保有', values=[r['%'] for r in rows])], unit='%'))


@card
def candidates():
    d = J('etf_add_check')
    jd = d['judgments']
    order = {'堅い価値あり': 0, '前提しだい': 1, '差が小さい': 2, '堅い価値なし〜小さい': 3, '価値なし': 4}
    rows = []
    for t, v in jd.items():
        m = v.get('USD・崩れあり（主）') or next(iter(v.values()))
        dd = (m.get('感度', {}).get('主', {}) or {}).get('差', {})
        rows.append([t, m.get('まとめ'), r1(dd.get('平均'), 2), r1(dd.get('確率'), 2), r1(dd.get('最大下落'), 1)])
    rows.sort(key=lambda r: (order.get(r[1], 9), -(r[2] or -9)))
    return dict(id='candidates', title='今の形に1本足すならどの ETF か（NASDAQ100 から5%）',
                q=d['question'], a=d['reading']['Q1']['読み'] + '。ただし分散の上乗せの仮定に頼る（保険の変更）。',
                src='out/etf_add_check.json', date=d['generated'],
                chart=dict(type='hbar', labels=[r[0] for r in rows[:14]],
                           series=[dict(name='平均の年率の差', values=[r[2] for r in rows[:14]])], unit='%pt', diverge=True),
                table=dict(head=['ETF', '判定（主の枠）', 'Δ平均の年率', 'Δ15%以上の確率', 'Δ最大下落（+＝浅い）'], rows=rows))


@card
def rebalance():
    d = J('rebalance_policy')
    W, names = d['windows'], d['policies']
    rows = []
    for p, nm in names.items():
        rows.append([nm] + [f"{W[w][p]['median']:.3f}（最悪 {W[w][p]['worst']:.3f}）" for w in ('10y', '15y', '20y')]
                    + [f"{round(W['20y'][p]['smh_share_max']*100)}%"])
    return dict(id='rebalance', title='積立の比率の戻し方（売らない／毎月／年1回）',
                q='目標の比率からずれたとき、売って戻すべきか、新しい入金を足りないほうへ回すだけでよいか（' + d['why'] + '）',
                a='最終の資産は戻し方でほとんど変わらない（放置を1として±1.5%以内）。売らずに足りないほうへ回す（今の注文書）で足りる。売って戻すと SMH の比率の暴れは抑えられるが、課税と NISA の枠の分は引いていない。',
                src='out/rebalance_policy.json', date=f"{d['months'][0]}〜{d['months'][1]}",
                chart=dict(type='bar', labels=[names[p] for p in names],
                           series=[dict(name=w + '窓の中央（放置=1）', values=[W[w][p]['median'] for p in names]) for w in ('10y', '15y', '20y')],
                           unit='倍', base=1.0),
                table=dict(head=['戻し方', '10年', '15年', '20年', '20年の SMH の比率の最大'], rows=rows))


@card
def drawdowns():
    d = J('sp500_compare')
    R = d['results']['下げの局面の累計（USD）']
    ks = list(R)
    forms = list(next(iter(R.values())))
    return dict(id='drawdowns', title='大きな下げの局面で何%落ちたか（2026-10-15 の形）',
                q='ITバブル崩壊・金融危機・コロナ・2022年の下げで、当時の配分の形と S&P500・NASDAQ100 はどれだけ落ちたか',
                a='テック寄りの形は ITバブル崩壊で S&P500 より大きく落ちたが、金融危機とコロナでは同じか浅かった。下の『配合を歴史で試す』で今の形を同じ期間で測れる。',
                src='out/sp500_compare.json', date=d['generated'],
                chart=dict(type='bar', labels=ks, series=[dict(name=f.replace('（2026-10-15〜・ETF 側）', '（10-15の形）'), values=[R[k][f] for k in ks]) for f in forms], unit='%'))


@card
def search():
    d = J('mw_summary')
    A = d['angles']
    surv = sum(len(x.get('survivors_SA_after_verify') or []) for x in A)
    ver = sum(1 for x in A if x.get('verified'))
    top = sorted(A, key=lambda x: -x['n_tested'])[:12]
    return dict(id='search', title='市場に勝てる規則を探した（mw）',
                q='事前登録と反証つきで、S&P500 型の市場に勝てる規則は見つかったか',
                a='反証の後も残った勝ちは、米国外の国の中の割安＋勢いなど、個人が持ちにくいものだけだった。今の持ち方（時価加重の NASDAQ100＋SMH を円で積む）を変える根拠はどの角度からも出なかった。',
                src='out/mw_summary.json', date=d['generated'],
                chart=dict(type='tiles', tiles=[dict(k='試した規則', v=f"{d['program_tests_total']:,}本"),
                                                dict(k='角度', v=f'{len(A)}'),
                                                dict(k='全体の線（Bonferroni の t）', v=str(d['bonferroni_t_program_wide'])),
                                                dict(k='別の検証役が作り直した角度', v=f'{ver}'),
                                                dict(k='反証の後に S/A で残った規則', v=f'{surv}本')]),
                table=dict(head=['角度（試した本数の多い順）', '本数', 'S', 'A', '反証の後に残った'],
                           rows=[[x['angle'], x['n_tested'], x['research_grades'].get('S', 0), x['research_grades'].get('A', 0),
                                  len(x.get('survivors_SA_after_verify') or [])] for x in top]))


def main():
    out = dict(generated=datetime.date.today().isoformat(), tool='night/ami_digest.py',
               note='これまでの歴史検証の出力から抜き出した要約。新しい計算はしない・判定に不使用', cards=[])
    bad = 0
    for fn in CARDS:
        try:
            out['cards'].append(fn())
        except Exception as e:
            bad += 1
            out['cards'].append(dict(id=fn.__name__, title=fn.__name__, err=f'{type(e).__name__}: {e}'[:200]))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f'✓ {OUT}  カード {len(out["cards"])}（読めなかった {bad}）')
    for c in out['cards']:
        print('  ', c['id'], '✗ ' + c['err'] if 'err' in c else '✓')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
