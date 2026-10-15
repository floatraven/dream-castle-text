# -*- coding: utf-8 -*-
"""梦城堡 · 引擎：只管规则和状态，不管打印。

* 全部状态都是 dict / list，可以直接存成 JSON。
* 所有随机都来自操作系统的随机数（random.SystemRandom），存档里没有种子可以反推。
* 牌堆不预先排好顺序：剩下的牌放在一个「没有顺序的池子」里，每次抽牌时才随机挑一张。
  只有被看过的牌（芭蕾娃娃偷看、预言梦翻开的牌堆顶）和被塞到底下的牌，才有固定位置。
"""
import math
import random

from .data import (FLOORS, ROOMS, ENEMIES, POOL, ELITES, CARDS, CANDLES, DOORS, BELL,
                   JUNK, JUNK_BY, RELICS, PALS, DEPTHS, START_CARDS, HAND_MAX, DREAMS,
                   DOUJI_MOVES)

VERSION = 1
_R = random.SystemRandom()


def set_rng(r):
    """只给开发测试用：换成可复现的随机数。游戏命令从不调用它。"""
    global _R
    _R = r


# ================================================================ 小工具
def rnd():
    return _R.random()


def ri(a, b):
    return a + int(math.floor(rnd() * (b - a + 1)))


def pick(a):
    return a[int(math.floor(rnd() * len(a)))]


def shuffle(a):
    for i in range(len(a) - 1, 0, -1):
        j = int(math.floor(rnd() * (i + 1)))
        a[i], a[j] = a[j], a[i]
    return a


def wpick(entries):
    s = sum(e[1] for e in entries)
    r = rnd() * s
    for e in entries:
        r -= e[1]
        if r < 0:
            return e[0]
    return entries[-1][0]


def clamp(v, a, b):
    return max(a, min(b, v))


def avg(a):
    return sum(a) / len(a) if a else 0


def jsround(x):
    """和 JavaScript 的 Math.round 一样：.5 往上进。"""
    return int(math.floor(x + 0.5))


def key(x, y):
    return '%d,%d' % (x, y)


def unkey(k):
    x, y = k.split(',')
    return int(x), int(y)


def last(a):
    return a[-1] if a else None


# ================================================================ 基础状态操作
def has_relic(G, rid):
    return rid in G['relics']


def has_pal(G, pid):
    return any(p['id'] == pid for p in G['pals'])


def pal_count(G):
    """伙伴数量（斗鸡不算）。"""
    return sum(1 for p in G['pals'] if p['id'] != 'douji')


def is_junk(it):
    return bool(it) and it.get('kind') == 'junk'


def junk_count(G):
    return sum(1 for x in G['luggage'] if is_junk(x))


def real_luggage(G):
    return [x for x in G['luggage'] if not is_junk(x)]


def luggage_cap(G):
    return 6 + (3 if has_relic(G, 'bag') else 0)


def over_cap(G):
    return len(G['luggage']) > luggage_cap(G)


def note(G, text, kind='info'):
    G.setdefault('inbox', []).append({'text': text, 'kind': kind})


def heal(G, n):
    before = G['hp']
    G['hp'] = min(G['maxHp'], G['hp'] + n)
    return G['hp'] - before


def hurt(G, n):
    if n <= 0:
        return 0
    G['hp'] -= n
    if G['hp'] <= 0 and has_relic(G, 'slipper') and not G['flags'].get('slipper'):
        G['hp'] = 1
        G['flags']['slipper'] = True
        note(G, '水晶鞋碎了。你留住了最后 1 点血。', 'good')
    return n


def add_luc(G, n):
    before = G['luc']
    v = clamp(before + n, 0, 7)
    if n < 0 and has_relic(G, 'spindle'):
        v = max(v, min(1, before))
    G['luc'] = v
    return v - before


def add_coins(G, n, can_double=False):
    if can_double and G.get('map') and G['map'].get('dream') == 'repeat' and rnd() < 0.3:
        n *= 2
        note(G, '重复梦：这笔糖霜币翻倍了。', 'good')
    G['coins'] += n
    G['stats']['coins'] += max(0, n)
    return n


def add_item(G, kind, iid):
    it = {'u': G['uid'], 'kind': kind, 'id': iid}
    G['uid'] += 1
    if kind == 'card':
        G['cards'].append(it)
    else:
        G['luggage'].append(it)
    return it


def item_name(it):
    k = it['kind']
    if k == 'card':
        return CARDS[it['id']]['name']
    if k == 'candle':
        return CANDLES[it['id']]['name']
    if k == 'door':
        return DOORS[it['id']]['name']
    if k == 'bell':
        return BELL['name']
    if k == 'relic':
        return RELICS[it['id']]['name']
    if k == 'coins':
        return '%d 糖霜币' % it['n']
    if k == 'junk':
        return JUNK[it['id']]['name']
    return '？'


def item_kind_name(it):
    return {'card': '王牌', 'candle': '蜡烛', 'door': '门', 'bell': '铃铛', 'relic': '藏品', 'junk': '纪念品', 'coins': '糖霜币'}.get(it['kind'], '')


def item_desc(it):
    k = it['kind']
    if k == 'card':
        return CARDS[it['id']]['desc']
    if k == 'candle':
        c = CANDLES[it['id']]
        return '点着时：%s熄灭时：%s最多烧 %d 步。' % (c['on'], c['off'], c['max'])
    if k == 'door':
        return DOORS[it['id']]['desc']
    if k == 'bell':
        return BELL['desc']
    if k == 'relic':
        return RELICS[it['id']]['desc']
    if k == 'junk':
        return JUNK[it['id']]['desc']
    return ''


def add_junk(G, jid, soft=False):
    """往行李箱塞纪念品。纪念品最多占到「容量 - 1」格，保证你总能走动；
    再塞不下时，改成拿走一点糖霜币。"""
    if junk_count(G) >= luggage_cap(G) - 1:
        lost = 0 if soft else min(G['coins'], 8)
        G['coins'] -= lost
        return {'name': JUNK[jid]['name'], 'full': True, 'lost': lost}
    add_item(G, 'junk', jid)
    G['stats']['junk'] = G['stats'].get('junk', 0) + 1
    return {'name': JUNK[jid]['name'], 'full': False, 'lost': 0}


def gain_relic(G, rid):
    if has_relic(G, rid):
        return False
    G['relics'].append(rid)
    if rid == 'crown':
        G['maxHp'] += 1
        heal(G, 1)
    if rid == 'shard':
        G['maxHp'] = max(1, G['maxHp'] - 1)
        G['hp'] = min(G['hp'], G['maxHp'])
    if rid == 'lamp':
        add_luc(G, 2)
    return True


def remove_item(G, u):
    k = str(u)
    for lst in (G['luggage'], G['cards']):
        for i, x in enumerate(lst):
            if str(x['u']) == k:
                return lst.pop(i)
    return None


def find_item(G, u):
    k = str(u)
    for lst in (G['luggage'], G['cards']):
        for x in lst:
            if str(x['u']) == k:
                return x
    return None


def rand_card_id():
    tier = wpick([['C', 58], ['U', 31], ['R', 11]])
    return pick([k for k in CARDS if CARDS[k]['r'] == tier])


def rand_candle_id():
    return wpick([['red', 2], ['long', 2], ['eerie', 2], ['scent', 1.5], ['star', 2], ['mint', 2]])


def rand_tool():
    k = wpick([['candle', 3], ['door', 2.4], ['bell', 0.9]])
    if k == 'candle':
        return {'kind': 'candle', 'id': rand_candle_id()}
    if k == 'door':
        return {'kind': 'door', 'id': wpick([['wood', 6], ['spin', 3], ['gold', 1]])}
    return {'kind': 'bell', 'id': 'bell'}


def rand_relic_id(G, tiers, exclude=None):
    ex = set(G.get('relics') or []) | set(exclude or [])
    w = {'C': 6, 'U': 4, 'R': 2}
    pool = [k for k in RELICS if k not in ex and RELICS[k]['t'] in tiers]
    if not pool:
        anyk = [k for k in RELICS if k not in ex]
        return pick(anyk) if anyk else None
    return wpick([[k, w[RELICS[k]['t']]] for k in pool])


def relic_choices(G, n, tiers='CUR'):
    out = []
    for _ in range(n):
        r = rand_relic_id(G, tiers, out)
        if r:
            out.append(r)
    return out


# ---------------------------------------------------------------- 价格
def base_price(kind, iid):
    if kind == 'card':
        return {'C': 20, 'U': 32, 'R': 48}[CARDS[iid]['r']]
    if kind == 'candle':
        return {'red': 52, 'long': 40, 'eerie': 36, 'scent': 36, 'star': 40, 'mint': 40}[iid]
    if kind == 'door':
        return {'wood': 22, 'spin': 34, 'gold': 52}[iid]
    if kind == 'bell':
        return 45
    if kind == 'relic':
        return {'C': 55, 'U': 80, 'R': 112}[RELICS[iid]['t']]
    return 18


def price_mult(G):
    m = 1.0
    if any(c['id'] == 'long' for c in G['lit']):
        m *= 0.7
    if has_relic(G, 'gacha'):
        m *= 0.85
    return m


def sell_price(it):
    if it['kind'] == 'relic':
        return {'C': 18, 'U': 26, 'R': 36}[RELICS[it['id']]['t']]
    return max(4, int(math.floor(base_price(it['kind'], it['id']) * 0.35)))


# ================================================================ 新的一场梦
def new_run(pal_id, meta, depth):
    d = depth if depth in DEPTHS else 'deep'
    G = {
        'v': VERSION, 'floor': 1, 'hp': DEPTHS[d]['hp'], 'maxHp': DEPTHS[d]['hp'], 'luc': 3, 'coins': 20,
        'depth': d, 'luggage': [], 'cards': [], 'relics': [], 'lit': [], 'litFloor': 0,
        'pals': [{'id': 'douji', 'lv': 1}, {'id': pal_id, 'lv': 1}],
        'map': None, 'stack': [], 'battle': None, 'pending': None,
        'flags': {}, 'uid': 1, 'seenEvents': [], 'dreamsUsed': [], 'holeUsed': False,
        'stats': {'fights': 0, 'wins': 0, 'rooms': 0, 'coins': 0, 'cmds': 0, 'junk': 0, 'junkGone': 0},
        'inbox': [], 'screen': 'map', 'letter': [], 'journal': [],
        'dead': False, 'won': False, 'ending': None,
    }
    for cid in START_CARDS:
        add_item(G, 'card', cid)
    add_item(G, 'door', 'wood')
    locker = meta.get('locker') or []
    if locker:
        got = []
        for it in locker:
            if it['kind'] == 'coins':
                G['coins'] += it['n']
                got.append('%d 糖霜币' % it['n'])
            else:
                add_item(G, it['kind'], it['id'])
                got.append(item_name(it))
        meta['locker'] = []
        note(G, '安娜把上一次寄存的东西交给了你：' + '、'.join(got), 'good')
    enter_floor(G, 1, {'carry': 0, 'light': 0, 'how': 'start'})
    return G


# ================================================================ 地图生成
def neighbors4(k, W, H):
    x, y = unkey(k)
    out = []
    for a, b in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= a < W and 0 <= b < H:
            out.append(key(a, b))
    return out


