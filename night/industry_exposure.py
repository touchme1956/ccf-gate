#!/usr/bin/env python3
"""night/industry_exposure.py — 自分のお金を業種（French 49業種）へ分解する（読むだけ・判定に不使用）

ユーザー（2026-09-28）「これかなり重要なデータでは？」→「やって」の2つ目。
2025年末、米国株の時価総額に占める比重は ソフトウェア 19.9%・半導体・電子部品 19.3% で、どちらも100年で最大。
自分のお金のうち、その二つの業種にどれだけ乗っているかを出す。方法は out/industry_peak_prereg.json の lookthrough_method。

  今の保有 … state.json の pf:portfolio（個別）と portfolio.json（ETF）を night/lookthrough.py でそのまま読む
  目標の姿 … portfolio.json の target（個別＝席〔out/score_all.json の buy〕＋按分に入る門外例外を等分／ETF＝ami_weights）
             iFreeNEXT NASDAQ100（IFREE-NDX）は同じ指数の QQQ の中身で代える
  業種    … SEC EDGAR の SIC → French の Siccodes49（100年のデータと同じ物差し）

⚠ EDGAR の SIC と French（Compustat）の SIC は一部の会社で違う。Apple は EDGAR では 3571＝コンピュータ機器だが、
  French の分類では半導体・電子部品（3663）の側にいると見られる（French のコンピュータ機器は2025年に1.1%しかなく、
  Apple がそこに居れば6%を超える）。だから両方の数え方を出す。
⚠ 業種が決まらない分・中身の取れない ETF の分は『未分類』として別に数え、ゼロで薄めない（ルール7）。
出力: out/industry_exposure.json
"""
import json, os, sys, time, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from lookthrough import castle, net, explode, jload, SEMI
from industry_trends import ff49_map, get, JA

OUT = os.path.join(BASE, 'out', 'industry_exposure.json')
SICF = os.path.join(BASE, 'out', 'sic_by_cik.json')
SAME_INDEX = {'IFREE-NDX': 'QQQ'}      # 投資信託は中身の配信が無いので、同じ指数の ETF の中身で代える
FRENCH_LIKE = {'AAPL': ('Chips', 'French（Compustat）は 3663＝半導体・電子部品の側と見られる。EDGAR は 3571＝コンピュータ機器')}


def sic_lookup(tickers):
    sc = jload(os.path.join(BASE, 'out', '_sic_cache.json'), {})
    ct = jload(os.path.join(BASE, 'out', '_cik_tickers.json'), {})
    sb = jload(SICF, {})
    out, added = {}, 0
    for t in sorted(tickers):
        if sc.get(t, {}).get('sic'):
            out[t] = (int(sc[t]['sic']), sc[t].get('desc') or '')
            continue
        c = ct.get(t) or ct.get(t.replace('.', '-'))
        if c and str(int(c)) in sb:
            out[t] = (int(sb[str(int(c))]), '')
            continue
        if not c:
            out[t] = (None, 'CIK が見つからない')
            continue
        try:
            j = json.loads(get(f'https://data.sec.gov/submissions/CIK{int(c):010d}.json'))
            s = j.get('sic')
            out[t] = (int(s) if s else None, f"{j.get('name', '')} {j.get('sicDescription', '')}".strip())
            if s:
                sb[str(int(c))] = str(s)
                added += 1
            time.sleep(0.15)
        except Exception as e:
            out[t] = (None, f'取得失敗 {e}')
    if added:
        json.dump(sb, open(SICF, 'w'), ensure_ascii=False, sort_keys=True)
    return out


def target_mix(prof, same=None):
    """目標の姿を {ticker: 総資産に対する割合} で。ETF は中身へ分解する前の本のまま返す"""
    same = same or SAME_INDEX
    pf = jload(os.path.join(BASE, 'portfolio.json'), {})
    tg = pf.get('target') or {}
    castle_pct = tg.get('shiro_castle_pct') or 0
    seats = [r['t'] for r in jload(os.path.join(BASE, 'out', 'score_all.json'), []) if r.get('buy')]
    ex = [x.get('t') for x in (jload(os.path.join(BASE, 'gate_exceptions.json'), {}) or {}).get('items', [])
          if x.get('in_castle_split')]
    names = seats + [t for t in ex if t not in seats]
    if tg.get('castle_weighting') != 'equal':
        raise SystemExit(f"castle_weighting={tg.get('castle_weighting')!r}: 等分以外の按分はこの道具では組んでいない")
    mix = {t: castle_pct / 100 / len(names) for t in names} if names else {}
    etf = {}
    for t, w in (tg.get('ami_weights') or {}).items():
        if w:
            etf[same.get(t, t)] = etf.get(same.get(t, t), 0) + w / 100
    return mix, etf, names


