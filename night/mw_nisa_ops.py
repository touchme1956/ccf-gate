#!/usr/bin/env python3
"""night/mw_nisa_ops.py — 『市場に勝てる歴史検証』の角度 nisa_ops（読むだけ・門の判定には不使用）

問い: 資産と積立（月17万円・80% 指数ファンド／20% 個別株〔城〕・NISA は夫婦2人分）を固定したまま、
      NISA と課税口座の『運用の決まり』は、既定の運用（NISA から先に買う・売らない・減らすときは口座の時価で按分・
      枠の回収なし）より、税引後・実質の最終資産で勝つか。
        O1  12月に、NISA の中で取得額（簿価）を1%以上下回っている口を売り、課税口座で1か月つなぎ、
            1月に復活した簿価の枠で NISA へ買い戻す（年の枠の範囲で）
        O2a 1月に、課税口座の含み損の区画を、空いている NISA の枠へ移す（損の大きい順）
        O2b 1月に、課税口座の区画を空いている NISA の枠へ移す（損の区画が先・次に益の小さい順）
        O3  売る袖（城＝回転 年0.25）は課税口座だけに置き、売らない指数だけを NISA に置く
        O4  課税口座に溢れた指数を、積み上げ型の投信ではなく分配型の米国 ETF で持つ
        O5  O1＋O2b＋O3（O2 は指数の区画だけ）
事前登録: out/mw_nisa_ops_prereg.json（測る前にコミット）。全体の線は out/mw_prereg.json（mw_common.grade）。
出力: out/mw_nisa_ops.json

使い方:
  python3 night/mw_nisa_ops.py --selftest   # 合成データで道具だけを確かめる（規則と既定は比べない）
  python3 night/mw_nisa_ops.py --dry        # データの範囲・窓の数だけ（規則と既定は比べない）
  python3 night/mw_nisa_ops.py              # 全部測って out/mw_nisa_ops.json へ
"""
import sys, os, io, json, math, csv, zipfile, re, random, subprocess, time, statistics as S, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

ANGLE = 'nisa_ops'
PREREG = 'mw_nisa_ops_prereg.json'
OUT = 'mw_nisa_ops.json'
FR_END = 202608

# ── 税と NISA（2024年からの新NISA・法定。事前登録の写し。変えるなら事前登録から）
TAX = 0.20315
TAX_STRESS = 0.25
WH_US = 0.10                          # 米国の配当源泉（NISA では戻らない。課税口座は外国税額控除）
Q_TSUMI, Q_GROWTH = 1_200_000, 2_400_000      # 1人あたり・年
LIFE, LIFE_G = 18_000_000, 12_000_000         # 1人あたり・簿価（成長投資枠は 1200万まで）
HOLDERS = 2                           # 夫婦2人分の NISA
CONTRIB = 170_000                     # 月の積立（円）
CONTRIB_HI = 300_000
CASTLE_SHARE = 0.20                   # 個別株（城）の袖（portfolio.json の target: 個別20 / ETF80）
TURN = 0.25                           # 城の片道の回転（年・mw_castle_mech turnover_oneway_ann）
FEE_FUND = 0.0010                     # 積み上げ型の指数投信（年）
FEE_ETF = 0.0003                      # 分配型の米国 ETF（年）
SWITCH = 0.001                        # 乗り換え・回転1回（売り＋買い）あたり 0.1%・売る時に引く（brief）
FX_YEN = 0.25                         # 楽天の定時為替の手数料 25銭/ドル（片道・2026-09-28 に楽天の手数料ページで確認）
RK_COMM = 0.00495                     # 楽天 米国株・ETF の取引手数料（課税口座・片道・上限22ドルは無視）。NISA は無料（同日確認）
O1_L, O1_L10 = 0.01, 0.10             # O1 の発動線（簿価をこれ以上下回ったら売る）
NAME_N, NAME_EVERY = 5, 10            # 名前の城: 5銘柄・10か月ごとに一番古い1銘柄を入れ替え（≒ 年0.24）
SEEDS = (11, 22, 33)
HORIZONS = (20, 25, 30)
EPS = 1e-9
COMM_DEDUCT = True                    # 課税口座の売りの手数料を譲渡益から引く（日本の扱い）。mw_jp_aftertax との突き合わせの時だけ False

LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=M.BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── 規則・場面 ─────────────────────────
RULES = {
    'D0': dict(),
    'O1': dict(o1=O1_L),
    'O1_L10': dict(o1=O1_L10),
    'O2a': dict(o2='loss'),
    'O2b': dict(o2='all'),
    'O3': dict(o3=True),
    'O4': dict(o4=True),
    'O5': dict(o1=O1_L, o2='all', o3=True),
}
PRIMARY_RULES = ['O1', 'O2a', 'O2b', 'O3', 'O4', 'O5']
SECONDARY_RULES = ['O1_L10']


class Cfg:
    def __init__(self, name, holders=HOLDERS, contrib=CONTRIB, tax=TAX, init_taxable=False, costs='brief', castle='clone',
                 castle_share=CASTLE_SHARE, turn=TURN, seed=None):
        self.name, self.holders, self.contrib, self.tax = name, holders, contrib, tax
        self.init_taxable, self.costs, self.castle, self.castle_share, self.turn, self.seed = init_taxable, costs, castle, castle_share, turn, seed


SCEN = {
    'P': Cfg('P'),                                           # 主: 2人・月17万・税20.315%・課税口座の持ち越しなし・brief の費用・城は市場の写し
    'S1_one_holder': Cfg('S1_one_holder', holders=1),
    'S2_300k': Cfg('S2_300k', contrib=CONTRIB_HI),
    'S3_tax25': Cfg('S3_tax25', tax=TAX_STRESS),
    'S4_init_taxable': Cfg('S4_init_taxable', init_taxable=True),
    'S7_rakuten': Cfg('S7_rakuten', costs='rakuten'),
}