def bfs(adj, start, avoid=None):
    d = {start: 0}
    q = [start]
    i = 0
    while i < len(q):
        c = q[i]
        i += 1
        for n in sorted(adj[c]):
            if n in d or (avoid and n in avoid):
                continue
            d[n] = d[c] + 1
            q.append(n)
    return d


def grow_cells(W, H, N, start, bias):
    cells = [start]
    cellset = {start}
    guard = 0
    while len(cells) < N and guard < 2000:
        guard += 1
        c = pick(cells)
        x, y = unkey(c)
        opts = [(a, b, w) for (a, b, w) in ((x, y - 1, bias['up']), (x + 1, y, bias['side']),
                                             (x - 1, y, bias['side']), (x, y + 1, bias['down']))
                if 0 <= a < W and 0 <= b < H and key(a, b) not in cellset]
        if not opts:
            continue
        o = wpick([[o, o[2]] for o in opts])
        k = key(o[0], o[1])
        cells.append(k)
        cellset.add(k)
    return cells


def spanning(cells, start, W, H, extra):
    cellset = set(cells)
    adj = {c: set() for c in cells}
    in_t = {start}
    fr = [[start, n] for n in neighbors4(start, W, H) if n in cellset]
    while fr:
        i = int(math.floor(rnd() * len(fr)))
        a, b = fr.pop(i)
        if b in in_t:
            continue
        in_t.add(b)
        adj[a].add(b)
        adj[b].add(a)
        for n in neighbors4(b, W, H):
            if n in cellset and n not in in_t:
                fr.append([b, n])
    for c in cells:
        for n in neighbors4(c, W, H):
            if n in cellset and c < n and n not in adj[c] and rnd() < extra:
                adj[c].add(n)
                adj[n].add(c)
    return adj


def adj_to_json(adj):
    return {k: sorted(v) for k, v in adj.items()}


def gen_main(G, fl):
    for _ in range(200):
        m = try_gen_main(G, fl)
        if m:
            return m
    raise RuntimeError('地图生成失败')


def try_gen_main(G, fl):
    W, H, N = 5, 6, FLOORS[fl - 1]['rooms']
    start = key(2, H - 1)
    cells = grow_cells(W, H, N, start, {'up': 3, 'side': 2.2, 'down': 0.8})
    if len(cells) < N:
        return None
    if min(unkey(k)[1] for k in cells) > 1:
        return None
    adj = spanning(cells, start, W, H, 0.3)
    dist = bfs(adj, start)
    stairs, best = None, -1
    for c in cells:
        if c == start:
            continue
        x, y = unkey(c)
        if y > 1:
            continue
        s = dist[c] + (H - 1 - y) * 0.7 + rnd() * 0.8
        if s > best:
            best, stairs = s, c
    if not stairs or dist[stairs] < 4 or dist[stairs] > 8:
        return None
    lift = guard_r = None
    if 2 <= fl <= 5 and rnd() < 0.6:
        cands = sorted([c for c in cells if c != start and c != stairs and dist[c] >= 3], key=lambda c: -dist[c])
        for c in cands:
            ns = [n for n in sorted(adj[c]) if n != start and n != stairs]
            if not ns:
                continue
            g = pick(ns)
            adj2 = {k: set(v) for k, v in adj.items()}
            for n in list(adj2[c]):
                if n != g:
                    adj2[c].discard(n)
                    adj2[n].discard(c)
            if len(bfs(adj2, start)) != len(cells):
                continue
            if stairs not in bfs(adj2, start, {g}):
                continue
            adj, lift, guard_r = adj2, c, g
            break
        dist = bfs(adj, start)
    rooms = {}
    for c in cells:
        x, y = unkey(c)
        rooms[c] = {'id': c, 'x': x, 'y': y, 'type': 'empty', 'done': False, 'data': {}}
    rooms[start]['type'] = 'start'
    rooms[start]['done'] = True
    rooms[stairs]['type'] = 'stairs'
    if lift:
        rooms[lift]['type'] = 'lift'
        rooms[guard_r]['type'] = 'guard'
    free = [c for c in cells if rooms[c]['type'] == 'empty']
    R = len(free)
    R0 = R - 1  # 多出来的那一间给故事会
    want = ['shop' if fl % 2 == 1 else 'dshop']
    if fl >= 2 or rnd() < 0.6:
        want.append('rest')
    if fl >= 2 or rnd() < 0.5:
        want.append('elite')
    for _ in range(max(3, jsround(R0 * 0.32))):
        want.append('battle')
    for _ in range(max(2, jsround(R0 * 0.18))):
        want.append('event')
    if fl >= 2:
        want.append('ambush')
    if fl in (2, 4):
        want.append('agency')
    if 2 <= fl <= 5 and not G['holeUsed'] and rnd() < 0.45:
        want.append('hole')
    sp_pool = [['vent', 5], ['swap', 4], ['well', 2.5], ['wish', 2]]
    for _ in range(2 if R0 >= 11 else 1):
        want.append(wpick([e for e in sp_pool if e[0] not in want]))
    if fl >= 3 and rnd() < 0.45:
        want.append('dshop' if fl % 2 == 1 else 'shop')
    bag = want[:R0]
    bag.append('story')
    while len(bag) < R:
        bag.append(wpick([['story', 40], ['battle', 35], ['event', 15], ['empty', 10]]))
    order = shuffle(free[:])
    far = {'shop', 'dshop', 'rest', 'elite', 'agency', 'wish'}
    sorted_bag = sorted(bag, key=lambda t: 0 if t in far else 1)
    remaining = set(order)
    for t in sorted_bag:
        cell = None
        if t in far:
            cell = next((c for c in order if c in remaining and dist[c] >= 2), None)
        if cell is None:
            cell = next((c for c in order if c in remaining), None)
        remaining.discard(cell)
        rooms[cell]['type'] = t
    return {
        'kind': 'main', 'floor': fl, 'W': W, 'H': H, 'rooms': rooms, 'adj': adj_to_json(adj),
        'start': start, 'cur': start, 'time': 0, 'vis': {}, 'visited': {start: True}, 'revealed': {},
        'dream': None, 'firstMove': False,
    }


def gen_final(G):
    """最后一层：入口 → 两条路 → 安全的角落 → 前厅 → 梦魇。走廊都是横平竖直的。"""
    W, H = 5, 4
    layout = [(2, 3, 'start'), (1, 3, 'event'), (3, 3, 'battle'), (1, 2, 'shop'), (2, 2, 'rest'),
              (3, 2, 'story'), (2, 1, 'hall'), (2, 0, 'boss')]
    rooms = {}
    for x, y, t in layout:
        rooms[key(x, y)] = {'id': key(x, y), 'x': x, 'y': y, 'type': t, 'done': t == 'start', 'data': {}}
    edges = [('2,3', '1,3'), ('2,3', '3,3'), ('1,3', '1,2'), ('3,3', '3,2'), ('1,2', '2,2'), ('3,2', '2,2'),
             ('2,2', '2,1'), ('2,1', '2,0')]
    adj = {k: [] for k in rooms}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    for k in adj:
        adj[k].sort()
    return {'kind': 'final', 'floor': 6, 'W': W, 'H': H, 'rooms': rooms, 'adj': adj, 'start': '2,3', 'cur': '2,3',
            'time': 0, 'vis': {}, 'visited': {'2,3': True}, 'revealed': {}, 'dream': None, 'firstMove': False}


def gen_bonus(G, parent_floor):
    deep = parent_floor >= 4
    for _ in range(200):
        W, H, N = 4, 3, 7
        start = key(0, 1)
        cells = grow_cells(W, H, N, start, {'up': 1, 'side': 3, 'down': 1})
        if len(cells) < N:
            continue
        adj = spanning(cells, start, W, H, 0.35)
        rooms = {}
        for c in cells:
            x, y = unkey(c)
            rooms[c] = {'id': c, 'x': x, 'y': y, 'type': 'empty', 'done': False, 'data': {}}
        rooms[start]['type'] = 'start'
        rooms[start]['done'] = True
        bag = shuffle(['battle', 'battle', 'gift', 'gift', 'treasure', 'event' if deep else 'dshop'])
        i = 0
        for c in cells:
            if c != start:
                rooms[c]['type'] = bag[i]
                i += 1
        m = {'kind': 'bonus', 'floor': parent_floor, 'bonus': 'grave' if deep else 'cellar', 'W': W, 'H': H,
             'rooms': rooms, 'adj': adj_to_json(adj), 'start': start, 'cur': start, 'time': 4, 'vis': {},
             'visited': {start: True}, 'revealed': {}, 'dream': None, 'firstMove': True}
        fill_rooms(G, m, min(5, parent_floor + 1))
        for k in m['rooms']:
            m['vis'][k] = 3
        return m
    raise RuntimeError('兔子洞生成失败')


def fill_rooms(G, m, fl):
    """给房间填内容：敌人、事件、商品。"""
    from .events import EVENTS
    pool = POOL[clamp(fl, 1, 5)]
    last_e = None
    for k in m['rooms']:
        r = m['rooms'][k]
        t = r['type']
        if t in ('battle', 'ambush'):
            e = pick(pool)
            while e == last_e and len(pool) > 1:
                e = pick(pool)
            r['eid'] = e
            last_e = e
        if t in ('elite', 'guard'):
            r['eid'] = pick(ELITES)
        if t == 'nightmare':
            r['eid'] = 'lnm'
        if t == 'boss':
            r['eid'] = 'boss'
        if t == 'gift':
            r['eid'] = 'box'
        if t == 'event':
            all_ev = [e for e in EVENTS if not (m['kind'] == 'final' and EVENTS[e].get('noFinal'))]
            cand = [e for e in all_ev if e not in G['seenEvents']]
            if not cand:
                G['seenEvents'] = []
                cand = all_ev
            e = pick(cand)
            G['seenEvents'].append(e)
            r['data']['ev'] = e
            r['data']['roll'] = rnd()
        if t in ('shop', 'dshop'):
            r['data']['stock'] = gen_stock(G, t)
        if t == 'treasure':
            r['data']['relics'] = relic_choices(G, 2, 'UR' if m.get('bonus') == 'grave' else 'CUR')


def gen_stock(G, t):
    st = []

    def mk(kind, iid, hidden=False):
        return {'kind': kind, 'id': iid, 'price': base_price(kind, iid), 'sold': False, 'hidden': hidden}

    if t == 'shop':
        c1 = rand_card_id()
        c2 = rand_card_id()
        if c2 == c1:
            c2 = rand_card_id()
        st += [mk('card', c1), mk('card', c2), mk('candle', rand_candle_id())]
        st.append(mk('door', wpick([['wood', 5], ['spin', 3], ['gold', 1]])) if rnd() < 0.6 else mk('bell', 'bell'))
        r1 = rand_relic_id(G, 'CU')
        r2 = rand_relic_id(G, 'CUR', [r1] if r1 else [])
        if r1:
            st.append(mk('relic', r1))
        if r2:
            st.append(mk('relic', r2))
    else:
        used = []
        tries = 0
        while len(st) < 5 and tries < 50:
            tries += 1
            k = wpick([['card', 4], ['candle', 2.5], ['door', 1.5], ['relic', 1.5], ['bell', 0.6]])
            if k == 'card':
                it = mk('card', rand_card_id(), True)
            elif k == 'candle':
                it = mk('candle', rand_candle_id(), True)
            elif k == 'door':
                it = mk('door', wpick([['wood', 5], ['spin', 3], ['gold', 1.2]]), True)
            elif k == 'bell':
                it = mk('bell', 'bell', True)
            else:
                r = rand_relic_id(G, 'CUR', used)
                if not r:
                    continue
                used.append(r)
                it = mk('relic', r, True)
            it['price'] = jsround(it['price'] * 0.7)
            st.append(it)
    return st