def breakdown(direct, etf_yen, prof, sic, f49, label):
    """direct: {ticker: 円}（個別）／ etf_yen: {ETF: 円}。業種ごとの円と、未分類を返す"""
    look, unknown = explode(etf_yen, prof)
    merged = dict(direct)
    for t, v in look.items():
        merged[t] = merged.get(t, 0) + v
    total = sum(direct.values()) + sum(etf_yen.values())
    ind = {'EDGAR': {}, 'French寄せ': {}}
    uncls = {}
    for t, v in merged.items():
        s = sic.get(t, (None, ''))[0]
        if s is None:
            uncls[t] = uncls.get(t, 0) + v
            continue
        k = f49(s)
        ind['EDGAR'][k] = ind['EDGAR'].get(k, 0) + v
        k2 = FRENCH_LIKE.get(t, (k,))[0]
        ind['French寄せ'][k2] = ind['French寄せ'].get(k2, 0) + v
    unk = sum(unknown.values()) + sum(uncls.values())

    def pct(x):
        return round(x / total * 100, 1) if total else None
    rec = ('Softw', 'Chips')
    # 金額（円）は書かない——割合だけで足り、保有の金額をこれ以上のファイルへ広げない
    res = {'label': label, '未分類(%)': pct(unk),
           '未分類の中身(%)': {**{f'{k}（中身の取れない分・現金を含む）': round(v / total * 100, 2) for k, v in unknown.items()},
                          **{k: round(v / total * 100, 2) for k, v in uncls.items()}}}
    for conv, d in ind.items():
        rows = sorted(d.items(), key=lambda kv: -kv[1])
        res[f'業種({conv})'] = [{'業種': k, 'ja': JA.get(k, k), '%': pct(v)} for k, v in rows]
        r = sum(d.get(k, 0) for k in rec)
        res[f'記録の二業種(ソフトウェア＋半導体・電子部品)_{conv}'] = {
            '%': pct(r), '下限(%)': pct(r), '上限(未分類を全部含めた・%)': pct(r + unk),
            'ソフトウェア(%)': pct(d.get('Softw', 0)), '半導体・電子部品(%)': pct(d.get('Chips', 0))}
    tech = sum(ind['EDGAR'].get(k, 0) for k in ('Softw', 'Chips', 'Hardw'))
    res['テック三業種(ソフトウェア＋半導体・電子部品＋コンピュータ機器)(%)'] = pct(tech)
    res['半導体の連鎖(装置・材料を含む・lookthrough の SEMI)(%)'] = pct(sum(v for t, v in merged.items() if t in SEMI))
    top = {}
    for k in rec:
        xs = sorted(((t, v) for t, v in merged.items()
                     if sic.get(t, (None,))[0] is not None and FRENCH_LIKE.get(t, (f49(sic[t][0]),))[0] == k),
                    key=lambda kv: -kv[1])
        top[JA.get(k, k)] = [{'t': t, '%': pct(v), '直接(%)': pct(direct.get(t, 0))} for t, v in xs[:8]]
    res['記録の二業種の上位(French寄せ)'] = top
    others = sorted(((t, v) for t, v in merged.items() if sic.get(t, (None,))[0] is not None
                     and FRENCH_LIKE.get(t, (f49(sic[t][0]),))[0] not in rec), key=lambda kv: -kv[1])
    res['それ以外の上位'] = [{'t': t, '業種': JA.get(f49(sic[t][0]), f49(sic[t][0])), '%': pct(v)} for t, v in others[:10]]
    return res