# ───────────────────────── 家計の模型 ─────────────────────────
class HH:
    """一つの家計（NISA つみたて NT・成長 NG〔夫婦の枠を合算〕・課税 T〔特定口座・1人に集める〕）。
    1歩（月 or 年）の順: [O1 年換わりの売り（年次のみ）] → 年替わり（精算・年の枠を戻す・売った簿価を生涯枠へ戻す）→
    O1 の買い戻し（1月）→ O2 の移し替え（1月）→ 城の回転の売り → 税の不足を売って埋める → 積立・配当・売却代金の買い（NISA が先・按分）→
    O1 の売り（12月・月次のみ・つなぎは課税口座）→ 当月のリターン・配当。"""

    def __init__(self, P, cfg, rule, sched=None):
        self.P, self.cfg, self.rule = P, cfg, rule
        self.f = P['freq']
        self.tax = cfg.tax
        self.wh = P['wh']
        self.pos = {}                        # (口座, 資産) -> [時価, 取得額]
        self.cash_i = 0.0                    # 指数の袖の円
        self.cash_cj = 0.0; self.cash_cu = 0.0   # 城の袖の円・ドル（ドルは為替手数料なしで買える）
        self.ytd = self.ydiv = self.withheld = 0.0
        self.carry = []
        self.qu = {'NT': 0.0, 'NG': 0.0}
        self.life = self.life_g = self.pend = self.pend_g = 0.0
        self.year = None
        self.bridge = {}                     # O1 のつなぎ: 資産 -> 課税口座の区画のうちつなぎの割合
        self.o1cash = {}                     # 年次の O1: 資産 -> 売った代金（年の境目で買い戻す）
        self.sched = sched                   # 名前の城: 入れ替えの計画
        self.names = []                      # いま持つ城の名前（[名前, 持ち始めの歩]）
        self.k = 1.0                         # 実質化の係数（その歩の）
        self.step_i = 0
        self.pre = False
        self.stats = collections.Counter()

    # ── 資産の性質
    def base(self, a):
        return 'MKT' if a in ('IDX', 'IDXE', 'CL') else a

    def is_fund(self, a):
        return a == 'IDX'

    def is_usd(self, a):
        return self.P['usd'] and a != 'IDX'

    def is_castle(self, a):
        return a not in ('IDX', 'IDXE')

    def frames(self, a):
        return ('NT', 'NG') if a == 'IDX' else ('NG',)

    def fee(self, a):
        return FEE_FUND if a == 'IDX' else (FEE_ETF if a == 'IDXE' else 0.0)

    def fxs(self, m):
        """円→ドル・ドル→円の片道の為替手数料（割合）"""
        if not self.P['usd']:
            return 0.0
        return FX_YEN / self.P['fx'][m]

    # ── 費用
    def comm(self, acct, a, x, kind):
        """売買の費用。brief: 回転・乗り換え（kind in turn/switch）の売りに 0.1%。rakuten: 課税口座の米国上場（城・ETF）に 片道0.495%"""
        if self.cfg.costs == 'brief':
            return SWITCH * x if kind in ('turn', 'switch') else 0.0
        if acct == 'T' and self.is_usd(a):
            return RK_COMM * x
        return 0.0

    # ── 口座の出し入れ
    def _add(self, acct, a, v, b):
        p = self.pos.get((acct, a))
        if p is None:
            self.pos[(acct, a)] = [v, b]
        else:
            p[0] += v; p[1] += b

    def put(self, acct, a, x, m, kind='regular', from_usd=False):
        """x 円（簿価）ぶん a を acct に買う。円からドル資産を買うなら為替手数料。課税口座の手数料は取得額に含める"""
        if x <= EPS:
            return
        v = x
        if self.is_usd(a) and not from_usd:
            c = x * self.fxs(m)
            v -= c; self.stats['fx_cost'] += c
        c2 = self.comm(acct, a, x, kind) if self.cfg.costs == 'rakuten' else 0.0
        v -= c2; self.stats['comm_cost'] += c2
        self._add(acct, a, v, x)
        if acct in ('NT', 'NG'):
            self.qu[acct] += x
            self.life += x
            if acct == 'NG':
                self.life_g += x

    def sell(self, acct, a, x, m, kind='regular'):
        """x（時価）を売る。課税口座は損益が実現、NISA は売った簿価を翌年に戻す。戻り値: 手取り（費用後）"""
        p = self.pos.get((acct, a))
        if not p or p[0] <= EPS or x <= EPS:
            return 0.0
        x = min(x, p[0])
        fr = x / p[0]
        b = p[1] * fr
        c = self.comm(acct, a, x, kind)
        self.stats['comm_cost'] += c
        if acct == 'T':
            self.realize(x - (c if COMM_DEDUCT else 0.0) - b)
        else:
            self.pend += b
            if acct == 'NG':
                self.pend_g += b
        p[0] -= x; p[1] -= b
        if p[0] <= 1e-7:
            del self.pos[(acct, a)]
        return x - c

    def realize(self, g):
        if self.tax <= 0 or abs(g) < 1e-12:
            return
        self.ytd += g
        self.withhold()

    def withhold(self):
        tgt = self.tax * max(0.0, self.ytd)
        self.cash_tax(-(tgt - self.withheld))
        self.withheld = tgt

    def cash_tax(self, x):
        """税の出入り（円）。正（還付）は袖へ 80/20、負は後で売って埋める"""
        if x >= 0:
            s = self.cfg.castle_share
            self.cash_i += x * (1 - s); self.cash_cj += x * s
        else:
            self.cash_i += x                 # いったん指数の袖の円を負にし、cover で埋める

    def settle(self, year):
        if self.tax <= 0:
            return
        self.carry = [c for c in self.carry if year - c[0] <= 3]
        inc = self.ytd
        fin = 0.0
        if inc > 0:
            rem = inc
            for c in self.carry:
                u = min(c[1], rem)
                c[1] -= u; rem -= u
            fin = self.tax * rem
            cred = min(self.wh * self.ydiv, fin) if self.ydiv > 0 else 0.0
            fin -= cred
        elif inc < 0:
            self.carry.append([year, -inc])
        self.cash_tax(self.withheld - fin)
        self.stats['tax_paid'] += fin
        self.stats['carry_expired'] += sum(c[1] for c in self.carry if year - c[0] >= 3)
        self.carry = [c for c in self.carry if c[1] > 1e-9 and year - c[0] < 3]
        self.ytd = self.ydiv = self.withheld = 0.0

    def new_year(self, y):
        if self.year is not None and y != self.year:
            self.settle(self.year)
            self.qu = {'NT': 0.0, 'NG': 0.0}
            self.life -= self.pend; self.life_g -= self.pend_g
            self.pend = self.pend_g = 0.0
        self.year = y

    # ── 枠
    def room(self, a, acct):
        h, k = self.cfg.holders, self.k
        cap_y = (Q_TSUMI if acct == 'NT' else Q_GROWTH) * h * k - self.qu[acct]
        cap_l = LIFE * h * k - self.life
        if acct == 'NG':
            cap_l = min(cap_l, LIFE_G * h * k - self.life_g)
        return max(0.0, min(cap_y, cap_l))

    def room_total(self, a):
        """a を NISA に入れられる額（枠を順に使ったとき）"""
        tot, life = 0.0, LIFE * self.cfg.holders * self.k - self.life
        for fr in self.frames(a):
            r = min(self.room(a, fr), max(0.0, life - tot))
            tot += r
        return tot

    def nisa_put(self, a, x, m, from_usd=False, kind='regular'):
        """x を a の NISA 枠（順に）へ。入った額を返す"""
        done = 0.0
        for fr in self.frames(a):
            y = min(x - done, self.room(a, fr))
            if y > EPS:
                self.put(fr, a, y, m, kind, from_usd)
                done += y
            if x - done <= EPS:
                break
        return done

    # ── 集計
    def value(self):
        return sum(v[0] for v in self.pos.values())

    def cash_all(self):
        return self.cash_i + self.cash_cj + self.cash_cu

    def acct_of(self, a):
        return [k for k in self.pos if k[1] == a]

    def castle_assets(self):
        return sorted({a for (_, a) in self.pos if self.is_castle(a)} | {n for n, _ in self.names})

    # ── 規則
    def o1_candidates(self):
        L = self.rule.get('o1')
        out = []
        for (ac, a), (v, b) in list(self.pos.items()):
            if ac in ('NT', 'NG') and b > 0 and v <= (1 - L) * b:
                out.append((ac, a))
        return out

    def o1_sell_month(self, m):
        """12月の月初（11月末の値で判断）: 簿価を L 以上下回る NISA の口を売り、同じ資産を課税口座でつなぐ"""
        for ac, a in self.o1_candidates():
            v, b = self.pos[(ac, a)]
            got = self.sell(ac, a, v, m, kind='switch')
            self.stats['o1_sales'] += 1
            self.stats['o1_room_gain'] += b - v
            self.put('T', a, got, m, kind='switch', from_usd=True)
            p = self.pos[('T', a)]
            self.bridge[a] = self.bridge.get(a, 0.0) + got
        # つなぎの割合（この月の売買が終わった後の区画に対して）は step の最後で決める

    def o1_fix_bridge(self):
        for a in list(self.bridge):
            p = self.pos.get(('T', a))
            if not p:
                del self.bridge[a]; continue
            self.bridge[a] = min(1.0, self.bridge[a] / p[0]) if p[0] > EPS else 0.0

    def o1_rebuy_month(self, m):
        """1月の月初: つなぎを売り、復活した枠で NISA へ買い戻す（入りきらない分は課税口座に残す）"""
        for a, frac in list(self.bridge.items()):
            p = self.pos.get(('T', a))
            if p and frac > 0:
                want = frac * p[0]
                rm = self.room_total(a)
                x = min(want, rm)
                if x > EPS:
                    got = self.sell('T', a, x, m, kind='switch')
                    self.nisa_put(a, got, m, from_usd=True, kind='switch')
                    self.stats['o1_rebought'] += got
                self.stats['o1_left_taxable'] += max(0.0, want - x)
            del self.bridge[a]

    def o1_sell_annual(self, m):
        """年次: 年末の値で判断して売り、年の境目で買い戻す（つなぎの時間は0）"""
        for ac, a in self.o1_candidates():
            v, b = self.pos[(ac, a)]
            got = self.sell(ac, a, v, m, kind='switch')
            self.stats['o1_sales'] += 1
            self.stats['o1_room_gain'] += b - v
            self.o1cash[a] = self.o1cash.get(a, 0.0) + got

    def o1_rebuy_annual(self, m):
        for a, x in list(self.o1cash.items()):
            got = self.nisa_put(a, x, m, from_usd=True, kind='switch')
            self.stats['o1_rebought'] += got
            if x - got > EPS:
                self.put('T', a, x - got, m, kind='switch', from_usd=True)
                self.stats['o1_left_taxable'] += x - got
            del self.o1cash[a]

    def o2_migrate(self, m):
        """1月の月初: 課税口座の区画を空いた枠へ移す。loss＝含み損だけ（損の大きい順）、all＝損が先・次に益の小さい順"""
        mode = self.rule.get('o2')
        cands = []
        for (ac, a), (v, b) in self.pos.items():
            if ac != 'T' or v <= EPS:
                continue
            if self.rule.get('o3') and self.is_castle(a):
                continue                     # O5: 城は課税口座に置く（O3）ので移さない
            if a == 'IDXE':
                continue                     # 分配型 ETF（O4）の区画は対象外（組み合わせない）
            gfrac = v / b - 1 if b > 0 else 0.0
            if mode == 'loss' and gfrac >= 0:
                continue
            cands.append((gfrac, a))
        for gfrac, a in sorted(cands):
            p = self.pos.get(('T', a))
            if not p:
                continue
            rm = self.room_total(a)
            x = min(p[0], rm)
            if x <= EPS:
                continue
            got = self.sell('T', a, x, m, kind='switch')
            self.nisa_put(a, got, m, from_usd=True, kind='switch')
            self.stats['o2_moved'] += got
            self.stats['o2_moves'] += 1

    # ── 城
    def castle_turn(self, m):
        """市場の写しの城: 毎歩 TURN/f を全口座から時価で按分して売り、同じ資産を買い直す（代金は城のドル）"""
        q = self.cfg.turn / self.f
        for key in [k for k in self.pos if k[1] == 'CL']:
            got = self.sell(key[0], 'CL', self.pos[key][0] * q, m, kind='turn')
            self.cash_cu += got

    def names_step(self, m):
        """名前の城: 計画どおりに入れ替え（古い名前を全口座で売る）・データの無い名前は前月末の値で売る（0で埋めない）"""
        R = self.P['R']
        drop = set()
        want = self.sched(self, m) if self.sched else None
        if want is not None:
            cur = [n for n, _ in self.names]
            for n in cur:
                if n not in want:
                    drop.add(n)
            for n in want:
                if n not in cur:
                    self.names.append([n, self.step_i])
        for n, _ in self.names:
            if m not in R.get(n, {}):
                drop.add(n)
                self.stats['names_forced_exit'] += 1
        for n in drop:
            for key in [k for k in self.pos if k[1] == n]:
                got = self.sell(key[0], n, self.pos[key][0], m, kind='turn')
                self.cash_cu += got
            self.names = [x for x in self.names if x[0] != n]
            self.stats['names_replaced'] += 1

    # ── 税の不足
    def cover(self, m):
        for _ in range(6):
            if self.cash_i >= -1e-9:
                return
            need = -self.cash_i
            # まず城のドル・円の現金で
            for attr in ('cash_cu', 'cash_cj'):
                c = getattr(self, attr)
                u = min(c, need)
                if u > 0:
                    setattr(self, attr, c - u); self.cash_i += u; need -= u
            if need <= 1e-9:
                return
            for grp in (('T',), ('NT', 'NG')):
                tv = sum(v[0] for (ac, a), v in self.pos.items() if ac in grp)
                if tv <= 0:
                    continue
                f = min(1.0, need / tv)
                for key in [k for k in self.pos if k[0] in grp]:
                    got = self.sell(key[0], key[1], self.pos[key][0] * f, m)
                    if self.is_usd(key[1]):
                        c = got * self.fxs(m); got -= c; self.stats['fx_cost'] += c
                    self.cash_i += got
                break

    # ── 買い（NISA が先・按分）
    def castle_targets(self):
        """城の資産ごとの買いの配分（等しい重みへの不足の按分）"""
        if self.cfg.castle == 'clone':
            return {'CL': 1.0}
        ns = [n for n, _ in self.names]
        if not ns:
            return {}
        cur = {n: sum(v[0] for (ac, a), v in self.pos.items() if a == n) for n in ns}
        tot = sum(cur.values()) + self.cash_cj + self.cash_cu
        need = {n: max(0.0, tot / len(ns) - cur[n]) for n in ns}
        s = sum(need.values())
        if s <= EPS:
            return {n: 1 / len(ns) for n in ns}
        return {n: need[n] / s for n in ns}

    def buy_all(self, m):
        xi = max(0.0, self.cash_i)
        xc = max(0.0, self.cash_cj) + max(0.0, self.cash_cu)
        usd_share = (max(0.0, self.cash_cu) / xc) if xc > 0 else 0.0
        self.cash_i -= xi; self.cash_cj -= max(0.0, self.cash_cj); self.cash_cu -= max(0.0, self.cash_cu)
        if self.pre:
            # S4 の持ち越し: 窓の前の12か月は課税口座だけで買う
            self.put('T', 'IDX', xi, m)
            for a, w in self.castle_targets().items():
                self._put_mixed('T', a, xc * w, m, usd_share)
            return
        dem = {}
        if xi > EPS:
            dem['IDX'] = xi
        tg = self.castle_targets() if xc > EPS else {}
        for a, w in tg.items():
            dem[a] = dem.get(a, 0.0) + xc * w
        # つみたて枠（指数だけ）
        if 'IDX' in dem:
            y = min(dem['IDX'], self.room('IDX', 'NT'))
            if y > EPS:
                self.put('NT', 'IDX', y, m)
                dem['IDX'] -= y
        # 成長投資枠（指数の残り・城〔O3 では城は入れない〕）を按分
        elig = {a: x for a, x in dem.items() if x > EPS and not (self.rule.get('o3') and self.is_castle(a))}
        tot = sum(elig.values())
        if tot > EPS:
            cap = self.room('IDX', 'NG')
            f = min(1.0, cap / tot)
            for a, x in elig.items():
                y = x * f
                if y > EPS:
                    if a == 'IDX':
                        self.put('NG', a, y, m)
                    else:
                        self._put_mixed('NG', a, y, m, usd_share)
                    dem[a] -= y
        # 残りは課税口座（O4: 指数は分配型 ETF）
        for a, x in dem.items():
            if x <= EPS:
                continue
            if a == 'IDX':
                self.put('T', 'IDXE' if self.rule.get('o4') else 'IDX', x, m)
            else:
                self._put_mixed('T', a, x, m, usd_share)

    def _put_mixed(self, acct, a, x, m, usd_share):
        """城の買い: ドルの現金の分は為替手数料なし"""
        if x <= EPS:
            return
        xu = x * usd_share
        if xu > EPS:
            self.put(acct, a, xu, m, from_usd=True)
        if x - xu > EPS:
            self.put(acct, a, x - xu, m)

    # ── 当月のリターン
    def apply(self, m):
        R, DY = self.P['R'], self.P['DY']
        f = self.f
        for key, p in list(self.pos.items()):
            ac, a = key
            b = self.base(a)
            r = R[b][m]
            dy = DY[b][m]
            if self.is_fund(a):
                p[0] *= 1 + r - self.wh * dy - self.fee(a) / f
            else:
                v0 = p[0]
                p[0] *= 1 + (r - dy) - self.fee(a) / f
                d = v0 * dy
                net = d * (1 - self.wh)
                if a == 'IDXE':
                    # 分配型 ETF の分配はドルのまま同じ ETF を課税口座で買い直す（事前登録）
                    self._pending_etf = getattr(self, '_pending_etf', 0.0) + net
                elif self.is_usd(a):
                    self.cash_cu += net
                else:
                    self.cash_cj += net
                if ac == 'T' and self.tax > 0:
                    self.ydiv += d
                    self.ytd += d
                    self.withhold()

    def reinvest_etf(self, m):
        x = getattr(self, '_pending_etf', 0.0)
        if x > EPS:
            self.put('T', 'IDXE', x, m, from_usd=True)
        self._pending_etf = 0.0

    # ── 1歩
    def step(self, m, contrib):
        f = self.f
        y = m // 100 if f == 12 else m
        mo = m % 100 if f == 12 else None
        annual = f == 1
        if annual and self.rule.get('o1') and not self.pre and self.year is not None:
            self.o1_sell_annual(m)
        self.new_year(y)
        if contrib > 0:
            s = self.cfg.castle_share
            self.cash_i += contrib * (1 - s); self.cash_cj += contrib * s
        if not self.pre:
            if self.rule.get('o1'):
                if annual:
                    self.o1_rebuy_annual(m)
                elif mo == 1:
                    self.o1_rebuy_month(m)
            if self.rule.get('o2') and (annual or mo == 1):
                self.o2_migrate(m)
        if self.cfg.castle == 'clone':
            self.castle_turn(m)
        else:
            self.names_step(m)
        self.reinvest_etf(m)
        self.cover(m)
        self.buy_all(m)
        if not annual and not self.pre and self.rule.get('o1') and mo == 12:
            self.o1_sell_month(m)
            self.o1_fix_bridge()
        self.apply(m)
        self.step_i += 1

    def liquidation_value(self, m):
        """いま全部売って円にしたら手元に残る額（税・為替・手数料の後）"""
        tv = self.value() + self.cash_all() + getattr(self, '_pending_etf', 0.0)
        s = self.fxs(m)
        fxc = sum(v[0] for (ac, a), v in self.pos.items() if self.is_usd(a)) * s + (self.cash_cu + getattr(self, '_pending_etf', 0.0)) * s
        cm = sum(self.comm(ac, a, v[0], 'regular') for (ac, a), v in self.pos.items() if ac == 'T') if self.cfg.costs == 'rakuten' else 0.0
        if self.tax <= 0:
            return tv - fxc - cm
        u = sum(v[0] - v[1] - (self.comm(ac, a, v[0], 'regular') if self.cfg.costs == 'rakuten' else 0.0)
                for (ac, a), v in self.pos.items() if ac == 'T')
        inc = self.ytd + u
        fin = 0.0
        if inc > 0:
            avail = sum(c[1] for c in self.carry if self.year - c[0] <= 3)
            fin = self.tax * max(0.0, inc - avail)
            cred = min(self.wh * self.ydiv, fin) if self.ydiv > 0 else 0.0
            fin -= cred
        return tv - fxc - cm - (fin - self.withheld)

    def liquidate(self, m):
        tot = self.value() + self.cash_all()
        self.stats['nisa_end'] = sum(v[0] for (ac, a), v in self.pos.items() if ac in ('NT', 'NG'))
        self.stats['pre_liq'] = tot
        self.stats['taxable_end'] = sum(v[0] for (ac, a), v in self.pos.items() if ac == 'T')
        self.stats['castle_in_taxable_end'] = sum(v[0] for (ac, a), v in self.pos.items() if ac == 'T' and self.is_castle(a))
        self.stats['life_used_end'] = self.life
        for key in [k for k in self.pos if k[0] == 'T']:
            got = self.sell('T', key[1], self.pos[key][0], m)
            if self.is_usd(key[1]):
                c = got * self.fxs(m); got -= c; self.stats['fx_cost'] += c
            self.cash_i += got
        self.settle(self.year)
        s = self.fxs(m)
        nis = 0.0
        for key in [k for k in self.pos]:
            v = self.pos[key][0]
            if self.is_usd(key[1]):
                c = v * s; v -= c; self.stats['fx_cost'] += c
            nis += v
        cu = self.cash_cu + getattr(self, '_pending_etf', 0.0)
        c = cu * s
        self.stats['fx_cost'] += c
        return nis + self.cash_i + self.cash_cj + cu - c