# ================================================================ 楼层
def floor_info(G):
    from .data import BONUS
    m = G.get('map')
    if not m:
        return FLOORS[0]
    if m['kind'] == 'bonus':
        return BONUS[m['bonus']]
    return FLOORS[m['floor'] - 1]


def enter_floor(G, n, o):
    G['floor'] = n
    prev = G.get('map')
    m = gen_final(G) if n == 6 else gen_main(G, n)
    # 梦构
    if 3 <= n <= 5:
        keys = [k for k in DREAMS if k not in G['dreamsUsed']]
        m['dream'] = pick(keys)
        G['dreamsUsed'].append(m['dream'])
    elif n == 2 and rnd() < 0.35 and 'day' not in G['dreamsUsed']:
        m['dream'] = 'day'
        G['dreamsUsed'].append('day')
    if m['dream'] == 'night':
        bs = [r for r in m['rooms'].values() if r['type'] == 'battle']
        for r in shuffle(bs)[:int(math.ceil(len(bs) / 2))]:
            r['type'] = 'nightmare'
    fill_rooms(G, m, n)
    # 时长
    if m['kind'] == 'main':
        d = bfs(m['adj'], m['start'])
        stairs = next(r for r in m['rooms'].values() if r['type'] == 'stairs')
        t = d[stairs['id']] + FLOORS[n - 1]['slack']
        if has_relic(G, 'chain'):
            t += 1
        if m['dream'] == 'lucid':
            t -= 1
        if m['dream'] == 'lost':
            t += 2
        if o.get('how') == 'collapse':
            t -= 1
        t += o.get('carry', 0)
        m['time'] = max(1, t)
        m['baseTime'] = m['time']
    G['map'] = m
    G['stack'] = []
    G['litFloor'] = 0
    if prev and prev.get('dream') == 'lost' and o.get('how') != 'start':
        add_luc(G, 2)
        note(G, '你走出了迷失梦，脑袋清楚了一些：清醒 +2。', 'good')
    light = o.get('light', 0)
    if has_relic(G, 'bean'):
        light += 2
    if light > 0:
        reveal_random(G, light)
    if o.get('how') != 'start':
        if o.get('how') in ('stairs', 'lift') and heal(G, 1):
            note(G, '走下楼梯时，你喘了口气：回复 1 点血。')
        if has_relic(G, 'ginger') and heal(G, 1):
            note(G, '姜饼屋：回复 1 点血。')
        if has_relic(G, 'piggy'):
            add_coins(G, 12)
            note(G, '存钱小猪吐出 12 糖霜币。')
    update_vis(G)
    G['pending'] = {'type': 'floor'}
    G['screen'] = 'map'


def reveal_random(G, n):
    m = G['map']
    cand = shuffle([k for k in m['rooms'] if not m['revealed'].get(k) and not m['visited'].get(k)])
    for k in cand[:n]:
        m['revealed'][k] = True


def reveal_type(G, t):
    m = G['map']
    for k in m['rooms']:
        if m['rooms'][k]['type'] == t:
            m['revealed'][k] = True
            for n in m['adj'][k]:
                m['revealed'][n] = True
    update_vis(G)


# ================================================================ 视野
def radius_for(L):
    return [0, 0, 1, 2, 3, 4, 99, 99][L]


def manhattan(a, b):
    x1, y1 = unkey(a)
    x2, y2 = unkey(b)
    return abs(x1 - x2) + abs(y1 - y2)


def update_vis(G):
    """vis：0 = 完全看不见；1 = 知道有个房间，看不清；2 = 看得出凶还是静；3 = 看清是什么。"""
    m = G['map']
    L = G['luc']
    scope = 1 if has_relic(G, 'scope') else 0
    nb = set(m['adj'][m['cur']])
    for k in m['rooms']:
        if m['visited'].get(k) or m['revealed'].get(k) or m['dream'] == 'lucid' or m['kind'] != 'main':
            v = 3
        elif m['dream'] == 'lost':
            # 迷雾里只有故事会还亮着，免得信的碎片怎么也找不到
            v = 3 if m['rooms'][k]['type'] == 'story' else (1 if k in nb else 0)
        elif L <= 0:
            v = 1 if k in nb else 0
        elif L >= 6 or k in nb or manhattan(m['cur'], k) <= radius_for(L) + scope:
            v = 3
        else:
            v = 2
        m['vis'][k] = max(m['vis'].get(k, 0), v)


def looks_hostile(r):
    R = ROOMS[r['type']]
    return (R.get('looks') or R['cat']) == 'hostile'


# ================================================================ 移动
def cur_room(G):
    return G['map']['rooms'][G['map']['cur']]


def natural_cost(G, to):
    m = G['map']
    r = m['rooms'][to]
    if m['kind'] == 'final':
        return 0
    if r['type'] == 'vent':
        return 0
    return 2 if (r['type'] == 'nightmare' and not r['done']) else 1


def move_cost(G, to):
    m = G['map']
    c = natural_cost(G, to)
    if c == 0:
        return 0
    if G['flags'].get('freeMove'):
        return 0
    if has_relic(G, 'pumpkin') and not m['firstMove'] and m['kind'] == 'main':
        c = max(0, c - 1)
    return c


def can_move(G, to):
    m = G['map']
    if to not in m['adj'][m['cur']]:
        return {'ok': False, 'why': '这里和你所在的房间之间没有走廊'}
    if over_cap(G):
        return {'ok': False, 'why': '行李箱塞不下了，丢掉或用掉一件才能继续走'}
    cost = move_cost(G, to)
    if m['kind'] != 'final' and m['time'] < cost:
        return {'ok': False, 'why': '时长不够了', 'cost': cost}
    return {'ok': True, 'cost': cost}


def spend_time(G, n):
    if G['map']['kind'] == 'final' or n <= 0:
        return
    G['map']['time'] = max(0, G['map']['time'] - n)
    for _ in range(n):
        for c in G['lit']:
            if c['left'] <= 0:
                continue
            c['left'] -= 1
            if c['id'] == 'red':
                add_coins(G, 4)
            if c['id'] == 'long':
                add_coins(G, 1)
    for c in [c for c in G['lit'] if c['left'] <= 0]:
        snuff(G, c['u'], True)


def arrive(G, to, cost):
    m = G['map']
    spend_time(G, cost)
    m['firstMove'] = True
    m['cur'] = to
    if not m['visited'].get(to):
        m['visited'][to] = True
        G['stats']['rooms'] += 1
    update_vis(G)
    enter_room(G)


def do_move(G, to):
    c = can_move(G, to)
    if not c['ok']:
        return c
    if G['flags'].get('freeMove') and natural_cost(G, to) > 0:
        G['flags']['freeMove'] = False
    arrive(G, to, c['cost'])
    return {'ok': True}


def door_targets(G, it):
    """门能去的房间。只算你看得见的房间，不会泄露雾里藏着什么。"""
    m = G['map']
    cx, cy = unkey(m['cur'])
    out = []
    for k, r in m['rooms'].items():
        if k == m['cur']:
            continue
        v = m['vis'].get(k, 0)
        x, y = unkey(k)
        if it['id'] == 'wood' and max(abs(x - cx), abs(y - cy)) == 1 and v >= 1:
            out.append(k)
        if it['id'] == 'spin' and abs(x - cx) + abs(y - cy) <= 2:
            if v >= 3 and r['type'] in ('battle', 'ambush', 'elite', 'guard', 'nightmare') and not r['done']:
                out.append(k)
            elif v == 2 and looks_hostile(r):
                out.append(k)
        if it['id'] == 'gold' and v >= 3:
            out.append(k)
    return out


def vent_targets(G):
    m = G['map']
    return [k for k in m['rooms'] if k != m['cur'] and manhattan(k, m['cur']) <= 3 and m['vis'].get(k, 0) >= 1]


def use_door(G, u, to):
    it = next((x for x in G['luggage'] if str(x['u']) == str(u)), None)
    if not it or it['kind'] != 'door':
        return {'ok': False, 'why': '找不到这扇门'}
    if G['map']['kind'] != 'final' and G['map']['time'] < 1:
        return {'ok': False, 'why': '时长不够了'}
    if to not in door_targets(G, it):
        return {'ok': False, 'why': '这扇门到不了那里'}
    remove_item(G, u)
    if it['id'] == 'spin':
        G['flags']['spinBonus'] = to
    arrive(G, to, 1)
    return {'ok': True}


def use_vent(G, to):
    if G['map']['time'] < 2:
        return {'ok': False, 'why': '钻管道要 2 时长'}
    if to not in vent_targets(G):
        return {'ok': False, 'why': '管道通不到那里'}
    arrive(G, to, 2)
    return {'ok': True}


# ---------------------------------------------------------------- 蜡烛
def can_light(G):
    if len(G['lit']) >= 2:
        return '烛台上只能同时点两支蜡烛'
    if G['litFloor'] >= 2:
        return '这一层已经点过两次蜡烛了'
    return None


def light_candle(G, u):
    it = next((x for x in G['luggage'] if str(x['u']) == str(u)), None)
    if not it or it['kind'] != 'candle':
        return '那不是蜡烛'
    why = can_light(G)
    if why:
        return why
    remove_item(G, u)
    G['lit'].append({'u': it['u'], 'id': it['id'], 'left': CANDLES[it['id']]['max']})
    G['litFloor'] += 1
    return None


def snuff(G, u, burnt=False):
    i = next((i for i, c in enumerate(G['lit']) if str(c['u']) == str(u)), -1)
    if i < 0:
        return
    c = G['lit'].pop(i)
    name = CANDLES[c['id']]['name']
    what = ''
    if c['id'] == 'red':
        r = rand_relic_id(G, 'CUR')
        if r:
            gain_relic(G, r)
            what = '得到了「%s」' % RELICS[r]['name']
    if c['id'] == 'long':
        a, b = rand_card_id(), rand_card_id()
        add_item(G, 'card', a)
        add_item(G, 'card', b)
        what = '得到了「%s」和「%s」' % (CARDS[a]['name'], CARDS[b]['name'])
    if c['id'] in ('eerie', 'star'):
        add_luc(G, 1)
        what = '清醒 +1'
    note(G, '%s%s%s' % (name, '烧完了' if burnt else '熄灭了', '：' + what if what else '。'), 'good' if what else 'info')


def lit_has(G, cid):
    return any(c['id'] == cid for c in G['lit'])


# ================================================================ 进入房间
def battle_kind(t):
    return {'battle': 'normal', 'ambush': 'ambush', 'elite': 'elite', 'guard': 'guard',
            'nightmare': 'nightmare', 'boss': 'boss', 'gift': 'box'}[t]