def main():
    prof = jload(os.path.join(BASE, 'out', 'etf_profiles.json'), {})
    etfs = prof.get('etfs') or {}
    c_now, c_asof, c_err = castle()
    n_now, n_asof = net()
    t_castle, t_etf, names = target_mix(prof)
    tick = set(c_now) | set(t_castle)
    for e in set(n_now) | set(t_etf):
        tick |= {t.upper() for t, _ in (etfs.get(e) or {}).get('h') or []}
    sic = sic_lookup(tick)
    f49 = ff49_map()

    now = breakdown(c_now, n_now, prof, sic, f49, f'今の保有（個別 {c_asof}・ETF {n_asof}）')
    T = 1_000_000
    tgt = breakdown({t: w * T for t, w in t_castle.items()}, {e: w * T for e, w in t_etf.items()}, prof, sic, f49,
                    '目標の姿（個別20%＝' + '・'.join(names) + ' を等分／ETF80%＝iFreeNEXT NASDAQ100 60〔QQQ の中身〕・SMH 20）')
    # 事前登録は iFreeNEXT を QQQ の中身で代えると決めた。QQQM（同じ指数・中身の日付が1か月新しい）で代えた場合も並べる
    q_castle, q_etf, _ = target_mix(prof, {'IFREE-NDX': 'QQQM'})
    tq = breakdown({t: w * T for t, w in q_castle.items()}, {e: w * T for e, w in q_etf.items()}, prof, sic, f49, 'QQQM')
    tgt['確認_iFreeNEXTをQQQMの中身で代えた場合(French寄せ・%)'] = tq['記録の二業種(ソフトウェア＋半導体・電子部品)_French寄せ']['%']
    peak = jload(os.path.join(BASE, 'out', 'industry_peak.json'), {})
    mkt = {r['業種']: r['比重'] for r in peak.get('今_記録を付けている業種') or []}
    etf_alone = {}
    for e in ('QQQ', 'QQQM', 'SMH', 'XLK'):
        b = breakdown({}, {e: T}, prof, sic, f49, e)
        etf_alone[e] = {k: b[f'記録の二業種(ソフトウェア＋半導体・電子部品)_{k}']['%'] for k in ('EDGAR', 'French寄せ')}
        etf_alone[e]['中身の日付'] = (etfs.get(e) or {}).get('asof')
    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/industry_exposure.py',
           'method': 'out/industry_peak_prereg.json の lookthrough_method',
           '米国市場全体(French・2025年末)': {'ソフトウェア(%)': round(mkt.get('Softw', 0) * 100, 1),
                                         '半導体・電子部品(%)': round(mkt.get('Chips', 0) * 100, 1),
                                         '二つの合計(%)': round((mkt.get('Softw', 0) + mkt.get('Chips', 0)) * 100, 1)},
           'ETF単体の記録の二業種(%)': etf_alone,
           '今の保有': now, '目標の姿': tgt,
           'SICが取れなかった銘柄': {t: v[1] for t, v in sic.items() if v[0] is None},
           '⚠': ['ETF の中身は out/etf_profiles.json の日付の写真（数週間古い）',
                 'Apple の置き場所で ソフトウェア＋半導体・電子部品 の割合が数ポイント動く。French寄せ が French の100年のデータと同じ数え方に近い',
                 'ASML・LRCX（SIC 3559）は French では『機械』、KLAC（3827）は『計測・分析機器』に入る。半導体の設備投資の循環に乗る点は同じなので、半導体の連鎖も併記した',
                 'ASML・TSM は米国の普通株ではない（ADR）ので French の比重の母集団には入らない。業種の分類だけ同じ物差しで当てた',
                 '判定・配分には使わない（表示だけ）']}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print('市場', doc['米国市場全体(French・2025年末)'])
    print('ETF単体', etf_alone)
    for key in ('今の保有', '目標の姿'):
        b = doc[key]
        print('\n==', b['label'], '未分類', b['未分類(%)'], '%')
        for conv in ('EDGAR', 'French寄せ'):
            print(conv, b[f'記録の二業種(ソフトウェア＋半導体・電子部品)_{conv}'])
        print('テック三業種', b['テック三業種(ソフトウェア＋半導体・電子部品＋コンピュータ機器)(%)'], '半導体の連鎖', b['半導体の連鎖(装置・材料を含む・lookthrough の SEMI)(%)'])
        print('業種(French寄せ)', [(r['ja'], r['%']) for r in b['業種(French寄せ)'][:10]])
        print('上位', b['記録の二業種の上位(French寄せ)'])
        print('それ以外', b['それ以外の上位'][:8])
        print('未分類の中身', b['未分類の中身(%)'])
    print('確認 QQQM で代えた目標', tgt['確認_iFreeNEXTをQQQMの中身で代えた場合(French寄せ・%)'])
    print('SICなし', doc['SICが取れなかった銘柄'])


if __name__ == '__main__':
    main()