def run_hh(P, cfg, rule, keys, defl=None, sched=None, record=False, pre_keys=None):
    """keys を順に動かす。defl: 歩 -> 実質化の係数（積立と枠に掛ける）。pre_keys: S4 の持ち越し（課税口座だけで買う歩）"""
    hh = HH(P, cfg, rule, sched)
    per = cfg.contrib * (12 if P['freq'] == 1 else 1)
    rec = {}
    contribs = {}
    if pre_keys:
        hh.pre = True
        for m in pre_keys:
            hh.k = defl(m) if defl else 1.0
            hh.step(m, per * hh.k)
        hh.pre = False
    for m in keys:
        hh.k = defl(m) if defl else 1.0
        c = per * hh.k
        hh.step(m, c)
        if record:
            rec[m] = hh.liquidation_value(m)
            contribs[m] = c
    fin = hh.liquidate(keys[-1])
    return fin, hh, rec, contribs


# ───────────────────────── 合成データでの道具の確かめ（規則と既定は比べない） ─────────────────────────
def synth_path(n=400, r=0.0, dy=0.0, usd=False, fx=100.0, freq=12, start=200001, seed=None, vol=0.0):
    keys = []
    m = start
    for _ in range(n):
        keys.append(m)
        m = madd(m, 1) if freq == 12 else m + 1
    rng = random.Random(seed)
    Rm = {k: (r + (rng.gauss(0, vol) if vol else 0.0)) for k in keys}
    P = {'name': 'SYN', 'freq': freq, 'keys': keys, 'R': {'MKT': Rm}, 'DY': {'MKT': {k: dy for k in keys}},
         'usd': usd, 'fx': {k: fx for k in keys}, 'wh': 0.0}
    return P