EMPTY_TEXTS = ['房间里什么也没有，只有一把小椅子。', '地上有一圈灰尘的印子，像是这里曾经放过一个箱子。',
               '墙上的挂钩空着，挂钩下面写着一个名字，看不清了。', '空的。窗帘动了一下。']


def enter_room(G):
    r = cur_room(G)
    if r['done'] and not ROOMS[r['type']].get('perm'):
        after_room(G)
        return
    t = r['type']
    if t in ('battle', 'ambush', 'elite', 'guard', 'nightmare', 'boss', 'gift'):
        start_battle(G, r['eid'], battle_kind(t))
        return
    if t in ('empty', 'hall'):
        r['done'] = True
        note(G, '门后面就是雾气最浓的地方。' if t == 'hall' else pick(EMPTY_TEXTS))
        after_room(G)
        return
    if t == 'start':
        after_room(G)
        return
    G['pending'] = {'type': t}


def after_room(G):
    """房间结算完以后：检查这一层是不是坍塌、兔子洞的时间到了没有。"""
    m = G['map']
    if G['hp'] <= 0 or G.get('pending') or G.get('battle'):
        return
    if m['kind'] == 'bonus' and m['time'] <= 0:
        leave_bonus(G, '时间到了，兔子洞把你吐了出来。')
        return
    if m['kind'] == 'main' and m['time'] <= 0:
        t = cur_room(G)['type']
        if t in ('stairs', 'lift', 'well'):
            G['pending'] = {'type': t, 'forced': True}
        else:
            G['pending'] = {'type': 'collapse'}


def close_pending(G):
    p = G['pending']
    G['pending'] = None
    if p and p['type'] in ('event', 'rest', 'wish', 'swap', 'hole', 'treasure', 'reward', 'story'):
        r = cur_room(G)
        if not ROOMS[r['type']].get('perm'):
            r['done'] = True
    after_room(G)


def leave_bonus(G, msg=None):
    parent = G['stack'].pop()
    G['map'] = parent
    G['pending'] = None
    note(G, msg or '你从兔子洞里爬了出来。')
    update_vis(G)
    after_room(G)


def enter_hole(G):
    if G['luc'] < 1:
        return '清醒值不够'
    add_luc(G, -1)
    cur_room(G)['done'] = True
    G['holeUsed'] = True
    bonus = gen_bonus(G, G['floor'])
    G['stack'].append(G['map'])
    G['map'] = bonus
    G['pending'] = {'type': 'bonusIntro'}
    return None


def go_next_floor(G, how):
    m = G['map']
    carry = light = 0
    if how == 'stairs':
        light = m['time']
    if how == 'lift':
        carry = m['time']
    enter_floor(G, G['floor'] + 1, {'carry': carry, 'light': light, 'how': how})
    if how == 'lift':
        r = rand_relic_id(G, 'UR')
        if r:
            gain_relic(G, r)
            note(G, '电梯里放着「%s」，你收下了。' % RELICS[r]['name'], 'good')
        d = 'gold' if rnd() < 0.5 else 'spin'
        add_item(G, 'door', d)
        note(G, '还有一扇「%s」。' % DOORS[d]['name'], 'good')


# ================================================================ 战斗
# 牌：{'u': 编号, 'v': 点数}
# 牌堆：{'top': [已经固定在最上面的牌，按顺序], 'pool': [还没有顺序的牌], 'bottom': [塞到底下的牌，按顺序]}
def full_deck(two):
    return [v for _ in range(2 if two else 1) for v in range(1, 12)]


def total(s):
    return (s['down']['v'] if s['down'] else 0) + sum(c['v'] for c in s['up'])


def up_sum(s):
    return sum(c['v'] for c in s['up'])


def has_fx(s, fid):
    return any(f['id'] == fid for f in s['fx'])


def new_card(B, v):
    c = {'u': B['cu'], 'v': v}
    B['cu'] += 1
    return c


def new_deck(B):
    B['deck'] = {'top': [], 'pool': [new_card(B, v) for v in full_deck(B['two'])], 'bottom': []}


def deck_len(B):
    d = B['deck']
    return len(d['top']) + len(d['pool']) + len(d['bottom'])


def deck_cards(B):
    d = B['deck']
    return d['top'] + d['pool'] + d['bottom']


def draw_card(B):
    d = B['deck']
    if d['top']:
        return d['top'].pop(0)
    if d['pool']:
        return d['pool'].pop(int(math.floor(rnd() * len(d['pool']))))
    if d['bottom']:
        return d['bottom'].pop(0)
    return None


def commit_top(B, n):
    """把牌堆最上面的 n 张固定下来（被人看到了，就不能再变）。"""
    d = B['deck']
    while len(d['top']) < n and (d['pool'] or d['bottom']):
        if d['pool']:
            d['top'].append(d['pool'].pop(int(math.floor(rnd() * len(d['pool'])))))
        else:
            d['top'].append(d['bottom'].pop(0))
    return d['top'][:n]


def deck_top(B):
    t = commit_top(B, 1)
    return t[0] if t else None


def return_to_deck(B, c):
    """把一张牌放回牌堆的随机位置（不会放到你塞到底下的牌后面）。"""
    d = B['deck']
    nt, npool = len(d['top']), len(d['pool'])
    k = int(math.floor(rnd() * (nt + npool + 1)))
    if k < nt:
        d['top'].insert(k, c)
    else:
        d['pool'].append(c)


def take_from_deck(B, pred):
    """从牌堆里拿出一张满足条件的牌（魔法棒用）。"""
    d = B['deck']
    for name, rng in (('bottom', range(len(d['bottom']) - 1, -1, -1)), ('pool', range(len(d['pool']))),
                      ('top', range(len(d['top']) - 1, -1, -1))):
        lst = d[name]
        for i in rng:
            if pred(lst[i]):
                return lst.pop(i)
    return None


def remove_from_deck(B, u):
    d = B['deck']
    for name in ('top', 'pool', 'bottom'):
        for i, c in enumerate(d[name]):
            if c['u'] == u:
                return d[name].pop(i)
    return None


def enemy_hp(eid, fl):
    return ENEMIES[eid]['hp'][clamp(fl, 1, 5) - 1]


def temp_card(B, cid=None):
    c = {'u': 'T%d' % B['cu'], 'kind': 'card', 'id': cid or rand_card_id(), 'temp': True}
    B['cu'] += 1
    return c


def start_battle(G, eid, kind, opts=None):
    opts = opts or {}
    m = G['map']
    fl = G['floor']
    if m['kind'] == 'bonus':
        fl = min(5, fl + 1)
    hp = opts.get('hp') or enemy_hp(eid, fl)
    if kind not in ('boss', 'echo'):
        if lit_has(G, 'red'):
            hp = max(1, hp - 1)
        if lit_has(G, 'eerie'):
            hp += 1
        if m.get('dream') == 'day':
            hp = max(1, hp - 1)
        if has_relic(G, 'silver') and kind in ('elite', 'guard'):
            hp = max(1, hp - 1)
    if G['depth'] == 'night' and kind != 'echo' and eid != 'box':
        hp += 1
    dream = m.get('dream')
    B = {
        'eid': eid, 'kind': kind, 'foeHp': hp, 'foeMax': hp, 'round': 0, 'cu': 1, 'ft': 1,
        'two': dream == 'repeat', 'chase': dream == 'chase', 'prophecy': dream == 'prophecy',
        'lock': 2 if dream == 'lock' else 0, 'repeat': dream == 'repeat',
        'deck': None, 'you': None, 'foe': None, 'target': 21, 'passes': 0, 'turn': 'you', 'phase': 'play',
        'p': {}, 'hand': [], 'pile': [], 'used': [], 'skill': {}, 'bonus': {}, 'res': None, 'end': None,
        'msgs': [], 'dirty': False, 'youHit': False, 'acts': 0,
        'timer': 4 if (kind == 'nightmare' or eid == 'box') else 0,
        'gift': {'r': 2} if eid == 'box' else None,
        'noBag': kind == 'echo', 'stealIdx': opts.get('stealIdx'),
        'peek': [], 'buried': [], 'pounce': False, 'revived': False, 'drew': [],
    }
    p = B['p']
    if eid == 'car':
        p['speed'] = 1
    if eid == 'candy':
        p['candies'] = 3
    if eid == 'guard':
        p['scis'] = 2
    if eid == 'doll':
        p['watches'] = 2
    if eid == 'bot':
        p['parts'] = 2
    if eid == 'puppet':
        p['mirrors'] = 2
    if eid in ('magician', 'merchant'):
        p['hand'] = []
    if eid == 'gpt':
        p['pitch'] = 1
    if eid == 'gemini':
        p['verdicts'] = 2
    if eid == 'box':
        B['foeHp'] = B['foeMax'] = 2
    if not B['noBag']:
        B['pile'] = shuffle([{'u': c['u'], 'kind': 'card', 'id': c['id']} for c in G['cards']])
        if has_relic(G, 'mark'):
            c = temp_card(B)
            B['hand'].append(c)
            B.setdefault('tempGot', []).append(['魔法书签', c['id']])
        if lit_has(G, 'mint'):
            c = temp_card(B)
            B['hand'].append(c)
            B.setdefault('tempGot', []).append(['薄荷蜡烛', c['id']])
    for pal in G['pals']:
        B['skill'][pal['id']] = 0
    if G['flags'].get('doujiBonus'):
        B['bonus']['douji'] = G['flags'].pop('doujiBonus')
    G['battle'] = B
    G['screen'] = 'battle'
    G['stats']['fights'] += 1
    start_round(G, B)
    return B


def draw_trump(B):
    if len(B['hand']) >= HAND_MAX:
        return None
    if not B['pile']:
        if not B['used']:
            return None
        B['pile'] = shuffle(B['used'])
        B['used'] = []
    c = B['pile'].pop()
    B['hand'].append(c)
    return c


def add_fx(B, owner, fid, label, v=None):
    f = {'id': fid, 'label': label, 'v': v, 't': B['ft'], 'owner': owner}
    B['ft'] += 1
    B[owner]['fx'].append(f)
    return f


def recalc_target(B):
    best = None
    for f in B['you']['fx'] + B['foe']['fx']:
        if f['id'] == 'gate' and (best is None or f['t'] > best['t']):
            best = f
    B['target'] = best['v'] if best else 21


def start_round(G, B):
    B['round'] += 1
    B['you'] = {'down': None, 'up': [], 'fx': []}
    B['foe'] = {'down': None, 'up': [], 'fx': []}
    new_deck(B)
    B['you']['down'] = draw_card(B)
    B['foe']['down'] = draw_card(B)
    B['you']['up'].append(draw_card(B))
    B['foe']['up'].append(draw_card(B))
    B['passes'] = 0
    B['phase'] = 'play'
    B['turn'] = 'foe' if B['chase'] else 'you'
    B['res'] = None
    B['dirty'] = False
    B['youHit'] = False
    B['acts'] = 0
    B['target'] = 21
    B['msgs'] = []
    B['p']['candyUsed'] = False
    B['peek'] = []
    B['buried'] = []
    B['pounce'] = False
    B['drew'] = []
    if not B['noBag']:
        for _ in range(2 if B['round'] == 1 else 1):
            c = draw_trump(B)
            if c:
                B['drew'].append(c)
    trait_round_start(G, B)
    if has_relic(G, 'cocoa') and B['round'] > 1 and (B['round'] - 1) % 2 == 0 and heal(G, 1):
        B['msgs'].append('热可可暖暖的：回复 1 点血。')


def trait_round_start(G, B):
    p = B['p']
    eid = B['eid']
    if eid == 'car':
        if p['speed'] > 1:
            add_fx(B, 'foe', 'speed', '车速 %d：它赢了你掉 %d 血' % (p['speed'], p['speed']), p['speed'])
    elif eid == 'sling':
        if B['round'] % 3 == 0:
            add_fx(B, 'foe', 'charge', '蓄满力：它赢了你掉 2 血')
            B['msgs'].append('皮筋绷得紧紧的。')
    elif eid == 'watcher':
        add_fx(B, 'foe', 'eye', '它看得见你的暗牌')
    elif eid == 'bot':
        if B['round'] > 1 and (B['round'] - 1) % 3 == 0 and p['parts'] > 0 and B['foeHp'] < B['foeMax']:
            B['foeHp'] += 1
            p['parts'] -= 1
            B['msgs'].append('维护机拧了拧螺丝，修好 1 点血。')
    elif eid == 'magician':
        # 魔术师袖子里最多藏 2 张，每局都换一张新的，不让牌在袖子里睡大觉
        swapped = len(p['hand']) >= 2
        if swapped:
            p['hand'].pop(0)
        c = pick(['candy', 'candy', 'umb', 'umb', 'gate17', 'gate24', 'watch', 'watch', 'wand', 'wand'])
        p['hand'].append('wand%d' % ri(2, 6) if c == 'wand' else c)
        B['msgs'].append('礼帽魔术师把一张没用上的牌塞回帽子，又变出一张新的，藏进了袖子里。' if swapped
                         else '礼帽魔术师从帽子里变出一张牌，藏进了袖子里。')
    elif eid == 'merchant':
        if not p['hand']:
            c = pick(['candy', 'umb', 'umb', 'gate17', 'gate24', 'watch', 'watch', 'wand', 'wand'])
            p['hand'].append('wand%d' % ri(2, 6) if c == 'wand' else c)
            B['msgs'].append('诡异行商从货箱里摸出一张牌，藏进了袖子里。')
    elif eid == 'boss':
        half = B['foeHp'] <= B['foeMax'] // 2
        T = wpick([[17, 1], [21, 0.6 if half else 1], [24, 1]])
        if T != 21:
            add_fx(B, 'foe', 'gate', '梦魇把目标改成了 %d' % T, T)
            recalc_target(B)
            B['msgs'].append('雾里有个声音低低地说：这一局的目标是 %d。' % T)
        if half:
            add_fx(B, 'foe', 'rage', '梦魇贴近了：它赢了你多掉 1 血')
    if B['chase'] and B['round'] >= 4:
        add_fx(B, 'foe', 'chase', '追逐梦：它赢了你多掉 1 血')


# ---------------------------------------------------------------- 你的操作
def can_hit(G, B):
    if B['phase'] != 'play' or B['turn'] != 'you':
        return {'ok': False, 'why': '现在不是你的回合'}
    if deck_len(B) == 0:
        return {'ok': False, 'why': '牌堆空了，只能停牌'}
    if has_fx(B['foe'], 'lull'):
        return {'ok': False, 'why': '对方的安眠曲让你没法要牌'}
    return {'ok': True}


def can_stand(G, B):
    if B['phase'] != 'play' or B['turn'] != 'you':
        return {'ok': False, 'why': '现在不是你的回合'}
    if has_relic(G, 'rshoes') and not B['youHit'] and can_hit(G, B)['ok']:
        return {'ok': False, 'why': '红舞鞋停不下来：这一局先要一张牌，才能停牌'}
    return {'ok': True}


def you_hit(G, B):
    c = draw_card(B)
    B['you']['up'].append(c)
    B['passes'] = 0
    B['youHit'] = True
    B['dirty'] = True
    B['acts'] += 1
    B['turn'] = 'foe'
    return c


def you_stand(G, B):
    B['passes'] += 1
    B['acts'] += 1
    B['turn'] = 'foe'
    if B['passes'] >= 2:
        B['phase'] = 'reveal'


def locked_now(B):
    return bool(B['lock']) and B['round'] <= B['lock']


def card_usable(G, B, it):
    if B['phase'] != 'play' or B['turn'] != 'you':
        return '等轮到你的时候再用'
    if B['noBag']:
        return '梦中梦里，行李箱打不开'
    if locked_now(B):
        return '锁魂梦：前两局用不了王牌'
    y, f = B['you'], B['foe']
    cid = it['id']
    if cid == 'watch' and not y['up']:
        return '你没有明牌可以放回去'
    if cid == 'mirror' and (not y['up'] or not f['up']):
        return '双方都得有明牌才能换'
    if cid == 'scis' and not last_fx(f):
        return '对方现在没有可以剪的效果'
    if cid == 'lull' and has_fx(y, 'lull'):
        return '已经在唱了'
    if (cid.startswith('wand') or cid == 'gwand') and deck_len(B) == 0:
        return '牌堆空了'
    return None


def last_fx(side):
    best = None
    for f in side['fx']:
        if best is None or f['t'] > best['t']:
            best = f
    return best


def cut_fx(G, B, owner, f):
    side = B[owner]
    side['fx'] = [x for x in side['fx'] if x is not f]
    if f['id'] == 'gate':
        recalc_target(B)
    if f['id'] == 'speed':
        B['p']['speed'] = 1
    return f


def guard_react(G, B, f):
    if B['eid'] != 'guard' or not B['p'].get('scis'):
        return None
    if f['id'] not in ('candy', 'bcandy', 'umb', 'bumb', 'gate', 'lull', 'tin'):
        return None
    B['p']['scis'] -= 1
    cut_fx(G, B, 'you', f)
    return '剪刀卫兵咔嚓一声，把它剪掉了。'


def play_card(G, B, it):
    why = card_usable(G, B, it)
    if why:
        return {'ok': False, 'why': why}
    C = CARDS[it['id']]
    y, f = B['you'], B['foe']
    out = {'ok': True, 'msg': ''}
    fx = None
    cid = it['id']
    if cid.startswith('wand'):
        n = C['n']
        c = take_from_deck(B, lambda c: c['v'] == n)
        if not c:
            out['msg'] = '牌堆里没有 %d，魔法棒落空了。' % n
        else:
            y['up'].append(c)
            out['msg'] = '魔法棒点出了 %d。' % n
            B['dirty'] = True
    elif cid == 'gwand':
        my = total(y)
        best = None
        for c in deck_cards(B):
            if my + c['v'] <= B['target'] and (best is None or c['v'] > best['v']):
                best = c
        if not best:
            out['msg'] = '没有不会让你爆的牌，金魔法棒落空了。'
        else:
            remove_from_deck(B, best['u'])
            y['up'].append(best)
            out['msg'] = '金魔法棒点出了 %d。' % best['v']
            B['dirty'] = True
    elif cid == 'watch':
        c = y['up'].pop()
        return_to_deck(B, c)
        out['msg'] = '你把 %d 放回了牌堆。' % c['v']
        B['dirty'] = True
    elif cid == 'mirror':
        a, b = y['up'].pop(), f['up'].pop()
        y['up'].append(b)
        f['up'].append(a)
        out['msg'] = '你用 %d 换走了对方的 %d。' % (a['v'], b['v'])
        B['dirty'] = True
    elif cid == 'candy':
        fx = add_fx(B, 'you', 'candy', '糖果罐：对方输了多掉 1 血')
    elif cid == 'bcandy':
        fx = add_fx(B, 'you', 'bcandy', '大糖果罐：对方输了多掉 2 血')
    elif cid == 'umb':
        fx = add_fx(B, 'you', 'umb', '小雨伞：你输了少掉 1 血')
    elif cid == 'bumb':
        fx = add_fx(B, 'you', 'bumb', '大雨伞：你输了不掉血')
    elif cid in ('gate17', 'gate24'):
        fx = add_fx(B, 'you', 'gate', '星星门：目标 %d' % C['n'], C['n'])
        recalc_target(B)
        out['msg'] = '这一局的目标变成了 %d。' % C['n']
    elif cid == 'scis':
        t = last_fx(f)
        cut_fx(G, B, 'foe', t)
        out['msg'] = '剪掉了「%s」。' % t['label'].split('：')[0]
    elif cid == 'lull':
        fx = add_fx(B, 'you', 'lull', '安眠曲：对方这一局不能再要牌')
        out['msg'] = '对方打了个哈欠。'
    elif cid == 'gift':
        a = rand_card_id()
        while a == 'gift':
            a = rand_card_id()
        b = rand_card_id()
        while b == 'gift':
            b = rand_card_id()
        B['hand'].append(temp_card(B, a))
        B['hand'].append(temp_card(B, b))
        out['msg'] = '礼物里是「%s」和「%s」（临时王牌）。' % (CARDS[a]['name'], CARDS[b]['name'])
    B['hand'] = [x for x in B['hand'] if str(x['u']) != str(it['u'])]
    if not it.get('temp'):
        B['used'].append(it)
    if fx:
        r = guard_react(G, B, fx)
        if r:
            out['msg'] = r
            out['guarded'] = True
    return out


def pal_uses(G, pal, B=None):
    n = PALS[pal['id']]['uses'][pal['lv'] - 1] + (1 if has_relic(G, 'key') else 0)
    if B:
        n += B.get('bonus', {}).get(pal['id'], 0)
    return n


def pal_left(G, B, pal):
    return pal_uses(G, pal, B) - B['skill'].get(pal['id'], 0)


def skill_usable(G, B, pal, move=None):
    if B['phase'] != 'play' or B['turn'] != 'you':
        return '等轮到你的时候再用'
    pid = pal['id']
    always = PALS[pid].get('always')
    if B['noBag'] and not always:
        return '梦中梦里，伙伴叫不醒'
    if locked_now(B) and not always:
        return '锁魂梦：前两局用不了伙伴技能'
    if pal_left(G, B, pal) <= 0:
        return '这一场已经用完了'
    if pid == 'douji':
        if move not in DOUJI_MOVES:
            return '要说清楚用哪一招：飞扑、护主、啄牌'
        if move == 'guard' and has_fx(B['you'], 'dguard'):
            return '斗鸡已经挡在你前面了'
        if move == 'peck' and not B['foe']['up']:
            return '对方没有明牌可以叼'
    if pid == 'tin' and has_fx(B['you'], 'tin'):
        return '锡兵已经挡在你前面了'
    if pid == 'bear' and G['hp'] >= G['maxHp']:
        return '你现在血是满的'
    if pid == 'rabbit' and (B['dirty'] or B['acts'] > 0):
        return '这一局已经动过牌了'
    if pid == 'ballet' and deck_len(B) == 0:
        return '牌堆空了'
    return None