def selftest():
    ok = {}
    base = dict(holders=100)            # 枠がほぼ無限
    # (1) 非課税（枠が十分）・費用0・配当0・城0: 積立の閉じた式
    P = synth_path(240, r=0.01)
    cfg = Cfg('t', castle_share=0.0, **base)
    fin, hh, _, _ = run_hh(P, cfg, {}, P['keys'])
    g = 1 + 0.01 - FEE_FUND / 12          # 指数投信の費用 0.10%/年を含む
    closed = sum(170_000 * g ** (240 - i) for i in range(240))
    ok['dca_closed_form'] = abs(fin - closed) < 1e-6 * closed
    # (2) 生涯枠: 値動き0（費用だけ）・2人・月17万 → 3600万で満ち、以後は課税口座。課税口座は費用の分だけ損（税0）
    P0 = synth_path(240, r=0.0)
    cfg = Cfg('t', castle_share=0.0)
    fin, hh, _, _ = run_hh(P0, cfg, {}, P0['keys'])
    g0 = 1 - FEE_FUND / 12
    closed0 = sum(170_000 * g0 ** (240 - i) for i in range(240))
    ok['life_cap_two_holders'] = abs(hh.stats['life_used_end'] - 2 * LIFE) < 1 and abs(fin - closed0) < 1e-6 * closed0 and hh.stats['taxable_end'] > 0 and hh.stats['tax_paid'] == 0
    # (3) 課税口座の一括: V − τ(V−1)（城だけ・回転なし・配当なし）
    P1 = synth_path(240, r=0.01)
    cfg = Cfg('t', castle_share=1.0, turn=0.0, holders=0, contrib=0)
    hh = HH(P1, cfg, {})
    hh.cash_cj = 1.0
    for mm in P1['keys']:
        hh.step(mm, 0.0)
    fin = hh.liquidate(P1['keys'][-1])
    V = 1.01 ** 240
    ok['lump_taxable'] = abs(fin - (V - TAX * (V - 1))) < 1e-9
    # (4) 為替手数料: 値動き0・ドル資産・課税口座だけ → 往復で (1−s)^2 ではなく (1−s)（買い）と売りの s
    P2 = synth_path(24, r=0.0, usd=True, fx=125.0)
    cfg = Cfg('t', castle_share=1.0, turn=0.0, holders=0, contrib=0)
    hh = HH(P2, cfg, {})
    hh.cash_cj = 1000.0
    for mm in P2['keys']:
        hh.step(mm, 0.0)
    fin = hh.liquidate(P2['keys'][-1])
    s = 0.25 / 125.0
    # 買いで s を払い、取得額は1000（手数料込み）・時価 1000(1−s) → 売りで損 1000s（課税口座の損は還付されない・繰越）→ 手取り 1000(1−s)(1−s)
    ok['fx_roundtrip'] = abs(fin - 1000 * (1 - s) * (1 - s)) < 1e-9
    # (5) O1 の枠の回収（月次）: 値が −30% になった NISA の口を12月に売り、1月に簿価の枠が戻って時価で買い戻す → 生涯枠の使用が (B−M) 減る
    P3 = synth_path(30, r=0.0)
    P3['R']['MKT'][P3['keys'][2]] = -0.30
    cfg = Cfg('t', castle_share=0.0, holders=1, contrib=0)
    for rname, rule in (('D0', {}), ('O1', {'o1': O1_L})):
        hh = HH(P3, cfg, rule)
        hh.cash_i = 1_000_000.0
        for mm in P3['keys']:
            hh.step(mm, 0.0)
        if rname == 'D0':
            life_d0 = hh.life
        else:
            life_o1 = hh.life
            st = dict(hh.stats)
    ok['o1_recycles_room'] = abs(life_d0 - 1_000_000) < 1e-6 and 0.695e6 < life_o1 < 0.700e6 and st['o1_sales'] == 1 and st['o1_rebought'] > 0.69e6
    # (6) O1 の年次版: 同じ
    P4 = synth_path(6, r=0.0, freq=1, start=2000)
    P4['R']['MKT'][2001] = -0.30
    hh = HH(P4, cfg, {'o1': O1_L})
    hh.cash_i = 1_000_000.0
    for mm in P4['keys']:
        hh.step(mm, 0.0)
    ok['o1_annual_recycles_room'] = 0.695e6 < hh.life < 0.700e6 and hh.stats['o1_sales'] == 1
    # (7) O2: 課税口座の損の区画を1月に移す → 損が実現して繰越・NISA の枠を使う
    P5 = synth_path(30, r=0.0)
    P5['R']['MKT'][P5['keys'][1]] = -0.20
    cfg = Cfg('t', castle_share=0.0, holders=1, contrib=0)
    hh = HH(P5, cfg, {'o2': 'loss'})
    hh._add('T', 'IDX', 1_000_000.0, 1_000_000.0)
    for mm in P5['keys']:
        hh.step(mm, 0.0)
    ok['o2_moves_loss_lot'] = hh.stats['o2_moves'] == 1 and ('T', 'IDX') not in hh.pos and 0.795e6 < hh.life < 0.800e6 and bool(hh.carry) and hh.carry[0][1] > 0.19e6
    # (8) 繰越は3年で切れる
    ok['carry_expires'] = True
    hh = HH(P5, Cfg('t', holders=0, contrib=0), {})
    hh.year = 2000
    hh.ytd = -100.0
    hh.settle(2000)
    for yy in (2001, 2002, 2003):
        hh.settle(yy)
    ok['carry_expires'] = hh.stats['carry_expired'] > 0 and not hh.carry
    # (9) 按分: 成長枠の空きより需要が大きいとき、指数と城は需要の比で入る
    P6 = synth_path(2, r=0.0)
    cfg = Cfg('t', castle_share=0.5, holders=1, contrib=0)
    hh = HH(P6, cfg, {})
    hh.qu['NT'] = Q_TSUMI                   # つみたて枠は使い切った
    hh.qu['NG'] = Q_GROWTH - 100_000         # 成長枠の残り 10万
    hh.year = P6['keys'][0] // 100
    hh.cash_i = 300_000.0; hh.cash_cj = 100_000.0
    hh.buy_all(P6['keys'][0])
    ng_i = hh.pos.get(('NG', 'IDX'), [0, 0])[1]; ng_c = hh.pos.get(('NG', 'CL'), [0, 0])[1]
    ok['prorata_growth_frame'] = abs(ng_i - 75_000) < 1e-6 and abs(ng_c - 25_000) < 1e-6
    # (10) 規則が一度も発動しなければ既定と一致（O2 は課税口座の区画が無いと何もしない）
    P7 = synth_path(120, r=0.006, vol=0.03, seed=5, dy=0.001)
    cfg = Cfg('t')
    a, _, _, _ = run_hh(P7, cfg, {}, P7['keys'])
    b, hb, _, _ = run_hh(P7, cfg, {'o2': 'loss'}, P7['keys'])
    ok['no_fire_identical'] = abs(a - b) < 1e-6 and hb.stats['o2_moves'] == 0
    # (11) 流動化の値（毎月）と最終額が一致する（最後の月）
    fin, hh, rec, _ = run_hh(P7, Cfg('t', holders=1), {'o1': O1_L, 'o2': 'all'}, P7['keys'], record=True)
    ok['liq_value_matches_final'] = abs(rec[P7['keys'][-1]] - fin) / fin < 1e-9
    return ok