def use_skill(G, B, pal, move=None):
    why = skill_usable(G, B, pal, move)
    if why:
        return {'ok': False, 'why': why}
    pid = pal['id']
    B['skill'][pid] = B['skill'].get(pid, 0) + 1
    out = {'ok': True, 'msg': '', 'pid': pid, 'move': move}
    if pid == 'douji':
        if move == 'pounce':
            B['pounce'] = True
            B['phase'] = 'reveal'
            out['pounce'] = True
        elif move == 'guard':
            add_fx(B, 'you', 'dguard', '斗鸡护主：你输了不掉血，对方赢了会被反啄 1 点血')
            if B['eid'] == 'guard' and B['p'].get('scis', 0) > 0:
                out['blocked'] = '剪刀卫兵的剪刀咔嚓一下伸过来，被斗鸡一翅膀扇开了。'
        elif move == 'peck':
            c = B['foe']['up'].pop()
            return_to_deck(B, c)
            B['dirty'] = True
            out['card'] = c
    elif pid == 'tin':
        f = add_fx(B, 'you', 'tin', '锡兵：这一局你输了不掉血')
        out['msg'] = '锡兵挡在了你前面。'
        r = guard_react(G, B, f)
        if r:
            out['msg'] = r
    elif pid == 'bear':
        n = heal(G, 2 if pal['lv'] > 1 else 1)
        out['msg'] = '布偶熊抱了抱你：回复 %d 点血。' % n
    elif pid == 'ballet':
        n = 2 if pal['lv'] > 1 else 1
        cards = commit_top(B, n)
        B['peek'] = [c['u'] for c in cards]
        out['peek'] = [{'u': c['u'], 'v': c['v']} for c in cards]
        out['msg'] = '芭蕾娃娃踮起脚，看了看牌堆顶。'
    elif pid == 'rabbit':
        new_deck(B)
        B['you']['down'] = draw_card(B)
        B['foe']['down'] = draw_card(B)
        B['you']['up'] = [draw_card(B)]
        B['foe']['up'] = [draw_card(B)]
        B['peek'] = []
        B['buried'] = []
        out['msg'] = '发条兔把牌全部收了回去，重新发了一遍。'
        out['redeal'] = True
    return out


def known_buried(B):
    """你塞到牌堆底下、现在还在牌堆里的牌。"""
    ids = set(B.get('buried') or [])
    return [c for c in B['deck']['bottom'] if c['u'] in ids]


def known_top(B):
    """玩家知道的牌堆顶的牌：[(位置, 牌)]。只有预言梦翻开的、芭蕾娃娃看过的才算。"""
    if deck_len(B) == 0:
        return []
    if B['prophecy']:
        deck_top(B)
    out = []
    for i, c in enumerate(B['deck']['top']):
        if (i == 0 and B['prophecy']) or c['u'] in (B.get('peek') or []):
            out.append((i, c))
    return out


def bury_card(B, u):
    d = B['deck']
    for i, c in enumerate(d['top']):
        if c['u'] == u:
            d['top'].pop(i)
            d['bottom'].append(c)
            B.setdefault('buried', []).append(u)
            return True
    return False


# ---------------------------------------------------------------- 对方的回合
def unknown_for(B, side, peek_opp):
    me = B[side]
    op = B['foe' if side == 'you' else 'you']
    seen = [me['down']['v']] + [c['v'] for c in me['up']] + [c['v'] for c in op['up']]
    if peek_opp:
        seen.append(op['down']['v'])
    pool = full_deck(B['two'])
    for v in seen:
        if v in pool:
            pool.remove(v)
    return pool


def foe_knows_you(B):
    return has_fx(B['foe'], 'eye')


def foe_wants_hit(G, B):
    T = B['target']
    f, y = B['foe'], B['you']
    E = ENEMIES[B['eid']]
    if deck_len(B) == 0 or has_fx(y, 'lull'):
        return False
    my = total(f)
    if my >= T:
        return False
    if B['prophecy']:
        nx = deck_top(B)['v']
        if my + nx > T:
            return False
        if B['passes'] == 1:
            eye = foe_knows_you(B)
            yt = total(y) if eye else up_sum(y) + avg(unknown_for(B, 'foe', False))
            if my > yt + 0.5 and (total(y) <= T if eye else True):
                return False
        return True
    eye = foe_knows_you(B)
    unk = unknown_for(B, 'foe', eye)
    if not unk:
        return False
    safe = sum(1 for v in unk if my + v <= T)
    p_bust = 1 - safe / len(unk)
    if E['ai'] == 'dealer':
        h = my < T - (21 - E['stand'])
        if p_bust >= 1:
            h = False
        if rnd() < 0.05:
            h = not h
        return h
    risk = E['risk']
    yv = up_sum(y)
    you_stood = B['passes'] == 1
    if eye:
        yt = yv + y['down']['v']
        if you_stood:
            if yt > T:
                return False
            if my > yt:
                return False
            if my == yt:
                return p_bust < 0.3
            return p_bust < 1
        if my >= T - 3 and my >= yt:
            return False
        return p_bust <= risk + (0.2 if my < yt else 0)
    if p_bust == 0:
        return True
    your_est = yv + avg(unk)
    if you_stood:
        if my > your_est + 1:
            return False
        if my >= your_est - 1:
            return p_bust < risk
        return p_bust < risk + 0.25
    if my >= T - 3:
        return False
    return p_bust <= risk


def foe_turn(G, B):
    acts = []
    trait_foe_turn(G, B, acts)
    if B['phase'] != 'play':
        return acts
    if foe_wants_hit(G, B):
        c = draw_card(B)
        B['foe']['up'].append(c)
        B['passes'] = 0
        B['dirty'] = True
        acts.append({'t': 'foeHit', 'c': c})
    else:
        B['passes'] += 1
        acts.append({'t': 'foeStand'})
    B['acts'] += 1
    B['turn'] = 'you'
    if B['passes'] >= 2:
        B['phase'] = 'reveal'
    return acts


def trait_foe_turn(G, B, acts):
    p = B['p']
    T = B['target']
    f, y = B['foe'], B['you']
    eid = B['eid']
    if eid == 'candy':
        if p['candies'] > 0 and not p['candyUsed'] and deck_len(B):
            est = up_sum(y) + avg(unknown_for(B, 'foe', False))
            if est >= T - 4 or (B['passes'] == 1 and est >= T - 6):
                c = draw_card(B)
                y['up'].append(c)
                p['candies'] -= 1
                p['candyUsed'] = True
                B['passes'] = 0
                B['dirty'] = True
                acts.append({'t': 'forceYou', 'c': c, 'msg': '糖果机咔哒一声，往你手里硬塞了一张牌：%d。' % c['v']})
    elif eid == 'doll':
        if total(f) > T and p['watches'] > 0 and f['up']:
            c = f['up'].pop()
            return_to_deck(B, c)
            p['watches'] -= 1
            B['passes'] = 0
            B['dirty'] = True
            acts.append({'t': 'foeReturn', 'c': c, 'msg': '瓷娃娃拨了拨怀表，把她最后一张明牌 %d 放回了牌堆。' % c['v']})
    elif eid == 'puppet':
        if p['mirrors'] > 0 and f['up'] and y['up']:
            a, b = last(f['up']), last(y['up'])
            m1 = total(f)
            m2 = m1 - a['v'] + b['v']
            if (m1 > T and m2 <= T) or (m2 <= T and m2 - m1 >= 3):
                f['up'].pop()
                y['up'].pop()
                f['up'].append(b)
                y['up'].append(a)
                p['mirrors'] -= 1
                B['passes'] = 0
                B['dirty'] = True
                acts.append({'t': 'swap', 'a': a, 'b': b,
                             'msg': '提线木偶扯了扯线：它的 %d 和你的 %d 换了位置。' % (a['v'], b['v'])})
    elif eid in ('magician', 'merchant'):
        magician_play(G, B, acts)


def magician_play(G, B, acts):
    p = B['p']
    f = B['foe']
    who = ENEMIES[B['eid']]['name']
    # 魔术师出手的条件更宽松一些
    loose = B['eid'] == 'magician'
    for _ in range(2):
        used = False
        i = 0
        while i < len(p['hand']) and not used:
            c = p['hand'][i]
            my = total(f)
            T = B['target']
            ok = False
            if c == 'watch' and my > T and f['up']:
                x = f['up'].pop()
                return_to_deck(B, x)
                acts.append({'t': 'foeReturn', 'c': x, 'msg': '%s用了「怀表」，把 %d 放回了牌堆。' % (who, x['v'])})
                ok = True
            elif c.startswith('wand'):
                n = int(c[4:])
                if my + n <= T and my + n >= T - (6 if loose else 4):
                    x = take_from_deck(B, lambda cc: cc['v'] == n)
                    if x:
                        f['up'].append(x)
                        acts.append({'t': 'foeHit', 'c': x, 'msg': '%s用「魔法棒」点出了 %d。' % (who, n)})
                        ok = True
            elif c == 'gate17' and 14 <= my <= 17 and T != 17:
                add_fx(B, 'foe', 'gate', '%s：目标 17' % who, 17)
                recalc_target(B)
                acts.append({'t': 'fx', 'msg': '%s用了「星星门·17」：这一局的目标变成 17。' % who})
                ok = True
            elif c == 'gate24' and 21 < my <= 24 and T != 24:
                add_fx(B, 'foe', 'gate', '%s：目标 24' % who, 24)
                recalc_target(B)
                acts.append({'t': 'fx', 'msg': '%s用了「星星门·24」：这一局的目标变成 24。' % who})
                ok = True
            elif c == 'candy' and T - (4 if loose else 2) <= my <= T and not has_fx(f, 'candy'):
                add_fx(B, 'foe', 'candy', '%s的糖果罐：你输了多掉 1 血' % who)
                acts.append({'t': 'fx', 'msg': '%s用了「糖果罐」：这一局你输了多掉 1 血。' % who})
                ok = True
            elif c == 'umb' and (my > T or (loose and my < T - 6)) and not has_fx(f, 'umb'):
                add_fx(B, 'foe', 'umb', '%s的小雨伞：它输了少掉 1 血' % who)
                acts.append({'t': 'fx', 'msg': '%s撑开了「小雨伞」：这一局它输了少掉 1 血。' % who})
                ok = True
            if ok:
                p['hand'].pop(i)
                used = True
                B['passes'] = 0
                B['dirty'] = True
            i += 1
        if not used:
            break


# ---------------------------------------------------------------- 结算
def outcome_of(ty, tf, T):
    if ty <= T and tf <= T:
        return 'win' if ty > tf else ('lose' if ty < tf else 'tie')
    if ty <= T:
        return 'win'
    if tf <= T:
        return 'lose'
    return 'win' if ty < tf else ('lose' if ty > tf else 'tie')


def dmg_to_you(G, B):
    if B['eid'] == 'box':
        return 0
    d = 1
    for x in B['foe']['fx']:
        if x['id'] == 'speed':
            d += x['v'] - 1
        if x['id'] == 'charge':
            d += 1
        if x['id'] in ('rage', 'chase', 'candy'):
            d += 1
        if x['id'] == 'bcandy':
            d += 2
    for x in B['you']['fx']:
        if x['id'] == 'umb':
            d -= 1
        if x['id'] in ('bumb', 'tin', 'dguard'):
            return 0
    return max(0, d)