def cross_check_jp_aftertax():
    """mw_jp_aftertax の口座の模型（Arm）と、同じ合成データ・同じ設定（1人・指数だけ／城だけ）で最終額が一致するか"""
    import mw_jp_aftertax as JA
    global COMM_DEDUCT
    COMM_DEDUCT = False                  # mw_jp_aftertax は手数料を譲渡益から引かないので、突き合わせの間だけ同じにする
    P = synth_path(240, r=0.008, vol=0.045, seed=7, dy=0.0015)
    P['wh'] = WH_US
    ks = P['keys']
    one = lambda m: 1.0
    out = {}
    # 指数だけ（つみたて→成長→課税・売らない）
    A = {'IDX': {'vehicle': 'fund', 'fee': FEE_FUND, 'frames': ('NT', 'NG')}}
    st = {'kind': 'single', 'asset': 'IDX', 'T': 0.0, 'cu': 0.0}
    fa, _, _ = JA.run_arm(JA.REG['R2_real'], st, A, {'IDX': P['R']['MKT']}, P['DY']['MKT'], one, ks, contrib_real=CONTRIB)
    fb, _, _, _ = run_hh(P, Cfg('x', holders=1, castle_share=0.0), {}, ks)
    out['index_only_R2'] = [round(fa, 2), round(fb, 2), abs(fa - fb) / fa < 1e-9]
    # 城だけ（直接保有・成長枠だけ・回転 0.25・売りに 0.1%）
    A = {'E': {'vehicle': 'direct', 'fee': 0.0, 'frames': ('NG',)}}
    st = {'kind': 'single', 'asset': 'E', 'T': TURN, 'cu': SWITCH}
    fa, _, _ = JA.run_arm(JA.REG['R2_real'], st, A, {'E': P['R']['MKT']}, P['DY']['MKT'], one, ks, contrib_real=CONTRIB)
    fb, _, _, _ = run_hh(P, Cfg('x', holders=1, castle_share=1.0), {}, ks)
    out['castle_only_R2'] = [round(fa, 2), round(fb, 2), abs(fa - fb) / fa < 1e-6]
    # 課税口座だけ（NISA なし）
    fa, _, _ = JA.run_arm(JA.REG['R3_taxable'], st, A, {'E': P['R']['MKT']}, P['DY']['MKT'], one, ks, contrib_real=CONTRIB)
    fb, _, _, _ = run_hh(P, Cfg('x', holders=0, castle_share=1.0), {}, ks)
    out['castle_only_R3'] = [round(fa, 2), round(fb, 2), abs(fa - fb) / fa < 1e-6]
    COMM_DEDUCT = True
    return out


# ───────────────────────── データ ─────────────────────────
def fr_intl(fname, country='Japan', cur='Local'):
    z = zipfile.ZipFile(io.BytesIO(M.get(f'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{fname}.zip', name=f'fr_{fname}.zip')))
    out, active, seen = {}, False, 0
    for line in z.read(f'{country}.Dat').decode('latin-1').splitlines():
        if 'Value-Weight' in line:
            active = (cur in line) and ('Not Reqd' in line) and seen == 0
            if active:
                seen = 1
            elif seen == 1:
                seen = 2
            continue
        mm = re.match(r'^\s*(\d{6})\s+(.*)$', line)
        if active and mm:
            x = float(mm.group(2).split()[0])
            if x <= -99.99 or x == -999:
                continue
            out[int(mm.group(1))] = x / 100
    return out