def dmg_to_foe(G, B):
    d = 1 + (1 if has_relic(G, 'clip') else 0) + (1 if has_relic(G, 'rshoes') else 0)
    for x in B['you']['fx']:
        if x['id'] == 'candy':
            d += 1
        if x['id'] == 'bcandy':
            d += 2
    for x in B['foe']['fx']:
        if x['id'] == 'umb':
            d -= 1
        if x['id'] == 'bumb':
            return 0
    return max(0, d)


def resolve_round(G, B):
    T = B['target']
    ty, tf = total(B['you']), total(B['foe'])
    o = 'win' if B['pounce'] else outcome_of(ty, tf, T)
    res = {'o': o, 'ty': ty, 'tf': tf, 'T': T, 'dmg': 0, 'notes': [], 'pounce': B['pounce'], 'counter': 0}
    name = ENEMIES[B['eid']]['name']
    if o == 'win':
        d = dmg_to_foe(G, B) + (1 if B['pounce'] else 0)
        res['dmg'] = d
        B['foeHp'] = max(0, B['foeHp'] - d)
        if B['gift'] and B['gift']['r'] > 0:
            B['gift']['r'] -= 1
            if B['gift']['r'] == 0:
                res['notes'].append('丝带散开了。')
    elif o == 'lose':
        d = dmg_to_you(G, B)
        res['dmg'] = d
        if d > 0:
            hurt(G, d)
        if has_fx(B['you'], 'dguard') and B['eid'] != 'box':
            B['foeHp'] = max(0, B['foeHp'] - 1)
            res['counter'] = 1
            res['notes'].append('斗鸡从翅膀底下冲出去，狠狠反啄了%s一口：它掉了 1 点血。' % name)
        if lit_has(G, 'scent'):
            G['coins'] = max(0, G['coins'] - 5)
            res['notes'].append('香氛蜡烛：扣了 5 糖霜币。')
    elif has_relic(G, 'ribbon') and heal(G, 1):
        res['notes'].append('蝴蝶结丝带：回复 1 点血。')
    if B['pounce'] and heal(G, 1):
        res['notes'].append('斗鸡跳回你肩上，用脑袋蹭了蹭你的脸：回复 1 点血。')
    if B['eid'] == 'gpt' and o == 'lose' and B['p'].get('pitch', 0) > 0:
        B['p']['pitch'] -= 1
        j = add_junk(G, pick(JUNK_BY['gpt']))
        if j['full']:
            res['notes'].append('GPT 推销员想塞纪念品，可你的行李箱里纪念品已经太多了。它顺手拿走了 %d 糖霜币。' % j['lost'])
        else:
            res['notes'].append('GPT 推销员往你的行李箱里硬塞了「%s」。' % j['name'])
    if B['eid'] == 'gemini' and not B['pounce'] and B['p'].get('verdicts', 0) > 0 and ty <= T - 5:
        B['p']['verdicts'] -= 1
        j = add_junk(G, pick(JUNK_BY['gemini']))
        if j['full']:
            res['notes'].append('Gemini 评委判你「不够高效」，罚了你 %d 糖霜币。' % j['lost'])
        else:
            res['notes'].append('Gemini 评委判你「不够高效」，往你的行李箱里塞了「%s」。' % j['name'])
    if B['eid'] == 'car':
        B['p']['speed'] = 1 if o == 'lose' else min(3, B['p']['speed'] + 1)
    res['foeLeft'] = B['foeHp']  # 先记下来：重复梦里敌人可能马上又站起来
    B['res'] = res
    B['phase'] = 'result'
    B['end'] = check_end(G, B, res)
    return res


def check_end(G, B, res):
    if G['hp'] <= 0:
        return 'lost'
    if B['eid'] == 'box':
        if B['gift']['r'] <= 0:
            return 'won'
        if B['round'] >= B['timer']:
            return 'boxfail'
        return None
    if B['foeHp'] <= 0:
        if B['repeat'] and not B['revived'] and B['kind'] != 'boss' and rnd() < 0.3:
            B['foeHp'] = 1
            B['revived'] = True
            res['notes'].append('%s又站了起来。' % ENEMIES[B['eid']]['name'])
            return None
        return 'won'
    if B['kind'] == 'echo':
        return None if res['o'] == 'tie' else 'echoDone'
    if B['timer'] and B['round'] >= B['timer']:
        return 'escaped'
    return None


# ---------------------------------------------------------------- 战斗结束
def battle_rewards(G, B):
    fl = G['floor']
    k = B['kind']
    rw = {'coins': 0, 'choices': [], 'relics': [], 'notes': []}
    base = 0
    if k in ('normal', 'ambush'):
        base = 7 + 2 * fl + ri(0, 3) + (4 if k == 'ambush' else 0)
    elif k in ('elite', 'guard'):
        base = 14 + 3 * fl + ri(0, 4)
    elif k == 'nightmare':
        base = 9 + 2 * fl
    elif k == 'event':
        base = 6 + 2 * fl
    elif k == 'merchant':
        base = 10
    mult = 1.0
    if lit_has(G, 'scent'):
        mult *= 2.5
    if lit_has(G, 'eerie'):
        mult *= 1.6
    if G['map'].get('dream') == 'day':
        mult *= 1.25
    coins = jsround(base * mult)
    if has_relic(G, 'jar') and base > 0:
        coins += 6
    if coins > 0:
        rw['coins'] = add_coins(G, coins, True)
    if k in ('normal', 'ambush', 'nightmare'):
        n = 3 + (1 if has_relic(G, 'clover') else 0)
        ids = []
        for _ in range(n):
            cid = rand_card_id()
            g = 0
            while cid in ids and g < 20:
                cid = rand_card_id()
                g += 1
            ids.append(cid)
            rw['choices'].append({'kind': 'card', 'id': cid})
        if rnd() < 0.3:
            t = rand_tool()
            add_item(G, t['kind'], t['id'])
            rw['notes'].append('你在地上捡到了「%s」。' % item_name(t))
    if k == 'box':
        rw['choices'] = [rand_tool(), rand_tool()]
    if k in ('elite', 'guard', 'event'):
        rw['relics'] = relic_choices(G, 2 if k == 'event' else 3)
    if G['flags'].get('spinBonus') and G['flags']['spinBonus'] == G['map']['cur']:
        r = rand_relic_id(G, 'CUR', rw['relics'])
        if r:
            gain_relic(G, r)
            rw['notes'].append('旋转门的谢礼：「%s」。' % RELICS[r]['name'])
    if k == 'nightmare':
        add_luc(G, 1)
        G['flags']['freeMove'] = True
        rw['notes'].append('清醒 +1，下一步不花时长。')
    if k == 'merchant' and B.get('stealIdx') is not None:
        r = cur_room(G)
        s = r['data']['stock'][B['stealIdx']]
        if s and not s['sold']:
            s['sold'] = True
            if s['kind'] == 'relic':
                gain_relic(G, s['id'])
            else:
                add_item(G, s['kind'], s['id'])
            rw['notes'].append('你拿走了「%s」。' % item_name(s))
    return rw


def end_battle(G):
    B = G['battle']
    r = cur_room(G)
    end = B['end']
    if G['flags'].get('spinBonus') == G['map']['cur']:
        G['flags']['spinBonus'] = None
    if end == 'lost':
        G['battle'] = None
        game_over(G)
        return
    if B['kind'] == 'echo':
        G['battle'] = None
        G['screen'] = 'map'
        go_next_floor(G, 'collapse')
        return
    if end == 'won':
        G['stats']['wins'] += 1
        if B['kind'] == 'boss':
            G['battle'] = None
            r['done'] = True
            G['pending'] = {'type': 'finale'}
            G['screen'] = 'map'
            return
        rw = battle_rewards(G, B)
        r['done'] = True
        if B['kind'] == 'merchant':
            r['data']['closed'] = True
        G['battle'] = None
        G['screen'] = 'map'
        G['pending'] = {'type': 'reward', 'rw': rw}
        return
    if end == 'escaped':
        hurt(G, 2)
        add_luc(G, -1)
        r['done'] = True
        G['battle'] = None
        G['screen'] = 'map'
        if G['hp'] <= 0:
            game_over(G)
            return
        note(G, '小梦魇离开了。你掉了 2 血，清醒 -1。', 'bad')
        after_room(G)
        return
    if end == 'boxfail':
        r['done'] = True
        G['battle'] = None
        G['screen'] = 'map'
        note(G, '丝带没有散开。礼品箱沉沉地睡着了。')
        after_room(G)
        return


def game_over(G):
    G['screen'] = 'map'
    G['pending'] = {'type': 'over'}
    G['dead'] = True


# ================================================================ 房间互动
def shop_buy(G, idx):
    r = cur_room(G)
    s = r['data']['stock'][idx]
    if s['sold']:
        return '已经卖掉了'
    price = jsround(s['price'] * price_mult(G))
    if G['coins'] < price:
        return '糖霜币不够'
    G['coins'] -= price
    s['sold'] = True
    if s['kind'] == 'relic':
        gain_relic(G, s['id'])
    else:
        add_item(G, s['kind'], s['id'])
    return None


def service_price(G, what):
    base = (34 if cur_room(G)['type'] == 'dshop' else 38) if what == 'luc' else 18
    return jsround(base * price_mult(G))


def shop_service(G, what):
    r = cur_room(G)
    svc = r['data'].setdefault('svc', {})
    used = svc.get(what, 0)
    if what == 'heal' and G['hp'] >= G['maxHp']:
        return '你的血是满的'
    if what == 'luc' and G['luc'] >= 7:
        return '清醒值已经满了'
    if used >= 2:
        return '这一样今天卖完了'
    price = service_price(G, what)
    if G['coins'] < price:
        return '糖霜币不够'
    G['coins'] -= price
    svc[what] = used + 1
    if what == 'heal':
        heal(G, 1)
    else:
        add_luc(G, 1)
    return None


def shop_sell(G, u):
    it = find_item(G, u)
    if not it:
        return '找不到这件东西'
    if is_junk(it):
        return '纪念品卖不出去，只能付钱请行商处理掉'
    if it['kind'] == 'card' and len(G['cards']) <= 3:
        return '牌盒里至少要留 3 张牌'
    remove_item(G, u)
    G['coins'] += sell_price(it)
    return None


def shop_dispose(G, u):
    it = find_item(G, u)
    if not is_junk(it):
        return '找不到这件纪念品'
    fee = JUNK[it['id']]['fee']
    if G['coins'] < fee:
        return '处理它要 %d 糖霜币' % fee
    remove_item(G, u)
    G['coins'] -= fee
    G['stats']['junkGone'] = G['stats'].get('junkGone', 0) + 1
    return None


def bag_loss_blocked(G, rid):
    """卖掉大号行李箱以后，纪念品不能比格子还多。"""
    return rid == 'bag' and junk_count(G) > 5


def sell_relic(G, rid):
    if rid not in G['relics']:
        return '没有这件藏品'
    if bag_loss_blocked(G, rid):
        return '行李箱里的纪念品太多了，大号行李箱卖不掉'
    G['relics'].remove(rid)
    if rid == 'crown':
        G['maxHp'] -= 1
        G['hp'] = min(G['hp'], G['maxHp'])
    if rid == 'shard':
        G['maxHp'] += 1
    G['coins'] += sell_price({'kind': 'relic', 'id': rid})
    return None


def try_steal(G, idx):
    r = cur_room(G)
    s = r['data']['stock'][idx]
    if s['sold']:
        return {'ok': False, 'why': '已经卖掉了'}
    if r['data'].get('stole'):
        return {'ok': False, 'why': '他已经醒了'}
    r['data']['stole'] = True
    chance = 0.6 if G['luc'] >= 5 else 0.45
    if rnd() < chance:
        s['sold'] = True
        if s['kind'] == 'relic':
            gain_relic(G, s['id'])
        else:
            add_item(G, s['kind'], s['id'])
        return {'ok': True, 'got': True, 'item': s}
    G['pending'] = None
    start_battle(G, 'merchant', 'merchant', {'stealIdx': idx})
    return {'ok': True, 'got': False}


def rest_choose(G, i):
    if i == 0:
        n = heal(G, 3)
        return '你睡了一小会儿，回复了 %d 点血。' % n if n else '你睡了一小会儿，醒来时神清气爽。'
    if i == 1:
        return '你发了会儿呆，脑子清楚了一点：清醒 +%d。' % add_luc(G, 1)
    G['map']['time'] += 1
    return '你数到第一百颗星星的时候，时间好像慢了下来：时长 +1。'


def _wish_relic(G):
    r = rand_relic_id(G, 'R') or rand_relic_id(G, 'UC')
    if r:
        gain_relic(G, r)
        return '许愿池里浮上来「%s」。' % RELICS[r]['name']
    return '许愿池里什么也没浮上来。'


def _wish_sleep(G):
    G['hp'] = G['maxHp']
    return '你睡了很久很久，醒来时枕头是暖的。血量回满了。'


def _wish_luc(G):
    add_luc(G, 2)
    return '你的眼睛亮了起来：清醒 +2。'


def _wish_coins(G):
    add_coins(G, 80)
    return '硬币一枚一枚掉进你的口袋，叮叮当当：得到 80 糖霜币。'


WISHES = [
    {'label': '想好好睡一觉', 'tip': '血量回满', 'run': _wish_sleep},
    {'label': '想要一件宝物', 'tip': '得到 1 件稀有藏品', 'run': _wish_relic},
    {'label': '想一直清醒', 'tip': '清醒 +2', 'run': _wish_luc},
    {'label': '想要很多糖', 'tip': '得到 80 糖霜币', 'run': _wish_coins},
]


def swap_options(G):
    things = len(real_luggage(G)) + len(G['cards'])
    return [
        {'label': '投进 40 糖霜币', 'tip': '换 1 件普通藏品', 'need': None if G['coins'] >= 40 else '糖霜币不够'},
        {'label': '投进 40 糖霜币和 1 点血', 'tip': '换 1 件稀有藏品',
         'need': '糖霜币不够' if G['coins'] < 40 else ('血不够了' if G['hp'] <= 1 else None)},
        {'label': '投进 2 件东西（行李箱或牌盒里的都行）', 'tip': '换 1 件藏品',
         'need': None if things >= 2 else '身上的东西不够两件（纪念品不算）'},
        {'label': '投进 1 件藏品', 'tip': '换 3 件随机工具（蜡烛、门、铃铛）', 'need': None if G['relics'] else '你还没有藏品'},
    ]


def swap_do(G, i, pick_u=None):
    o = swap_options(G)[i]
    if o['need']:
        return {'why': o['need']}
    if i == 0:
        G['coins'] -= 40
        r = rand_relic_id(G, 'C') or rand_relic_id(G, 'U')
        if r:
            gain_relic(G, r)
        return {'text': '贩卖机咔哒一声，掉出「%s」。' % RELICS[r]['name'] if r else '贩卖机吞了钱，什么也没吐。'}
    if i == 1:
        G['coins'] -= 40
        hurt(G, 1)
        r = rand_relic_id(G, 'R') or rand_relic_id(G, 'U')
        if r:
            gain_relic(G, r)
        return {'text': '贩卖机发出满意的声音，掉出「%s」。' % RELICS[r]['name'] if r else '贩卖机吞了钱，什么也没吐。'}
    if i == 2:
        its = [find_item(G, u) for u in (pick_u or [])]
        if len(its) != 2 or any((not x) or is_junk(x) for x in its):
            return {'why': '要挑两件东西（纪念品不收）'}
        names = [item_name(x) for x in its]
        for x in its:
            remove_item(G, x['u'])
        r = rand_relic_id(G, 'CU')
        if r:
            gain_relic(G, r)
        return {'text': '「%s」和「%s」被吞了进去。掉出来的是「%s」。' % (names[0], names[1], RELICS[r]['name'] if r else '一阵风')}
    if i == 3:
        rid = pick_u or last(G['relics'])
        if rid not in G['relics']:
            return {'why': '没有这件藏品'}
        if bag_loss_blocked(G, rid):
            return {'why': '行李箱里的纪念品太多了，大号行李箱投不进去'}
        nm = RELICS[rid]['name']
        sell_relic(G, rid)
        G['coins'] -= sell_price({'kind': 'relic', 'id': rid})
        got = []
        for _ in range(3):
            t = rand_tool()
            add_item(G, t['kind'], t['id'])
            got.append(item_name(t))
        return {'text': '「%s」被吞了进去，掉出来「%s」。' % (nm, '」「'.join(got))}
    return {'why': '没有这个选项'}


# ---------------------------------------------------------------- 代理办事处
def deposit_item(G, meta, u):
    if len(meta['locker']) >= 3:
        return '保管箱已经满了（3 件）'
    it = find_item(G, u)
    if not it:
        return '找不到这件东西'
    if is_junk(it):
        return '安娜摇摇头：这个我可不收。'
    if it['kind'] == 'card' and len(G['cards']) <= 3:
        return '牌盒里至少要留 3 张牌'
    if G['coins'] < 15:
        return '寄存要 15 糖霜币'
    remove_item(G, u)
    G['coins'] -= 15
    meta['locker'].append({'kind': it['kind'], 'id': it['id']})
    return None


def deposit_coins(G, meta):
    if len(meta['locker']) >= 3:
        return '保管箱已经满了（3 件）'
    if G['coins'] < 40:
        return '要 40 糖霜币（存 30，手续费 10）'
    G['coins'] -= 40
    meta['locker'].append({'kind': 'coins', 'n': 30})
    return None


def recruit_pal(G, pid):
    bell = next((x for x in G['luggage'] if x['kind'] == 'bell'), None)
    if not bell:
        return '需要 1 只呼救铃'
    if pal_count(G) >= 3:
        return '伙伴最多 3 个（斗鸡不算）'
    if has_pal(G, pid):
        return '已经是你的伙伴了'
    if G['coins'] < 30:
        return '还要 30 糖霜币'
    remove_item(G, bell['u'])
    G['coins'] -= 30
    G['pals'].append({'id': pid, 'lv': 1})
    return None


def upgrade_pal(G, pid):
    bell = next((x for x in G['luggage'] if x['kind'] == 'bell'), None)
    if not bell:
        return '需要 1 只呼救铃'
    p = next((x for x in G['pals'] if x['id'] == pid), None)
    if not p:
        return '没有这个伙伴'
    if p['lv'] >= 2:
        return '已经进阶过了'
    remove_item(G, bell['u'])
    p['lv'] = 2
    return None


# ================================================================ 故事会与结局
def story_for_room(G, meta):
    """决定这间故事会讲哪个故事。结果记在房间里。
    每一层（第 1～5 层）第一次走进的故事会，会给你那封信的一行（信的碎片）。"""
    from .story import SIDE_ORDER
    r = cur_room(G)
    if r['data'].get('story'):
        return r['data']['story']
    m = G['map']
    fl = G['floor']
    main_heard = meta.setdefault('mainHeard', [])
    piece = None
    if m['kind'] == 'main' and 1 <= fl <= 5 and (fl - 1) not in G['letter'] and (fl - 1) not in G.get('pieceRooms', []):
        piece = fl - 1
        kind, sid = ('main', fl) if fl not in main_heard else ('side', next_side(meta, G))
    elif m['kind'] == 'final' and 6 not in main_heard:
        kind, sid = 'main', 6
    else:
        kind, sid = 'side', next_side(meta, G)
    if piece is not None:
        G.setdefault('pieceRooms', []).append(piece)
    st = {'kind': kind, 'id': sid, 'piece': piece}
    r['data']['story'] = st
    return st


def next_side(meta, G):
    from .story import SIDE_ORDER
    heard = meta.setdefault('sideHeard', [])
    taken = G.setdefault('sideTaken', [])
    for sid in SIDE_ORDER:
        if sid not in heard and sid not in taken:
            taken.append(sid)
            return sid
    # 都讲完了：从头再讲
    meta['sideHeard'] = []
    for sid in SIDE_ORDER:
        if sid not in taken:
            taken.append(sid)
            return sid
    G['sideTaken'] = []
    return SIDE_ORDER[0]


def finish_story(G, meta, choice):
    r = cur_room(G)
    st = r['data']['story']
    if st['kind'] == 'main':
        lst = meta.setdefault('mainHeard', [])
        if st['id'] not in lst:
            lst.append(st['id'])
    else:
        lst = meta.setdefault('sideHeard', [])
        if st['id'] not in lst:
            lst.append(st['id'])
    meta['storyCount'] = meta.get('storyCount', 0) + 1
    out = []
    by_douji = st['kind'] == 'main' and st['id'] == 6
    if choice == 0:
        n = heal(G, 2)
        if by_douji:
            out.append('你把斗鸡抱进怀里。它把脑袋靠在你胸口，小声说：「本鸡就知道你会抱。」回复 %d 点血。' % n if n else
                       '你把斗鸡抱进怀里。它把脑袋靠在你胸口，小声说：「本鸡就知道你会抱。」')
        else:
            out.append('clawd 们挤过来，把你围在最暖和的中间：回复 %d 点血。' % n if n else
                       'clawd 们挤过来，把你围在最暖和的中间。你本来就好好的，现在更好了。')
    else:
        n = add_luc(G, 1)
        out.append('你把故事记在了心里：清醒 +1。' if n else '你把故事记在了心里。')
    if st.get('piece') is not None and st['piece'] not in G['letter']:
        G['letter'].append(st['piece'])
        G['letter'].sort()
        out.append('你把那张小纸条仔细叠好，收进了口袋。（信的碎片：%d/5）' % len(G['letter']))
    return '\n'.join(out)


def finale_choose(G, meta, i):
    if i == 0:
        ending = 'reply' if len(G['letter']) >= 5 else 'unfinished'
    else:
        ending = 'efficient'
    G['ending'] = ending
    G['won'] = True
    G['dead'] = True
    G['pending'] = {'type': 'ended', 'ending': ending}
    st = meta.setdefault('stats', {})
    st['wins'] = st.get('wins', 0) + 1
    st['best'] = max(st.get('best', 0), 6)
    ends = meta.setdefault('endings', [])
    if ending not in ends:
        ends.append(ending)
    return ending