def yahoo_close_div(t):
    """Yahoo の月足: adjclose のリターン（mw_common.yahoo）と close のリターンの差＝配当のリターン（負は0に切る・数を数える）"""
    import urllib.parse
    radj = M.yahoo(t)
    b = open(os.path.join(M.CACHE, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json'), 'rb').read()
    j = json.loads(b)
    r = j['chart']['result'][0]
    off = r.get('meta', {}).get('gmtoffset') or 0
    import datetime
    px = {}
    for ts, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(ts + off)
        px[d.year * 100 + d.month] = c
    ks = sorted(px)
    rc = {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k}
    dy, neg = {}, 0
    for k, v in radj.items():
        if k in rc:
            d = v - rc[k]
            if d < 0:
                neg += 1
                d = 0.0
            dy[k] = d
    return {k: radj[k] for k in radj if k in dy}, dy, neg


def load_data():
    import mw_jp_aftertax as JA
    D = {}
    ff = M.ff_factors()
    D['mkt'] = {k: v for k, v in ff['mkt'].items() if k <= FR_END}
    D['dy'] = JA.market_div_return()
    D['cpi_us'] = JA.fill_cpi(JA.fred_monthly('CPIAUCNS', 'first'))
    D['cpi_filled'] = sorted(set(JA.CPI_FILLED))
    D['fx'] = JA.fred_monthly('DEXJPUS', 'last')
    w = M.french_series('49_Industry_Portfolios', 'Value Weight')
    wo = M.french_series('49_Industry_Portfolios_Wout_Div', 'Value Weight')
    D['ind'], D['ind_dy'], negc = {}, {}, 0
    for c in w:
        D['ind'][c] = {k: v for k, v in w[c].items() if k <= FR_END}
        dd = {}
        for k, v in D['ind'][c].items():
            if k in wo.get(c, {}):
                x = v - wo[c][k]
                if x < 0:
                    negc += 1; x = 0.0
                dd[k] = x
        D['ind_dy'][c] = dd
        D['ind'][c] = {k: v for k, v in D['ind'][c].items() if k in dd}
    D['ind_dy_neg_clipped'] = negc
    jw = fr_intl('F-F_International_Countries')
    jo = fr_intl('F-F_International_Countries_Wout_Div')
    D['jp'] = {k: v for k, v in jw.items() if k in jo}
    D['jp_dy'] = {}
    negj = 0
    for k in D['jp']:
        x = jw[k] - jo[k]
        if x < 0:
            negj += 1; x = 0.0
        D['jp_dy'][k] = x
    D['jp_dy_neg_clipped'] = negj
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(M.CACHE, 'jst_R6.xlsx'), read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    hdr = next(rows)
    ix = {k: hdr.index(k) for k in ('year', 'country', 'eq_tr', 'eq_div_rtn', 'cpi')}
    jst = collections.defaultdict(dict)
    for r in rows:
        tr, dv, cp = r[ix['eq_tr']], r[ix['eq_div_rtn']], r[ix['cpi']]
        if tr is None or dv is None or cp is None:
            continue                                  # 欠けた年は使わない（0で埋めない）
        jst[r[ix['country']]][int(r[ix['year']])] = (float(tr), float(dv), float(cp))
    D['jst'] = dict(jst)
    # 実物の城（mw_castle_mech の N5 の選び・2010-07〜）
    cm = json.load(open(os.path.join(M.BASE, 'out', 'mw_castle_mech.json')))
    D['n5'] = cm['castle_selection_N5']
    D['n5_turn'] = cm['graded_primary']['decay_aged25_T3VW']['turnover_oneway_ann']
    D['yh'], D['yh_dy'], D['yh_neg'] = {}, {}, {}
    for t in sorted({n for v in D['n5'].values() for n in v}):
        D['yh'][t], D['yh_dy'][t], D['yh_neg'][t] = yahoo_close_div(t)
    return D


def to_jpy(R, fx):
    out = {}
    for m, r in R.items():
        p = madd(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + r) * fx[m] / fx[p] - 1
    return out


def build_paths(D):
    """事前登録の道の組: USJ（米国市場・円 1971〜）・JPJ（日本市場・円 1975〜）・USD（米国市場・ドル 1926〜）・JST（16か国・年次・現地通貨）"""
    P = {}
    fx = D['fx']
    usj = to_jpy(D['mkt'], fx)
    ks = sorted(k for k in usj if k in D['dy'])
    R = {'MKT': usj}
    DY = {'MKT': D['dy']}
    for c in D['ind']:
        R[c] = to_jpy(D['ind'][c], fx)
        DY[c] = D['ind_dy'][c]
    for t in D['yh']:
        R['Y:' + t] = to_jpy(D['yh'][t], fx)
        DY['Y:' + t] = D['yh_dy'][t]
    P['USJ'] = {'name': 'USJ', 'freq': 12, 'keys': ks, 'R': R, 'DY': DY, 'usd': True, 'fx': fx, 'wh': WH_US, 'defl': None,
                'names': sorted(D['ind'])}
    ks = sorted(k for k in D['mkt'] if k in D['dy'])
    R = {'MKT': D['mkt']}
    DY = {'MKT': D['dy']}
    for c in D['ind']:
        R[c] = D['ind'][c]; DY[c] = D['ind_dy'][c]
    cpi = D['cpi_us']
    P['USD'] = {'name': 'USD', 'freq': 12, 'keys': ks, 'R': R, 'DY': DY, 'usd': False, 'fx': None, 'wh': WH_US, 'defl': cpi,
                'names': sorted(D['ind'])}
    ks = sorted(D['jp'])
    P['JPJ'] = {'name': 'JPJ', 'freq': 12, 'keys': ks, 'R': {'MKT': D['jp']}, 'DY': {'MKT': D['jp_dy']}, 'usd': False, 'fx': None,
                'wh': 0.0, 'defl': None, 'names': None}
    for c, d in D['jst'].items():
        ys = sorted(d)
        P['JST:' + c] = {'name': 'JST:' + c, 'freq': 1, 'keys': ys, 'R': {'MKT': {y: d[y][0] for y in ys}},
                         'DY': {'MKT': {y: d[y][1] for y in ys}}, 'usd': False, 'fx': None, 'wh': 0.0,
                         'defl': {y: d[y][2] for y in ys}, 'names': None}
    return P


def windows(P, H, pre=0):
    """1月起点（年次は毎年）・H 年の連続した歩。pre>0 なら起点の前に pre 歩が連続してあるものだけ"""
    ks = P['keys']
    f = P['freq']
    n = H * f
    pos = {k: i for i, k in enumerate(ks)}
    out = []
    for i, k in enumerate(ks):
        if f == 12 and k % 100 != 1:
            continue
        if i - pre < 0 or i + n > len(ks):
            continue
        seg = ks[i - pre:i + n]
        ok = True
        for a, b in zip(seg, seg[1:]):
            if (madd(a, 1) if f == 12 else a + 1) != b:
                ok = False; break
        if ok:
            out.append((ks[i - pre:i], ks[i:i + n]))
    return out


def deflator(P, keys):
    d = P.get('defl')
    if not d:
        return None
    k0 = keys[0]
    base = d[k0]
    return lambda m: d[m] / base


def names_sched_random(P, seed, start_key):
    """名前の城: 起点で5業種を無作為に（その月にデータがあるものから）、以後10か月ごとに一番古い1業種を入れ替え（seed は窓ごとに固定）"""
    rng = random.Random(f'{seed}-{start_key}')
    pool = P['names']

    def sched(hh, m):
        cur = [n for n, _ in hh.names]
        avail = [n for n in pool if m in P['R'][n]]
        if not cur:
            return rng.sample(avail, NAME_N)
        want = list(cur)
        if hh.step_i > 0 and hh.step_i % NAME_EVERY == 0:
            oldest = min(hh.names, key=lambda x: (x[1], x[0]))[0]
            want.remove(oldest)
        miss = [n for n in want if m not in P['R'][n]]
        for n in miss:
            want.remove(n)
        while len(want) < NAME_N:
            c = [n for n in avail if n not in want and n not in cur]
            want.append(rng.choice(c))
        return want
    return sched


def names_sched_n5(D):
    """実物の城（mw_castle_mech の N5）: 毎年7月にその年の5銘柄へ入れ替え"""
    sel = {int(y): ['Y:' + t for t in v] for y, v in D['n5'].items()}

    def sched(hh, m):
        y = m // 100 if m % 100 >= 7 else m // 100 - 1
        return sel.get(y, [n for n, _ in hh.names])
    return sched


# ───────────────────────── 測る ─────────────────────────
def summarize(rs):
    """[(起点, 比)] → 勝ち（比>1）・同点（|比−1|<1e-9）・中央・最悪・最良・10%点"""
    if not rs:
        return None
    v = sorted(r for _, r in rs)
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return {'n': n, 'win_share': round(sum(1 for r in v if r > 1 + 1e-9) / n, 3), 'tie_share': round(sum(1 for r in v if abs(r - 1) <= 1e-9) / n, 3),
            'median': round(med, 5), 'p10': round(v[int(n * 0.1)], 5), 'worst': [min(rs, key=lambda x: x[1])[0], round(min(v), 5)],
            'best': [max(rs, key=lambda x: x[1])[0], round(max(v), 5)]}


class Lab:
    def __init__(self, D, P):
        self.D, self.P = D, P
        self.cache = {}

    def arm(self, pname, cfg, rname, pre, keys, seed=None, record=False):
        P = self.P[pname]
        rule = RULES[rname]
        if cfg.castle == 'names':
            sched = names_sched_random(P, seed, keys[0])
        elif cfg.castle == 'n5':
            sched = names_sched_n5(self.D)
        else:
            sched = None
        defl = deflator(P, keys)
        return run_hh(P, cfg, rule, keys, defl, sched, record, pre_keys=pre or None)

    def ratio(self, pname, cfg, rname, pre, keys, seed=None):
        ck = (pname, cfg.name, cfg.castle, seed, keys[0], len(keys))
        if ck not in self.cache:
            fb, hb, _, _ = self.arm(pname, cfg, 'D0', pre, keys, seed)
            self.cache[ck] = (fb, dict(hb.stats))
        fb, sb = self.cache[ck]
        fs, hs, _, _ = self.arm(pname, cfg, rname, pre, keys, seed)
        return fs / fb, dict(hs.stats), sb, fs, fb


def run_windows(lab, pnames, cfg, rname, seed=None):
    """道の組ごと・H ごとの比の分布"""
    out = {}
    pre = 12 if cfg.init_taxable else 0
    for pn in pnames:
        P = lab.P[pn]
        pre_n = (1 if P['freq'] == 1 else 12) if cfg.init_taxable else 0
        for H in HORIZONS:
            rs, diag = [], []
            for pk, ks in windows(P, H, pre_n):
                r, ss, sb, fs, fb = lab.ratio(pn, cfg, rname, pk, ks, seed)
                rs.append((ks[0], round(r, 6)))
                diag.append((ss, sb, fs, fb))
            out.setdefault(pn, {})[H] = {'rs': rs, 'diag': diag}
    return out


def pool_jst(W, H):
    rs = []
    for pn, v in W.items():
        if pn.startswith('JST:') and H in v:
            rs += [(pn[4:] + ':' + str(k), r) for k, r in v[H]['rs']]
    return rs


def diag_med(diag):
    def med(xs):
        xs = sorted(xs)
        return round(xs[len(xs) // 2], 5) if xs else None
    if not diag:
        return None
    return {'o1_sales': med([d[0].get('o1_sales', 0) for d in diag]),
            'o1_room_gain_over_final': med([d[0].get('o1_room_gain', 0) / d[2] for d in diag]),
            'o2_moved_over_final': med([d[0].get('o2_moved', 0) / d[2] for d in diag]),
            'nisa_share_end_rule': med([d[0].get('nisa_end', 0) / d[0]['pre_liq'] for d in diag if d[0].get('pre_liq')]),
            'nisa_share_end_default': med([d[1].get('nisa_end', 0) / d[1]['pre_liq'] for d in diag if d[1].get('pre_liq')]),
            'tax_paid_over_final_rule': med([d[0].get('tax_paid', 0) / d[2] for d in diag]),
            'tax_paid_over_final_default': med([d[1].get('tax_paid', 0) / d[3] for d in diag]),
            'costs_over_final_rule': med([(d[0].get('comm_cost', 0) + d[0].get('fx_cost', 0)) / d[2] for d in diag]),
            'costs_over_final_default': med([(d[1].get('comm_cost', 0) + d[1].get('fx_cost', 0)) / d[3] for d in diag])}


def block(W, pnames_main):
    """記録用: 道の組 × H の要約（JST は合算と国別・1926年より前の起点と後）"""
    res = {}
    for pn in pnames_main:
        if pn == 'JST':
            continue
        if pn not in W:
            continue
        res[pn] = {}
        for H, v in W[pn].items():
            rs = v['rs']
            e = {'all': summarize(rs), 'diag_median': diag_med(v['diag'])}
            if lab_monthly(pn):
                end_le_2006 = [(k, r) for k, r in rs if (k // 100 + H - 1) <= 2006]
                end_ge_2007 = [(k, r) for k, r in rs if (k // 100 + H - 1) >= 2007]
                e['ending_le_2006'] = summarize(end_le_2006)
                e['ending_ge_2007'] = summarize(end_ge_2007)
            res[pn][H] = e
    if any(k.startswith('JST:') for k in W):
        res['JST'] = {}
        for H in HORIZONS:
            rs = pool_jst(W, H)
            dg = [d for pn, v in W.items() if pn.startswith('JST:') and H in v for d in v[H]['diag']]
            pre = [(k, r) for k, r in rs if int(k.split(':')[1]) < 1926]
            post = [(k, r) for k, r in rs if int(k.split(':')[1]) >= 1926]
            by = {pn[4:]: summarize(v[H]['rs']) for pn, v in W.items() if pn.startswith('JST:') and H in v and v[H]['rs']}
            res['JST'][H] = {'all': summarize(rs), 'start_lt_1926_fresh': summarize(pre), 'start_ge_1926': summarize(post),
                             'by_country': by, 'diag_median': diag_med(dg)}
    return res


def lab_monthly(pn):
    return pn in ('USJ', 'JPJ', 'USD')


def verdict(res, sets=('USJ', 'JPJ', 'USD', 'JST')):
    """事前登録の判定: H ごとに、全部の道の組で 勝ち ≥ 0.90 かつ 中央 ≥ 1"""
    pass_h, detail = {}, {}
    for H in HORIZONS:
        ok = True
        d = {}
        for s in sets:
            e = (res.get(s) or {}).get(H, {}).get('all')
            if not e:
                ok = False; d[s] = None; continue
            c = e['win_share'] >= 0.90 and e['median'] >= 1.0
            d[s] = {'win_share': e['win_share'], 'median': e['median'], 'tie_share': e['tie_share'], 'pass': c}
            ok = ok and c
        pass_h[H] = ok
        detail[H] = d
    if all(pass_h.values()):
        v = '勝つ（頑丈）'
    elif pass_h[30] or pass_h[25]:
        v = '長い窓だけ勝つ'
    else:
        meds = [detail[20][s]['median'] for s in sets if detail[20].get(s)]
        v = '負ける' if meds and all(x < 1 for x in meds) else '勝たない'
    return v, pass_h, detail


def stress(W):
    """事前登録の圧力の窓: 米国の失われた10年（USJ・USD の 2000-01 起点）・日本の1990年代（JPJ の 1989-01・1990-01 起点）"""
    out = {}
    for pn, starts in (('USJ', (199901, 200001)), ('USD', (199901, 200001)), ('JPJ', (198901, 199001))):
        if pn not in W:
            continue
        for H, v in W[pn].items():
            for k, r in v['rs']:
                if k in starts:
                    out[f'{pn}_{k}_{H}y'] = r
    return out


def twr(rec, contribs, keys):
    out, prev = {}, 0.0
    for m in keys:
        c = contribs[m]
        den = prev + c
        out[m] = (rec[m] - prev - c) / den if den > 0 else 0.0
        prev = rec[m]
    return out


def grade_block(lab, cfg, rname, pn='USJ'):
    """mw_common.grade の材料: 期間ごとに家計を作り直し（毎月積立）、税引後の『いま全部売ったら』の時間加重リターンを規則と既定で比べる"""
    P = lab.P[pn]
    ks = P['keys']
    per = {'full': (ks[0], ks[-1]), 'train': (ks[0], M.TRAIN_END), 'hold': (M.HOLD_START, ks[-1]), 'recent': (M.RECENT_START, ks[-1])}
    st, series = {}, {}
    for nm, (a, z) in per.items():
        kk = [k for k in ks if a <= k <= z]
        fs, hs, rs, cs = lab.arm(pn, cfg, rname, None, kk, record=True)
        fb, hb, rb, cb = lab.arm(pn, cfg, 'D0', None, kk, record=True)
        s, b = twr(rs, cs, kk), twr(rb, cb, kk)
        st[nm] = M.excess_stats(s, b)
        st[nm + '_final_ratio'] = round(fs / fb, 6)
        series[nm] = (s, b)
    s, b = series['full']
    st['rolling20_on_full_twr'] = M.rolling(s, b, 20)
    st['dca20_on_full_twr'] = M.dca(s, b, 20)
    return st


def main():
    t0 = time.time()
    D = load_data()
    P = build_paths(D)
    lab = Lab(D, P)
    out = {'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': git_sha(f'out/{PREREG}'), 'global_prereg': 'mw_prereg.json',
           'global_prereg_commit': git_sha('out/mw_prereg.json'),
           'benchmark': '既定の運用 D0（同じ道・同じ積立・同じ資産: NISA から先に買う〔指数はつみたて→成長・城は成長〕・売らない〔城の回転だけ〕・減らすときは口座の時価で按分・枠の回収や移し替えなし・課税口座の溢れも積み上げ型の投信）',
           'sanity': {}, 'deviations': [], 'tested': []}
    san = out['sanity']
    san['selftest'] = selftest()
    san['cross_check_vs_mw_jp_aftertax'] = cross_check_jp_aftertax()
    log('selftest', san['selftest'])
    log('cross_check', san['cross_check_vs_mw_jp_aftertax'])
    san['french_mkt_cagr_full'] = round(M.cagr(D['mkt']) * 100, 2)
    san['french_mkt_cagr_2007'] = round(M.cagr(M.window(D['mkt'], M.HOLD_START)) * 100, 2)
    san['usj_cagr_2007_jpy'] = round(M.cagr(M.window(P['USJ']['R']['MKT'], M.HOLD_START)) * 100, 2)
    san['jpj_cagr_full_local'] = round(M.cagr(D['jp']) * 100, 2)
    san['jpj_cagr_1990_2009'] = round(M.cagr(M.window(D['jp'], 199001, 200912)) * 100, 2)
    san['cpi_filled_months'] = D['cpi_filled']
    san['ind_dy_neg_clipped'] = D['ind_dy_neg_clipped']
    san['jp_dy_neg_clipped'] = D['jp_dy_neg_clipped']
    san['yahoo_dy_neg_clipped'] = D['yh_neg']
    san['n5_turnover_oneway_ann_castle_mech'] = D['n5_turn']
    san['paths'] = {pn: {'from': p['keys'][0], 'to': p['keys'][-1], 'n': len(p['keys']), 'freq': p['freq']} for pn, p in P.items()}
    san['windows_count'] = {pn: {H: len(windows(p, H)) for H in HORIZONS} for pn, p in P.items()}
    log('sanity', json.dumps({k: san[k] for k in ('french_mkt_cagr_full', 'french_mkt_cagr_2007', 'usj_cagr_2007_jpy', 'jpj_cagr_full_local', 'jpj_cagr_1990_2009')}, ensure_ascii=False))
    main_sets = ['USJ', 'JPJ', 'USD'] + [pn for pn in P if pn.startswith('JST:')]
    fam = {}
    # 主の族（P）と副（O1_L10）
    for sc in ['P', 'S1_one_holder', 'S2_300k', 'S3_tax25', 'S4_init_taxable']:
        cfg = SCEN[sc]
        for rn in PRIMARY_RULES + SECONDARY_RULES:
            W = run_windows(lab, main_sets, cfg, rn)
            res = block(W, ['USJ', 'JPJ', 'USD', 'JST'])
            v, ph, det = verdict(res)
            rec = {'name': f'{rn}__{sc}', 'rule': rn, 'scenario': sc, 'castle': 'clone', 'costs': 'brief',
                   'family': 'primary' if (sc == 'P' and rn in PRIMARY_RULES) else ('secondary_rule' if sc == 'P' else 'sensitivity'),
                   'verdict': v, 'pass_by_horizon': ph, 'verdict_detail': det, 'windows': res, 'stress': stress(W),
                   'windows_usj20': W['USJ'][20]['rs'] if sc in ('P',) else None}
            out['tested'].append(rec)
            fam[(rn, sc)] = rec
            u = res['USJ'][20]['all']; j = res['JPJ'][20]['all']; us = res['USD'][20]['all']; js = res['JST'][20]['all']
            log(f'{rn:7s} {sc:16s} {v:10s} USJ20 勝{u["win_share"]} 同{u["tie_share"]} 中{u["median"]} | JPJ20 勝{j["win_share"]} 中{j["median"]} | USD20 勝{us["win_share"]} 中{us["median"]} | JST20 勝{js["win_share"]} 中{js["median"]}  ({time.time() - t0:.0f}s)')
    # 城を名前（49業種・5銘柄）で持つ（米国の道だけ・3つの seed）
    for rn in PRIMARY_RULES + SECONDARY_RULES:
        for seed in SEEDS:
            cfg = Cfg('S5_names', castle='names', seed=seed)
            W = run_windows(lab, ['USJ', 'USD'], cfg, rn, seed=seed)
            res = block(W, ['USJ', 'USD'])
            v, ph, det = verdict(res, sets=('USJ', 'USD'))
            out['tested'].append({'name': f'{rn}__S5_names_seed{seed}', 'rule': rn, 'scenario': 'S5_names', 'seed': seed, 'castle': 'names49',
                                  'costs': 'brief', 'family': 'sensitivity', 'verdict': v, 'pass_by_horizon': ph, 'verdict_detail': det,
                                  'windows': res, 'stress': stress(W)})
            u = res['USJ'][20]['all']; us = res['USD'][20]['all']
            log(f'{rn:7s} S5_names s{seed} {v:10s} USJ20 勝{u["win_share"]} 中{u["median"]} | USD20 勝{us["win_share"]} 中{us["median"]}  ({time.time() - t0:.0f}s)')
    # 楽天の実際の手数料（USJ だけ）
    for rn in PRIMARY_RULES + SECONDARY_RULES:
        cfg = SCEN['S7_rakuten']
        W = run_windows(lab, ['USJ'], cfg, rn)
        res = block(W, ['USJ'])
        v, ph, det = verdict(res, sets=('USJ',))
        out['tested'].append({'name': f'{rn}__S7_rakuten', 'rule': rn, 'scenario': 'S7_rakuten', 'castle': 'clone', 'costs': 'rakuten',
                              'family': 'sensitivity', 'verdict': v, 'pass_by_horizon': ph, 'verdict_detail': det, 'windows': res, 'stress': stress(W)})
        u = res['USJ'][20]['all']
        log(f'{rn:7s} S7_rakuten {v:10s} USJ20 勝{u["win_share"]} 中{u["median"]}  ({time.time() - t0:.0f}s)')
    # 実物の城 N5（2010-07〜2026-08・USJ・一本の窓・2人と1人）
    n5 = {}
    ks = [k for k in P['USJ']['keys'] if 201007 <= k <= FR_END]
    for sc, hol in (('P', 2), ('S1_one_holder', 1)):
        for rn in PRIMARY_RULES + SECONDARY_RULES:
            cfg = Cfg('S6_n5_' + sc, castle='n5', holders=hol)
            r, ss, sb, fs, fb = lab.ratio('USJ', cfg, rn, None, ks)
            n5[f'{rn}__{sc}'] = {'ratio': round(r, 6), 'rule_final': round(fs), 'default_final': round(fb),
                                 'nisa_share_end_rule': round(ss.get('nisa_end', 0) / ss['pre_liq'], 4) if ss.get('pre_liq') else None,
                                 'nisa_share_end_default': round(sb.get('nisa_end', 0) / sb['pre_liq'], 4) if sb.get('pre_liq') else None,
                                 'names_replaced_default': sb.get('names_replaced'), 'forced_exit_default': sb.get('names_forced_exit'),
                                 'tax_paid_rule': round(ss.get('tax_paid', 0)), 'tax_paid_default': round(sb.get('tax_paid', 0))}
            out['tested'].append({'name': f'{rn}__S6_n5_{sc}', 'rule': rn, 'scenario': 'S6_n5_' + sc, 'castle': 'n5_actual', 'costs': 'brief',
                                  'family': 'sensitivity', 'single_window': n5[f'{rn}__{sc}']})
            log(f'{rn:7s} S6_n5 {sc:14s} 比 {r:.5f}')
    out['n5_2010'] = n5
    # 格付け（mw_common.grade）: USJ の時間加重（税引後の『いま全部売ったら』）・族ごとに Holm
    out['grades'] = {}
    for sc in ['P', 'S1_one_holder', 'S2_300k', 'S4_init_taxable']:
        cfg = SCEN[sc]
        gb = {rn: grade_block(lab, cfg, rn) for rn in PRIMARY_RULES + SECONDARY_RULES}
        fams = [(PRIMARY_RULES, 'primary' if sc == 'P' else f'sens_{sc}'), (SECONDARY_RULES, 'secondary' if sc == 'P' else f'sens2_{sc}')]
        for members, fname in fams:
            hp = M.holm({rn: (gb[rn]['hold'] or {}).get('p') for rn in members if gb[rn].get('hold')})
            for rn in members:
                g = gb[rn]
                rec = fam[(rn, sc)]
                u20 = rec['windows']['USJ'][20]['all']
                roll = {'windows': u20['n'], 'wins': round(u20['win_share'] * u20['n']), 'win_rate': u20['win_share'], 'median': u20['median'],
                        'worst': u20['worst'], 'best': u20['best'], 'note': 'USJ の毎月積立20年窓（家計を窓ごとに作り直す）の最終額の比。一括ではない（事前登録の逸脱）'}
                reg = [(c, e['median']) for c, e in rec['windows']['JST'][20]['by_country'].items() if c != 'USA' and e]
                repl = {'regions': len(reg), 'positive': sum(1 for _, x in reg if x > 1.0), 'source': 'JST の米国以外15か国の20年窓の比の中央 > 1'}
                gr, cr = M.grade(g['full'], g['train'], g['hold'], roll, cost_hold=g['hold'], repl=repl, family_holm_p=hp.get(rn), leveraged_or_timing=False)
                ent = {'rule': rn, 'scenario': sc, 'family': fname, 'full': g['full'], 'train': g['train'], 'hold': g['hold'], 'recent': g['recent'],
                       'net_cost_hold': g['hold'], 'final_ratio': {k: g[k + '_final_ratio'] for k in ('full', 'train', 'hold', 'recent')},
                       'roll20_dca_windows': roll, 'rolling20_on_full_twr': g['rolling20_on_full_twr'], 'dca20_on_full_twr': g['dca20_on_full_twr'],
                       'repl': repl, 'holm_p_hold': hp.get(rn), 'grade': gr, 'criteria': cr}
                out['grades'][f'{rn}__{sc}'] = ent
                rec['grade'] = gr; rec['criteria'] = cr
                log(f'格付け {rn:7s} {sc:16s} {gr} full {g["full"] and g["full"]["ex_ann"]} t{g["full"] and g["full"]["t"]} | hold {g["hold"] and g["hold"]["ex_ann"]} t{g["hold"] and g["hold"]["t"]} | holm {hp.get(rn)}')
    out['n_tested'] = len(out['tested'])
    out['runtime_s'] = round(time.time() - t0)
    out['log_tail'] = LOG[-400:]
    M.save(OUT, out)
    log('保存', OUT, out['n_tested'], f'{time.time() - t0:.0f}s')


def dry():
    D = load_data()
    P = build_paths(D)
    info = {pn: {'from': p['keys'][0], 'to': p['keys'][-1], 'n': len(p['keys']), 'windows': {H: len(windows(p, H)) for H in HORIZONS},
                 'windows_pre': {H: len(windows(p, H, 12 if p['freq'] == 12 else 1)) for H in HORIZONS}} for pn, p in P.items()}
    print(json.dumps(info, ensure_ascii=False, indent=0))
    print('ind neg clipped', D['ind_dy_neg_clipped'], 'jp neg', D['jp_dy_neg_clipped'], 'yh neg', D['yh_neg'])
    print('cpi filled', D['cpi_filled'])


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=1))
        print(json.dumps(cross_check_jp_aftertax(), ensure_ascii=False, indent=1))
    elif '--dry' in sys.argv:
        dry()
    else:
        main()
