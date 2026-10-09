# -*- coding: utf-8 -*-
"""梦城堡 · 命令行界面。

每条命令：读档 → 执行 → 存档 → 打印。输出全是纯文字，不用颜色。
对手的暗牌、牌堆的顺序不会出现在输出里——除非游戏规则让你看见（清醒值、藏品、芭蕾娃娃、预言梦）。
"""
import sys
import traceback

from . import engine as E
from . import savefile
from . import story as S
from .data import (ROOMS, ENEMIES, CARDS, CANDLES, DOORS, BELL, JUNK, RELICS, RARITY,
                   PALS, START_PALS, DEPTHS, DREAMS, DOUJI_MOVES, HAND_MAX)
from .events import EVENTS, visible_choices, event_choose

CMD = 'python3 game.py'
COLS = 'ABCDE'
RULE = '─' * 46
DOUBLE = '═' * 46


class GameError(Exception):
    pass


def default_meta():
    return {'locker': [], 'stats': {'runs': 0, 'wakes': 0, 'wins': 0, 'best': 0}, 'tips': {},
            'depth': 'deep', 'lastPal': 'bear', 'mainHeard': [], 'sideHeard': [], 'storyCount': 0,
            'endings': []}


def normalize(state):
    if not isinstance(state, dict):
        state = {}
    meta = state.get('meta')
    if not isinstance(meta, dict):
        meta = {}
    d = default_meta()
    for k, v in d.items():
        if k not in meta:
            meta[k] = v
    for k, v in d['stats'].items():
        meta['stats'].setdefault(k, v)
    state['meta'] = meta
    run = state.get('run')
    if not isinstance(run, dict) or run.get('v') != E.VERSION:
        run = None
    state['run'] = run
    return state


class Ctx:
    def __init__(self, state):
        self.state = state
        self.meta = state['meta']
        self.out = []
        self.show_view = True

    @property
    def G(self):
        return self.state.get('run')

    @G.setter
    def G(self, v):
        self.state['run'] = v

    def say(self, *lines):
        for ln in lines:
            self.out.extend(str(ln).split('\n'))


# ================================================================ 小工具
def hearts(hp, mx):
    hp = max(0, min(hp, mx))
    return '♥' * hp + '♡' * (mx - hp)


def coord(k):
    x, y = E.unkey(k)
    return '%s%d' % (COLS[x], y + 1)


def parse_coord(s):
    s = s.strip().upper()
    if len(s) >= 2 and s[0] in COLS and s[1:].isdigit():
        return E.key(COLS.index(s[0]), int(s[1:]) - 1)
    return None


def norm(s):
    return str(s).strip().lower().replace('·', '').replace('・', '').replace(' ', '').replace('「', '').replace('」', '')


def journal_add(G, title, text):
    G.setdefault('journal', []).append({'title': title, 'text': text})


def drain_inbox(ctx):
    G = ctx.G
    if not G or not G.get('inbox'):
        return
    items = G['inbox']
    G['inbox'] = []
    for n in items:
        ctx.say('· ' + n['text'])


def douji_line(kind):
    return '斗鸡：「%s」' % E.pick(S.DOUJI_LINES[kind])


def item_line(it, show_kind=True):
    s = E.item_name(it)
    extra = []
    if show_kind:
        extra.append(E.item_kind_name(it))
    if it['kind'] == 'card':
        extra.append(RARITY[CARDS[it['id']]['r']])
    if it.get('temp'):
        extra.append('临时')
    if extra:
        s += '（%s）' % '·'.join(extra)
    return s


KIND_NAMES = {'normal': '作战', 'ambush': '狭路相逢', 'elite': '紧急作战', 'guard': '险路恶敌', 'nightmare': '梦魇',
              'boss': '梦的尽头', 'box': '礼品箱', 'event': '不期而遇', 'merchant': '被抓了个正着', 'echo': '梦中梦'}


# ================================================================ 地图
DIRS = [(0, -1, '往上'), (1, 0, '往右'), (0, 1, '往下'), (-1, 0, '往左'),
        (1, -1, '往右上'), (1, 1, '往右下'), (-1, 1, '往左下'), (-1, -1, '往左上')]


def neighbor_list(G):
    """相邻房间（有走廊连着的），按 上、右、下、左、斜角 排好。"""
    m = G['map']
    x, y = E.unkey(m['cur'])
    nb = set(m['adj'][m['cur']])
    out = []
    for dx, dy, word in DIRS:
        k = E.key(x + dx, y + dy)
        if k in nb:
            out.append((k, word))
            nb.discard(k)
    for k in sorted(nb):  # 保险：不管走廊怎么连，相邻的房间一个都不会漏
        out.append((k, '有走廊'))
    return out


def room_label(G, k):
    m = G['map']
    r = m['rooms'][k]
    v = m['vis'].get(k, 0)
    if v >= 3:
        t = r['type']
        R = ROOMS[t]
        s = R['name']
        if t in ('battle', 'ambush', 'elite', 'guard', 'nightmare', 'gift') and r.get('eid') and not r['done']:
            s += ' · ' + ENEMIES[r['eid']]['name']
        if t == 'nightmare' and not r['done']:
            s += '（走进去要花 2 时长）'
        if t == 'event' and not r['done'] and G['luc'] >= 7:
            s += '（你看得清：「%s」）' % EVENTS[r['data']['ev']]['title']
        if t in ('stairs', 'lift'):
            s += '（出口）'
        if t == 'well':
            s += '（出口：直接跳到下一层）'
        if t == 'vent':
            s += '（走进来不花时长）'
        if t == 'boss' and not r['done']:
            s += '（梦魇）'
        if r['done'] and not R.get('perm') and t not in ('start',):
            s += '（故事讲完了）' if t == 'story' else '（来过了）'
        if t == 'shop' or t == 'dshop':
            if r['data'].get('closed'):
                s += '（关门了）'
        return s
    if v == 2:
        return '凶恶的梦境（太远了，看不清是什么）' if E.looks_hostile(r) else '平静的梦境（太远了，看不清是什么）'
    return '看不清的房间（雾太浓了）'


def grid_lines(G):
    m = G['map']
    W, H = m['W'], m['H']

    def shown(k):
        return k in m['rooms'] and m['vis'].get(k, 0) >= 1

    def linked(a, b):
        return shown(a) and shown(b) and b in m['adj'][a]

    lines = ['     ' + ''.join(' %s     ' % COLS[x] for x in range(W)).rstrip()]
    for y in range(H):
        row = '%3d  ' % (y + 1)
        for x in range(W):
            k = E.key(x, y)
            if shown(k):
                cell = ('[%s]' if k == m['cur'] else ' %s ') % coord(k)
            else:
                cell = '    '
            conn = '---' if (x + 1 < W and linked(k, E.key(x + 1, y))) else '   '
            row += cell + conn
        lines.append(row.rstrip())
        if y + 1 < H:
            v = [' '] * (5 + 7 * W)
            for x in range(W):
                if linked(E.key(x, y), E.key(x, y + 1)):
                    v[5 + 7 * x + 1] = '|'
                if x + 1 < W:
                    a = linked(E.key(x, y), E.key(x + 1, y + 1))       # 往右下的斜走廊
                    b = linked(E.key(x + 1, y), E.key(x, y + 1))       # 往左下的斜走廊
                    if a or b:
                        v[5 + 7 * x + 5] = 'X' if (a and b) else ('\\' if a else '/')
            lines.append(''.join(v).rstrip())
    return lines


def vis_dist(G, src):
    m = G['map']
    d = {src: 0}
    q = [src]
    i = 0
    while i < len(q):
        c = q[i]
        i += 1
        for n in m['adj'][c]:
            if n in d or m['vis'].get(n, 0) < 1:
                continue
            d[n] = d[c] + 1
            q.append(n)
    return d


def status_line(G):
    m = G['map']
    if m['kind'] == 'final':
        t = '时长 不限'
    elif m['kind'] == 'bonus':
        t = '时长 %d（兔子洞里的）' % m['time']
    else:
        t = '时长 %d' % m['time']
    return '血 %s %d/%d · 清醒 %d/7 · %s · 糖霜币 %d' % (hearts(G['hp'], G['maxHp']), max(0, G['hp']), G['maxHp'],
                                                    G['luc'], t, G['coins'])


def pals_text(G):
    return '、'.join(PALS[p['id']]['name'] + ('（进阶）' if p['lv'] > 1 else '') for p in G['pals'])


def candles_text(G):
    parts = []
    for i in range(2):
        if i < len(G['lit']):
            c = G['lit'][i]
            parts.append('%d. %s（还能烧 %d 步）' % (i + 1, CANDLES[c['id']]['name'], c['left']))
        else:
            parts.append('%d. 空着' % (i + 1))
    return '  '.join(parts)


def luggage_text(G):
    if not G['luggage']:
        return '（空的）'
    return '  '.join('[%d] %s' % (i + 1, E.item_name(it)) for i, it in enumerate(G['luggage']))


def floor_title(G):
    F = E.floor_info(G)
    m = G['map']
    if m['kind'] == 'bonus':
        return '兔子洞 · %s · %s' % (F['label'], F['name'])
    return '%s · %s' % (F['label'], F['name'])


def view_map(ctx):
    G = ctx.G
    m = G['map']
    ctx.say(RULE, '【%s】' % floor_title(G))
    if m.get('dream'):
        D = DREAMS[m['dream']]
        ctx.say('梦构 · %s：%s' % (D['name'], D['desc']))
    ctx.say(status_line(G))
    ctx.say('伙伴：%s　　信的碎片：%d/5' % (pals_text(G), len(G['letter'])))
    ctx.say('烛台：%s' % candles_text(G))
    ctx.say('行李箱（%d/%d 格）：%s' % (len(G['luggage']), E.luggage_cap(G), luggage_text(G)))
    if E.over_cap(G):
        ctx.say('！行李箱塞不下了：丢掉（drop）或用掉一件才能继续走%s。' % ('（纪念品丢不掉，只能找行商处理）' if E.junk_count(G) else ''))
    ctx.say('', '地图（[ ] 是你。只有用 --- 或 | 连着的两个房间之间才有走廊；没画出来的地方还藏在雾里）：')
    ctx.say(*grid_lines(G))
    ctx.say('')
    cur = E.cur_room(G)
    here = room_label(G, m['cur'])
    ctx.say('你在 %s：%s。' % (coord(m['cur']), here))
    if ROOMS[cur['type']].get('perm') and cur['type'] != 'start':
        ctx.say('（这间房间可以反复进：用 enter 再进去。）')
    ctx.say('相邻的房间：')
    for i, (k, word) in enumerate(neighbor_list(G), 1):
        c = E.can_move(G, k)
        if m['vis'].get(k, 0) < 3 and not E.over_cap(G):
            # 看不清的房间：不提前透露走进去要花多少时长
            ctx.say('  [%d] go %s（%s）  %s —— 至少花 1 时长' % (i, coord(k), word, room_label(G, k)))
        elif c['ok']:
            cost = '不花时长' if c['cost'] == 0 else '花 %d 时长' % c['cost']
            ctx.say('  [%d] go %s（%s）  %s —— %s' % (i, coord(k), word, room_label(G, k), cost))
        else:
            ctx.say('  [%d] go %s（%s）  %s —— 走不了：%s' % (i, coord(k), word, room_label(G, k), c['why']))
    d = vis_dist(G, m['cur'])
    nb = set(m['adj'][m['cur']])
    others = [k for k in m['rooms'] if k != m['cur'] and k not in nb and m['vis'].get(k, 0) >= 1]
    others.sort(key=lambda k: (d.get(k, 99), E.manhattan(k, m['cur']), k))
    if others:
        ctx.say('其他看得见的房间：')
        for k in others:
            ctx.say('  %s  %s' % (coord(k), room_label(G, k)))
    # 出口
    exits = [k for k, r in m['rooms'].items() if r['type'] in ('stairs', 'lift', 'well', 'boss') and m['vis'].get(k, 0) >= 3]
    for k in sorted(exits):
        r = m['rooms'][k]
        nm = ROOMS[r['type']]['name'] if r['type'] != 'boss' else '梦魇所在的生梦之源'
        if k == m['cur']:
            continue
        if k in d:
            ctx.say('→ %s在 %s：沿着看得见的走廊，最少还要走 %d 段。' % (nm, coord(k), d[k]))
        else:
            ctx.say('→ %s在 %s：还没找到看得见的走廊通过去。' % (nm, coord(k)))
    if m['kind'] == 'main' and not any(m['rooms'][k]['type'] == 'stairs' for k in exits):
        ctx.say('→ 还没看见楼梯间。楼梯间总在最上面两行（第 1、2 行）。')
    if m['kind'] == 'main' and m['time'] <= 2 and cur['type'] not in ('stairs', 'lift', 'well'):
        # 固定挑一句，这样反复 status 看到的都一样
        ctx.say('斗鸡：「%s」' % S.DOUJI_LINES['hurry'][m['time'] % len(S.DOUJI_LINES['hurry'])])
    if m['kind'] == 'bonus':
        ctx.say('→ 这里是兔子洞。时长用完，洞口会把你吐回原来的房间；也可以随时用 leave 爬出去。')
    ctx.say('', '你可以：')
    ctx.say('  go <房间>              走到相邻的房间，例如 go %s（也可以 choose <上面的编号>）'
            % (coord(neighbor_list(G)[0][0]) if neighbor_list(G) else 'C5'))
    if ROOMS[cur['type']].get('perm') and cur['type'] != 'start':
        ctx.say('  enter                  再进一次这间「%s」' % ROOMS[cur['type']]['name'])
    if any(x['kind'] == 'candle' for x in G['luggage']):
        ctx.say('  light <编号>           点燃行李箱里的蜡烛')
    if G['lit']:
        ctx.say('  snuff <1或2>           熄灭烛台上的蜡烛')
    if any(x['kind'] == 'door' for x in G['luggage']):
        ctx.say('  door <编号> [房间]     推开行李箱里的一扇门（不写房间就列出能去哪儿）')
    if G['luggage']:
        ctx.say('  drop <编号>            丢掉行李箱里的一件东西')
    if m['kind'] == 'bonus':
        ctx.say('  leave                  爬出兔子洞')
    ctx.say('  bag                    看牌盒、行李箱、藏品、伙伴和信的碎片')
    ctx.say('  journal / rules / help 重读故事 / 看规则 / 看全部命令')
    if not ctx.meta['tips'].get('map'):
        ctx.meta['tips']['map'] = True
        ctx.say('', S.TIP_MAP)


# ================================================================ 牌桌
def foe_know(G, B):
    if G['luc'] >= 7 or E.has_relic(G, 'shard') or (E.has_relic(G, 'magic') and B['round'] == 1):
        return 'exact'
    if G['luc'] >= 5 or E.has_relic(G, 'pea') or E.lit_has(G, 'star'):
        return 'hint'
    return None


def unseen_values(G, B):
    pool = E.full_deck(B['two'])
    seen = [B['you']['down']['v']] + [c['v'] for c in B['you']['up']] + [c['v'] for c in B['foe']['up']]
    if foe_know(G, B) == 'exact':
        seen.append(B['foe']['down']['v'])
    for v in seen:
        if v in pool:
            pool.remove(v)
    return pool


def fmt_values(vals):
    out = []
    for v in sorted(set(vals)):
        n = vals.count(v)
        out.append('%d×%d' % (v, n) if n > 1 else str(v))
    return '、'.join(out) if out else '（没有）'


def trait_text(B):
    p = B['p']
    En = ENEMIES[B['eid']]
    s = '【%s' % En['trait']

    def dots(n, mx):
        return '●' * n + '○' * max(0, mx - n)

    eid = B['eid']
    if eid == 'car':
        s += ' %s' % dots(p['speed'], 3)
    elif eid == 'sling':
        k = B['round'] % 3
        s += ' 蓄满了' if k == 0 else ' %s' % dots(k, 3)
    elif eid == 'candy':
        s += ' ×%d' % p['candies']
    elif eid == 'guard':
        s += ' ×%d' % p['scis']
    elif eid == 'doll':
        s += ' ×%d' % p['watches']
    elif eid == 'bot':
        s += ' · 零件 ×%d' % p['parts']
    elif eid == 'puppet':
        s += ' ×%d' % p['mirrors']
    elif eid in ('magician', 'merchant'):
        s += ' · 袖子里藏着 1 张牌' if p['hand'] else ''
    elif eid == 'gpt':
        s += ' ×%d' % p['pitch']
    elif eid == 'gemini':
        s += ' ×%d' % p['verdicts']
    elif eid == 'lnm':
        s += ' · 还剩 %d 局' % max(0, B['timer'] - B['round'] + 1)
    elif eid == 'box':
        s += ' · 丝带还有 %d 条 · 还剩 %d 局' % (B['gift']['r'], max(0, B['timer'] - B['round'] + 1))
    return s + '】' + En['tdesc']


def cards_text(cards):
    return ' '.join(str(c['v']) for c in cards)


def view_battle(ctx):
    G = ctx.G
    B = G['battle']
    En = ENEMIES[B['eid']]
    T = B['target']
    ctx.say(RULE, '【牌桌 · 第 %d 局】%s · %s' % (B['round'], En['name'], KIND_NAMES.get(B['kind'], '')))
    ctx.say('对手：%s　血 %s %d/%d' % (En['name'], hearts(B['foeHp'], B['foeMax']), B['foeHp'], B['foeMax']))
    ctx.say('  ' + trait_text(B))
    ctx.say('你：' + status_line(G).split(' · 时长')[0] + ' · 糖霜币 %d' % G['coins'])
    ctx.say('')
    ctx.say('目标点数：%d%s' % (T, '（被改过了）' if T != 21 else ''))
    know = foe_know(G, B)
    fd = B['foe']['down']['v']
    fu = E.up_sum(B['foe'])
    if know == 'exact':
        fdown = '[暗牌 %d（你看得见）]' % fd
        ftot = '= %d' % (fd + fu) + ('（爆了）' if fd + fu > T else '')
    elif know == 'hint':
        big = '大' if fd >= 6 else '小'
        fdown = '[暗牌：感觉是%s的（%s）]' % (big, '6～11' if fd >= 6 else '1～5')
        ftot = '= %s + %d' % (big, fu)
    else:
        fdown = '[暗牌 ?]'
        ftot = '= ? + %d' % fu
    if know != 'exact' and fu + 1 > T:
        ftot += '（光明牌就超过 %d 了：它肯定爆了）' % T
    fup = cards_text(B['foe']['up']) or '（没有明牌）'
    ctx.say('%s的牌：%s %s  %s' % (En['name'], fdown, fup, ftot))
    ty = E.total(B['you'])
    yup = cards_text(B['you']['up']) or '（没有明牌）'
    ctx.say('你的牌：[暗牌 %d] %s  = %d%s' % (B['you']['down']['v'], yup, ty,
                                          '（爆了）' if ty > T else ('（正好！）' if ty == T else '')))
    ctx.say('牌堆：%d 张。' % E.deck_len(B))
    kt = E.known_top(B)
    if kt:
        parts = []
        for i, c in kt:
            how = '预言梦让它一直翻开着' if (i == 0 and B['prophecy']) else '芭蕾娃娃看到的'
            parts.append('第 %d 张是 %d（%s）' % (i + 1, c['v'], how))
        ctx.say('你知道的牌堆顶：' + '；'.join(parts))
    kb = E.known_buried(B)
    if kb:
        ctx.say('你塞到牌堆最底下的牌：%s（它们会最后才被抽到）' % '、'.join(str(c['v']) for c in kb))
    un = unseen_values(G, B)
    ctx.say('没见过的牌（还在牌堆里，或者是对方的暗牌）：%s' % fmt_values(un))
    safe = [v for v in un if ty + v <= T]
    bust = [v for v in un if ty + v > T]
    if kt and kt[0][0] == 0:
        nv = kt[0][1]['v']
        ctx.say('  你再要一张：会抽到牌堆顶的 %d，变成 %d 点%s。' % (nv, ty + nv, '（爆了）' if ty + nv > T else ''))
    elif not bust:
        ctx.say('  你再要一张：怎么抽都不会爆。')
    elif not safe:
        ctx.say('  你再要一张：怎么抽都会爆。')
    else:
        ctx.say('  你再要一张：抽到 %s 不会爆；抽到 %s 会爆。' % (fmt_values(safe), fmt_values(bust)))
    if B['you']['fx'] or B['foe']['fx']:
        ctx.say('场上的效果：')
        for f in B['foe']['fx']:
            ctx.say('  对方 · ' + f['label'])
        for f in B['you']['fx']:
            ctx.say('  你 · ' + f['label'])
    ctx.say('')
    if B['noBag']:
        ctx.say('手里的王牌：梦中梦里，行李箱打不开。')
    else:
        ctx.say('手里的王牌（最多 %d 张）：' % HAND_MAX + ('' if B['hand'] else '没有'))
        for i, it in enumerate(B['hand'], 1):
            why = E.card_usable(G, B, it)
            ctx.say('  [%d] %s —— %s%s' % (i, item_line(it, False), CARDS[it['id']]['desc'], ('（现在用不了：%s）' % why) if why else ''))
        ctx.say('  牌盒里还有 %d 张没抽%s。' % (len(B['pile']), ('；用过的 %d 张，牌盒抽空后会洗回去' % len(B['used'])) if B['used'] else ''))
    if E.locked_now(B):
        ctx.say('  （锁魂梦：前两局用不了王牌和伙伴技能——斗鸡除外。）')
    ctx.say('伙伴：')
    for pal in G['pals']:
        P = PALS[pal['id']]
        left = E.pal_left(G, B, pal)
        if pal['id'] == 'douji':
            ctx.say('  斗鸡 —— 这一场还能出招 %d 次（三招共用）：' % max(0, left))
            ctx.say('    飞扑：直接算你赢下这一局，对方多掉 1 血，你没满血就回 1 血')
            ctx.say('    护主：这一局你输了不掉血，对方赢了还会被反啄 1 血%s' % ('（已经在护着你了）' if E.has_fx(B['you'], 'dguard') else ''))
            ctx.say('    啄牌：叼走对方最后一张明牌，扔回牌堆')
        else:
            sk = P['desc'] if pal['lv'] == 1 or pal['id'] != 'bear' else '回复 2 点血。'
            why = E.skill_usable(G, B, pal)
            ctx.say('  %s —— %s：%s还能用 %d 次%s' % (P['name'], P['skill'], sk, max(0, left),
                                                 ('（现在用不了：%s）' % why) if why and left > 0 else ''))
    ctx.say('', '轮到你了。你可以：')
    ch, cs = E.can_hit(G, B), E.can_stand(G, B)
    ctx.say('  hit                    要牌' + ('' if ch['ok'] else '（现在不行：%s）' % ch['why']))
    ctx.say('  stand                  停牌' + ('' if cs['ok'] else '（现在不行：%s）' % cs['why']))
    if B['hand'] and not B['noBag']:
        ctx.say('  use <编号或名字>       用一张王牌，例如 use 1（不占回合）')
    ctx.say('  pal 斗鸡 <招式>        斗鸡出招：飞扑 / 护主 / 啄牌（不占回合）')
    if len(G['pals']) > 1:
        ctx.say('  pal <伙伴>             请伙伴帮忙，例如 pal %s（不占回合）' % PALS[G['pals'][1]['id']]['name'])
    if any(c['u'] in (B.get('peek') or []) for _, c in kt):
        ctx.say('  bury <编号>            把芭蕾娃娃看到的那张牌塞到牌堆最底下，例如 bury 1')
    ctx.say('  bag / rules            看身上的东西 / 看规则')


# ---------------------------------------------------------------- 牌桌上的叙述
def announce_battle(ctx, B):
    G = ctx.G
    En = ENEMIES[B['eid']]
    ctx.say('')
    if B['kind'] == 'boss':
        ctx.say(S.BOSS_ENTER)
        journal_add(G, '梦魇', S.BOSS_ENTER)
    elif B['kind'] == 'ambush':
        ctx.say('这间房间看起来平静，可是门一关上，%s就从暗处走了出来！' % En['name'])
    elif B['kind'] == 'echo':
        ctx.say('地板一块一块往下掉，你跟着掉进了另一层梦里。')
    ctx.say('⚔ %s · %s（血 %d）' % (KIND_NAMES.get(B['kind'], '作战'), En['name'], B['foeHp']))
    ctx.say(En['line'])
    if En.get('taunt'):
        ctx.say(En['taunt'])
    if B['kind'] != 'boss':
        ctx.say(douji_line('battle'))
    for src, cid in B.get('tempGot') or []:
        ctx.say('%s给了你一张临时王牌：「%s」（这一场用完就没了）。' % (src, CARDS[cid]['name']))
    if B['bonus'].get('douji'):
        ctx.say('（照过镜子的斗鸡士气正旺：这一场多出招 %d 次。）' % B['bonus']['douji'])
    if B['chase']:
        ctx.say('（追逐梦：每一局都是对方先出手。）')
    narrate_round_start(ctx, B, first=True)
    if not ctx.meta['tips'].get('battle'):
        ctx.meta['tips']['battle'] = True
        ctx.say('', S.TIP_BATTLE)


def narrate_round_start(ctx, B, first=False):
    ctx.say('', '—— 第 %d 局 ——' % B['round'])
    for m in B['msgs']:
        ctx.say(m)
    if B['drew']:
        ctx.say('你从牌盒里抽到了：%s。' % '、'.join('「%s」' % CARDS[c['id']]['name'] for c in B['drew']))
    elif not B['noBag'] and len(B['hand']) >= HAND_MAX:
        ctx.say('（手里已经有 %d 张王牌，这一局没有再抽。）' % HAND_MAX)


def narrate_foe(ctx, B, acts):
    name = ENEMIES[B['eid']]['name']
    for a in acts:
        if a['t'] == 'foeHit' and not a.get('msg'):
            ctx.say('%s要了一张牌：%d。' % (name, a['c']['v']))
        elif a['t'] == 'foeStand':
            ctx.say('%s停牌了。' % name)
        else:
            ctx.say(a.get('msg', ''))


def narrate_result(ctx, B, res):
    G = ctx.G
    name = ENEMIES[B['eid']]['name']
    T = res['T']
    ty, tf = res['ty'], res['tf']

    def line(who, side, tot):
        up = cards_text(side['up'])
        return '  %s：暗牌 %d%s = %d%s' % (who, side['down']['v'], (' + ' + ' + '.join(str(c['v']) for c in side['up'])) if side['up'] else '',
                                       tot, '（爆了）' if tot > T else '')

    ctx.say('', '【亮牌】目标 %d' % T)
    ctx.say(line('你', B['you'], ty))
    ctx.say(line(name, B['foe'], tf))
    o = res['o']
    if res['pounce']:
        ctx.say('→ 斗鸡把对方的牌啄得满天飞！这一局算你赢。%s掉了 %d 点血（剩 %d/%d）。' % (name, res['dmg'], res.get('foeLeft', B['foeHp']), B['foeMax']))
    elif o == 'win':
        why = ''
        if ty > T and tf > T:
            why = '两边都爆了，你爆得少。'
        elif tf > T:
            why = '%s爆了。' % name
        else:
            why = '你离 %d 更近。' % T
        if B['eid'] == 'box':
            ctx.say('→ 这一局你赢了：%s丝带还剩 %d 条。' % (why, B['gift']['r']))
        else:
            ctx.say('→ 这一局你赢了：%s%s掉了 %d 点血（剩 %d/%d）。' % (why, name, res['dmg'], res.get('foeLeft', B['foeHp']), B['foeMax']))
    elif o == 'lose':
        if ty > T and tf > T:
            why = '两边都爆了，你爆得多。'
        elif ty > T:
            why = '你爆了。'
        else:
            why = '%s离 %d 更近。' % (name, T)
        if res['dmg']:
            ctx.say('→ 这一局输了：%s你掉了 %d 点血（血 %d/%d）。' % (why, res['dmg'], max(0, G['hp']), G['maxHp']))
        else:
            ctx.say('→ 这一局输了：%s不过你一点血也没掉。' % why)
    else:
        ctx.say('→ 平局，谁也没有掉血。')
    for n in res['notes']:
        ctx.say('· ' + n)
    drain_inbox(ctx)
    if not B['end'] or B['end'] in ('won',):
        if o == 'win' and not res['pounce'] and E.rnd() < 0.5 and not B['end']:
            ctx.say(douji_line('win'))
        elif o == 'lose' and res['dmg'] and G['hp'] > 0:
            ctx.say(douji_line('low') if G['hp'] <= 2 else douji_line('hurt'))
        elif o == 'tie' and E.rnd() < 0.4:
            ctx.say(douji_line('tie'))


def finish_battle(ctx, B):
    G = ctx.G
    name = ENEMIES[B['eid']]['name']
    end = B['end']
    if B['kind'] == 'echo':
        if end == 'lost':
            ctx.say('', '眼前一黑……')
        elif end == 'won':
            ctx.say('', '倒影碎成了一地的光。你回过神来，发现自己已经站在下一层了。')
        else:
            ctx.say('', '倒影冲你笑了笑，慢慢淡去。地板又塌了一块，你跟着掉进了下一层。')
    elif end == 'won':
        if B['kind'] == 'boss':
            ctx.say('', '雾猛地一缩。')
        elif B['eid'] == 'box':
            ctx.say('', '丝带散开了！')
        else:
            ctx.say('', '%s倒下了。' % name)
        if B['kind'] != 'boss':
            last_res = B.get('res') or {}
            by_douji = last_res.get('pounce') or last_res.get('counter') or last_res.get('o') != 'win'
            ctx.say(douji_line('victory_douji' if by_douji else 'victory'))
    elif end == 'escaped':
        ctx.say('', '四局过去了。小梦魇飘走了……')
    elif end == 'boxfail':
        ctx.say('', '四局过去了，丝带还是没有散开。')
    elif end == 'lost':
        ctx.say('', '眼前一黑……')
    E.end_battle(G)


def run_battle(ctx):
    """把战斗推进到需要你做决定的地方，或者战斗结束。"""
    G = ctx.G
    guard = 0
    while G.get('battle') and guard < 300:
        guard += 1
        B = G['battle']
        if not B.get('announced'):
            B['announced'] = True
            announce_battle(ctx, B)
            continue
        if B['phase'] == 'play' and B['turn'] == 'foe':
            narrate_foe(ctx, B, E.foe_turn(G, B))
            continue
        if B['phase'] == 'reveal':
            jc = E.junk_count(G)
            narrate_result(ctx, B, E.resolve_round(G, B))
            if E.junk_count(G) > jc and G['hp'] > 0:
                ctx.say(douji_line('junk'))
            continue
        if B['phase'] == 'result':
            if B['end']:
                finish_battle(ctx, B)
                continue
            E.start_round(G, B)
            narrate_round_start(ctx, B)
            continue
        break


# ================================================================ 菜单（各种需要你做选择的时刻）
def opt(label, tip='', why=None, act=None):
    return {'label': label, 'tip': tip, 'why': why, 'act': act}


def _close(ctx):
    E.close_pending(ctx.G)


def menu_reward(ctx, p):
    G = ctx.G
    rw = p['rw']
    body = []
    if rw['coins']:
        body.append('拿到 %d 糖霜币。' % rw['coins'])
    body += ['· ' + n for n in rw['notes']]
    opts = []

    def take_relic(rid):
        def act(ctx):
            E.gain_relic(G, rid)
            ctx.say('收下了「%s」。' % RELICS[rid]['name'])
            _close(ctx)
        return act

    def take_item(c):
        def act(ctx):
            E.add_item(G, c['kind'], c['id'])
            ctx.say('「%s」%s。' % (E.item_name(c), '放进了牌盒' if c['kind'] == 'card' else '放进了行李箱'))
            if E.over_cap(G):
                ctx.say('！行李箱塞不下了：丢掉或用掉一件才能继续走。')
            _close(ctx)
        return act

    def skip(ctx):
        ctx.say('你什么也没拿。')
        _close(ctx)

    if rw['relics']:
        body.append('挑一件藏品带走（藏品一直生效）：')
        for rid in rw['relics']:
            opts.append(opt('%s（藏品·%s）' % (RELICS[rid]['name'], RARITY[RELICS[rid]['t']]), RELICS[rid]['desc'], act=take_relic(rid)))
        opts.append(opt('都不要', act=skip))
    elif rw['choices']:
        is_cards = rw['choices'][0]['kind'] == 'card'
        body.append('挑一张王牌放进牌盒：' if is_cards else '挑一件放进行李箱（现在 %d/%d 格）：' % (len(G['luggage']), E.luggage_cap(G)))
        for c in rw['choices']:
            opts.append(opt(item_line(c), E.item_desc(c), act=take_item(c)))
        opts.append(opt('都不要', act=skip))
    else:
        opts.append(opt('好', act=lambda ctx: _close(ctx)))
    return {'title': '赢了 · 战利品', 'body': body, 'options': opts}


def menu_treasure(ctx, p):
    G = ctx.G
    r = E.cur_room(G)
    opts = []

    def take(rid):
        def act(ctx):
            E.gain_relic(G, rid)
            ctx.say('收下了「%s」。' % RELICS[rid]['name'])
            _close(ctx)
        return act

    for rid in r['data']['relics']:
        opts.append(opt('%s（藏品·%s）' % (RELICS[rid]['name'], RARITY[RELICS[rid]['t']]), RELICS[rid]['desc'],
                        why='你已经有了' if E.has_relic(G, rid) else None, act=take(rid)))
    opts.append(opt('不拿了', act=lambda ctx: (ctx.say('你把它们留在了原地。'), _close(ctx))))
    return {'title': '遗落的宝物', 'sub': '只能拿走一件', 'body': [ROOMS['treasure']['desc']], 'options': opts}


def stock_name(G, s):
    hidden = s['hidden'] and G['luc'] < 7 and not s['sold']
    kind = {'card': '王牌', 'candle': '蜡烛', 'door': '门', 'bell': '铃铛', 'relic': '藏品'}[s['kind']]
    if hidden:
        return '看不清的%s' % kind, '清醒值到 7 才看得清。买下来就知道了。'
    return '%s（%s）' % (E.item_name(s), kind), E.item_desc(s)


def menu_shop(ctx, p):
    G = ctx.G
    r = E.cur_room(G)
    dream = r['type'] == 'dshop'
    title = ROOMS[r['type']]['name']
    sub = '你有 %d 糖霜币' % G['coins']
    if r['data'].get('closed'):
        return {'title': title, 'sub': '货架空了，行商不见了。', 'body': ['地上只留下一枚糖霜币大小的脚印。'],
                'options': [opt('离开', act=lambda ctx: _close(ctx))]}
    mode = p.get('mode')
    opts = []
    body = []
    if mode == 'sell':
        body.append('用过的东西卖不回原价，只能拿回三成多。纪念品卖不出去，只能付钱请行商处理掉。')
        for it in [x for x in G['luggage'] if E.is_junk(x)]:
            J = JUNK[it['id']]

            def dispose(u=it['u'], nm=E.item_name(it)):
                def act(ctx):
                    why = E.shop_dispose(G, u)
                    if why:
                        raise GameError(why)
                    ctx.say('「%s」被送走了。行李箱轻了一点。' % nm)
                return act
            opts.append(opt((J['btn'] % E.item_name(it)) + '（纪念品）', '付 %d 糖霜币' % J['fee'],
                            why=None if G['coins'] >= J['fee'] else '糖霜币不够', act=dispose()))
        for it in E.real_luggage(G):
            def sell(u=it['u'], nm=E.item_name(it), pr=E.sell_price(it)):
                def act(ctx):
                    why = E.shop_sell(G, u)
                    if why:
                        raise GameError(why)
                    ctx.say('卖掉了「%s」，拿到 %d 糖霜币。' % (nm, pr))
                return act
            opts.append(opt('卖掉「%s」（行李箱）' % E.item_name(it), '+%d 糖霜币' % E.sell_price(it), act=sell()))
        for it in G['cards']:
            def sellc(u=it['u'], nm=E.item_name(it), pr=E.sell_price(it)):
                def act(ctx):
                    why = E.shop_sell(G, u)
                    if why:
                        raise GameError(why)
                    ctx.say('卖掉了「%s」，拿到 %d 糖霜币。' % (nm, pr))
                return act
            opts.append(opt('卖掉「%s」（牌盒）' % E.item_name(it), '+%d 糖霜币' % E.sell_price(it),
                            why=None if len(G['cards']) > 3 else '牌盒里至少要留 3 张', act=sellc()))
        for rid in G['relics']:
            def sellr(rid=rid):
                def act(ctx):
                    why = E.sell_relic(G, rid)
                    if why:
                        raise GameError(why)
                    ctx.say('卖掉了「%s」，拿到 %d 糖霜币。' % (RELICS[rid]['name'], E.sell_price({'kind': 'relic', 'id': rid})))
                return act
            opts.append(opt('卖掉「%s」（藏品）' % RELICS[rid]['name'], '+%d 糖霜币' % E.sell_price({'kind': 'relic', 'id': rid}),
                            why='纪念品太多，卖不掉' if E.bag_loss_blocked(G, rid) else None, act=sellr()))
        opts.append(opt('返回货架', act=lambda ctx: p.pop('mode', None)))
        return {'title': title + ' · 卖东西', 'sub': sub, 'body': body, 'options': opts, 'shifty': True}
    if mode == 'steal':
        body.append('他在打瞌睡。挑一件顺走：成功率 %s；被抓到的话，要和他打一场（他有 4 点血）。只能试一次。'
                    % ('六成' if G['luc'] >= 5 else '四成五'))
        for i, s in enumerate(r['data']['stock']):
            if s['sold']:
                continue
            nm, desc = stock_name(G, s)

            def steal(i=i):
                def act(ctx):
                    out = E.try_steal(G, i)
                    if not out['ok']:
                        raise GameError(out['why'])
                    if out['got']:
                        ctx.say('他没醒。你把「%s」揣进了口袋。' % E.item_name(out['item']))
                        p.pop('mode', None)
                    else:
                        ctx.say('他睁开了眼睛。')
                return act
            opts.append(opt('顺走「%s」' % nm, desc, act=steal()))
        opts.append(opt('算了，回到货架前', act=lambda ctx: p.pop('mode', None)))
        return {'title': title + ' · 顺手牵羊', 'sub': sub, 'body': body, 'options': opts}
    body.append('货架上的东西都蒙着一层雾，像是还没被梦完。' if dream else '「随便看。看中了就拿钱来。要不然，你也可以试试别的办法。」')
    if E.junk_count(G):
        body.append('你的行李箱里有 %d 件纪念品。到「卖东西」里，可以付钱请行商处理掉。' % E.junk_count(G))
    mult = E.price_mult(G)
    for i, s in enumerate(r['data']['stock']):
        nm, desc = stock_name(G, s)
        if s['sold']:
            opts.append(opt('（已经没了）%s' % nm, '', why='已经没了', act=None))
            continue
        price = E.jsround(s['price'] * mult)

        def buy(i=i):
            def act(ctx):
                why = E.shop_buy(G, i)
                if why:
                    raise GameError(why)
                ctx.say('买下了「%s」。' % E.item_name(r['data']['stock'][i]))
                if E.over_cap(G):
                    ctx.say('！行李箱塞不下了：丢掉或用掉一件才能继续走。')
            return act
        opts.append(opt('买「%s」 · %d 糖霜币' % (nm, price), desc, why=None if G['coins'] >= price else '糖霜币不够', act=buy()))
    svc = r['data'].get('svc', {})
    lp, hp = E.service_price(G, 'luc'), E.service_price(G, 'heal')

    def service(what):
        def act(ctx):
            why = E.shop_service(G, what)
            if why:
                raise GameError(why)
            ctx.say('清醒 +1。' if what == 'luc' else '回复了 1 点血。')
        return act

    why = '糖霜币不够' if G['coins'] < lp else ('清醒值已经满了' if G['luc'] >= 7 else ('这一样卖完了' if svc.get('luc', 0) >= 2 else None))
    opts.append(opt('买一小瓶清醒 · %d 糖霜币' % lp, '清醒 +1（现在 %d/7），这里最多卖 2 瓶' % G['luc'], why=why, act=service('luc')))
    if not dream:
        why = '糖霜币不够' if G['coins'] < hp else ('你的血是满的' if G['hp'] >= G['maxHp'] else ('这一样卖完了' if svc.get('heal', 0) >= 2 else None))
        opts.append(opt('买一块软糖 · %d 糖霜币' % hp, '回复 1 点血，这里最多卖 2 块', why=why, act=service('heal')))
    opts.append(opt('卖东西 / 处理纪念品', act=lambda ctx: p.__setitem__('mode', 'sell')))
    if not dream and not r['data'].get('stole'):
        opts.append(opt('趁他打瞌睡，顺走一件……', '只能试一次，被抓到要打一场', act=lambda ctx: p.__setitem__('mode', 'steal')))
    opts.append(opt('离开', act=lambda ctx: (ctx.say('你离开了%s。' % title), _close(ctx))))
    return {'title': title, 'sub': sub, 'body': body, 'options': opts, 'shifty': True}


def menu_event(ctx, p):
    G = ctx.G
    r = E.cur_room(G)
    ev = EVENTS[r['data']['ev']]
    opts = []
    for orig, c in visible_choices(G, ev):
        tip = c.get('tip')
        tip = tip(G) if callable(tip) else (tip or '')
        if c.get('reveal') and G['luc'] >= 7:
            tip = '清醒值满了，你看得清：' + c['reveal'](G, r)
        why = c['need'](G) if c.get('need') else None

        def act(orig=orig):
            def run(ctx):
                out = event_choose(G, orig)
                if out.get('why'):
                    raise GameError(out['why'])
                ctx.say('→ ' + out.get('text', ''))
                journal_add(G, '不期而遇 · ' + ev['title'], ev['text'] + '\n→ ' + out.get('text', ''))
                if out.get('battle'):
                    G['pending'] = None
                    E.start_battle(G, out['battle']['eid'], out['battle']['kind'])
                else:
                    _close(ctx)
            return run
        opts.append(opt(c['label'], tip, why=why, act=act()))
    return {'title': '不期而遇 · ' + ev['title'], 'body': [ev['text']], 'options': opts}


def menu_rest(ctx, p):
    G = ctx.G
    opts = []
    labels = [('小睡一会儿', '回复 3 点血'), ('发会儿呆', '清醒 +1'), ('数星星', '时长 +1')]
    for i, (lb, tip) in enumerate(labels):
        if i == 2 and G['map']['kind'] == 'final':
            continue

        def act(i=i):
            def run(ctx):
                ctx.say(E.rest_choose(G, i))
                if i == 0:
                    ctx.say(E.pick(S.DOUJI_LINES['rest']))
                _close(ctx)
            return run
        opts.append(opt(lb, tip, act=act()))
    return {'title': '安全的角落', 'sub': '只能选一样', 'body': [ROOMS['rest']['desc']], 'options': opts}


def menu_wish(ctx, p):
    G = ctx.G
    opts = []
    for w in E.WISHES:
        def act(w=w):
            def run(ctx):
                ctx.say(w['run'](G))
                _close(ctx)
            return run
        opts.append(opt(w['label'], w['tip'], act=act()))
    return {'title': '得偿所愿', 'sub': '许一个愿', 'body': [ROOMS['wish']['desc']], 'options': opts}


def menu_swap(ctx, p):
    G = ctx.G
    mode = p.get('mode', 0)
    if mode == 2:
        items = E.real_luggage(G) + G['cards']
        body = ['挑两件投进去：choose <编号> <编号>，例如 choose 1 3。纪念品不收。']
        opts = [opt('%s（%s）' % (E.item_name(it), '牌盒' if it['kind'] == 'card' else '行李箱'), E.item_desc(it), act='pick:%s' % it['u'])
                for it in items]
        opts.append(opt('再想想（回到贩卖机前）', act=lambda ctx: p.__setitem__('mode', 0)))
        return {'title': '失与得 · 投进两件东西', 'body': body, 'options': opts, 'multi': 2,
                'hint': '用 %s choose <编号> <编号> 一次挑两件；或者选最后一项回去。' % CMD}
    if mode == 3:
        body = ['挑一件藏品投进去，换 3 件随机工具：']
        opts = []
        for rid in G['relics']:
            def act(rid=rid):
                def run(ctx):
                    out = E.swap_do(G, 3, rid)
                    if out.get('why'):
                        raise GameError(out['why'])
                    ctx.say(out['text'])
                    if E.over_cap(G):
                        ctx.say('！行李箱塞不下了：丢掉或用掉一件才能继续走。')
                    _close(ctx)
                return run
            opts.append(opt(RELICS[rid]['name'], RELICS[rid]['desc'], act=act()))
        opts.append(opt('再想想（回到贩卖机前）', act=lambda ctx: p.__setitem__('mode', 0)))
        return {'title': '失与得 · 投进一件藏品', 'body': body, 'options': opts}
    opts = []
    for i, o in enumerate(E.swap_options(G)):
        def act(i=i):
            def run(ctx):
                if i in (2, 3):
                    p['mode'] = i
                    return
                out = E.swap_do(G, i)
                if out.get('why'):
                    raise GameError(out['why'])
                ctx.say(out['text'])
                _close(ctx)
            return run
        opts.append(opt(o['label'], o['tip'], why=o['need'], act=act()))
    opts.append(opt('什么也不换，离开', '贩卖机会关掉', act=lambda ctx: (ctx.say('贩卖机咔哒一声，熄了灯。'), _close(ctx))))
    return {'title': '失与得', 'sub': '只能换一次', 'body': [ROOMS['swap']['desc']], 'options': opts}


def menu_agency(ctx, p):
    G = ctx.G
    M = ctx.meta
    L = M['locker']
    body = ['安娜：「要寄存什么吗？寄在我这儿的东西，下一次你入梦的时候会直接交给你。就算这一次醒了，也不会丢。」',
            '保管箱（%d/3）：%s' % (len(L), '、'.join(E.item_name(x) for x in L) if L else '空的'),
            '你有 %d 糖霜币。' % G['coins']]
    has_bell = any(x['kind'] == 'bell' for x in G['luggage'])
    body.append('招募和进阶都要用掉 1 只呼救铃（你%s），招募还要 30 糖霜币。最多同时带 3 个伙伴，斗鸡不算。' % ('有' if has_bell else '还没有'))
    opts = []
    for it in E.real_luggage(G) + G['cards']:
        why = None
        if len(L) >= 3:
            why = '保管箱满了'
        elif G['coins'] < 15:
            why = '糖霜币不够'
        elif it['kind'] == 'card' and len(G['cards']) <= 3:
            why = '牌盒里至少要留 3 张'

        def dep(u=it['u'], nm=E.item_name(it)):
            def run(ctx):
                why = E.deposit_item(G, M, u)
                if why:
                    raise GameError(why)
                ctx.say('安娜把「%s」收进了保管箱。下一次入梦时会交给你。' % nm)
            return run
        opts.append(opt('寄存「%s」（%s）· 15 糖霜币' % (E.item_name(it), '牌盒' if it['kind'] == 'card' else '行李箱'), '', why=why, act=dep()))

    def depc(ctx):
        why = E.deposit_coins(G, M)
        if why:
            raise GameError(why)
        ctx.say('安娜把 30 糖霜币收进了保管箱。')
    opts.append(opt('寄存 30 糖霜币 · 一共花 40（手续费 10）', '', why='保管箱满了' if len(L) >= 3 else ('糖霜币不够' if G['coins'] < 40 else None), act=depc))
    for pid in ['douji', 'tin', 'ballet', 'bear', 'rabbit']:
        P = PALS[pid]
        mine = next((x for x in G['pals'] if x['id'] == pid), None)
        if mine:
            if mine['lv'] >= 2:
                continue

            def up(pid=pid):
                def run(ctx):
                    why = E.upgrade_pal(G, pid)
                    if why:
                        raise GameError(why)
                    ctx.say('%s进阶了：%s' % (PALS[pid]['name'], PALS[pid]['up']))
                    if pid == 'douji':
                        ctx.say(douji_line('upgrade'))
                return run
            opts.append(opt('给%s进阶（用掉 1 只呼救铃）' % P['name'], '进阶后：' + P['up'], why=None if has_bell else '没有呼救铃', act=up()))
        else:
            why = '没有呼救铃' if not has_bell else ('伙伴已经有 3 个了' if E.pal_count(G) >= 3 else ('糖霜币不够' if G['coins'] < 30 else None))

            def rec(pid=pid):
                def run(ctx):
                    why = E.recruit_pal(G, pid)
                    if why:
                        raise GameError(why)
                    ctx.say('%s加入了。' % PALS[pid]['name'])
                return run
            opts.append(opt('招募%s（呼救铃 + 30 糖霜币）' % P['name'], '%s：%s每场 %d 次。' % (P['skill'], P['desc'], P['uses'][0]), why=why, act=rec()))
    opts.append(opt('离开', act=lambda ctx: (ctx.say('安娜冲你挥了挥手。'), _close(ctx))))
    return {'title': '代理办事处', 'body': body, 'options': opts, 'shifty': True}


def menu_hole(ctx, p):
    G = ctx.G

    def go(ctx):
        why = E.enter_hole(G)
        if why:
            raise GameError(why)
        ctx.say('你深吸一口气，钻进了洞里。斗鸡紧紧扒着你的肩膀。')
    return {'title': '兔子洞', 'sub': '要钻进去吗', 'body': [ROOMS['hole']['desc'], '那边有自己的 4 时长，这边的时长不会变。'],
            'options': [opt('钻进去', '清醒 -1', why=None if G['luc'] >= 1 else '清醒值不够', act=go),
                        opt('不了', '这个洞会合上', act=lambda ctx: (ctx.say('洞口慢慢合上了。'), _close(ctx)))]}


def menu_well(ctx, p):
    G = ctx.G

    def jump(ctx):
        G['pending'] = None
        ctx.say('你抱紧灯，跳了下去。风在耳边呼呼地响。斗鸡紧紧扒住你的肩膀：「抓稳了！本鸡在！」')
        E.go_next_floor(G, 'well')
    forced = p.get('forced') or G['map']['time'] <= 0
    opts = [opt('跳下去', act=jump)]
    if not forced:
        opts.append(opt('不了', '以后回到这里，用 enter 再跳', act=lambda ctx: _close(ctx)))
    return {'title': '先行一步', 'sub': '时长用完了，只能跳下去' if forced else '直接去下一层',
            'body': [ROOMS['well']['desc'], '跳下去不用找楼梯，但剩下的时长不会照亮下一层，也没法在楼梯上喘口气。'],
            'options': opts}


def menu_stairs(ctx, p):
    G = ctx.G
    m = G['map']
    lift = p['type'] == 'lift'
    t = m['time']
    forced = p.get('forced') or t <= 0
    nxt = E.FLOORS[G['floor']]['name'] if G['floor'] < 6 else ''
    if G['floor'] >= 5:
        text = ('乘电梯下去：能拿到 1 件藏品和 1 扇稀有的门。' if lift else '走下楼梯：走楼梯的时候，你还能喘口气，回复 1 点血。') + \
               '下面是最后一层，没有时长限制，所有房间都看得清。'
    elif lift:
        text = '乘电梯下去：剩下的 %d 时长会跟着你带到下一层，还能拿到 1 件藏品和 1 扇稀有的门。' % t
    else:
        text = '走下楼梯：剩下的 %d 时长会照亮下一层的 %d 个房间。走楼梯的时候，你还能喘口气，回复 1 点血。' % (t, t)

    def go(ctx):
        G['pending'] = None
        ctx.say('你%s。' % ('走进电梯，按下了唯一的那个按钮' if lift else '提着灯，一级一级走了下去'))
        ctx.say(douji_line('descend'))
        E.go_next_floor(G, 'lift' if lift else 'stairs')
    opts = [opt('乘电梯' if lift else '走下去', act=go)]
    if not forced:
        opts.append(opt('再逛逛', '以后回到这里，用 enter 再下楼', act=lambda ctx: _close(ctx)))
    return {'title': '电梯间' if lift else '楼梯间', 'sub': '时长用完了，只能往下走' if forced else '下面是「%s」' % nxt,
            'body': [text], 'options': opts}


def menu_vent(ctx, p):
    G = ctx.G
    opts = []
    tg = E.vent_targets(G)
    for k in sorted(tg, key=lambda k: (E.manhattan(k, G['map']['cur']), k)):
        def go(k=k):
            def run(ctx):
                G['pending'] = None
                ctx.say('你钻进管道，爬啊爬，从 %s 的通风口探出了头。' % coord(k))
                out = E.use_vent(G, k)
                if not out['ok']:
                    raise GameError(out['why'])
                drain_inbox(ctx)
            return run
        opts.append(opt('钻到 %s：%s' % (coord(k), room_label(G, k)), '花 2 时长', why=None if G['map']['time'] >= 2 else '时长不够（要 2）', act=go()))
    opts.append(opt('不了', act=lambda ctx: _close(ctx)))
    return {'title': '通风管道', 'sub': '能反复用', 'body': [ROOMS['vent']['desc']], 'options': opts}


def menu_collapse(ctx, p):
    G = ctx.G

    def sit(ctx):
        G['pending'] = None
        E.start_battle(G, 'echo', 'echo')
    return {'title': '坍塌 · 梦中梦',
            'body': ['时长用完了。地板一块块往下掉，你跟着掉进了另一层梦里。',
                     '有一个人在那里等你，长得和你一模一样。',
                     '和倒影打一局，平局重来。输了掉 1 点血。不管输赢，醒来都会到下一层，只是那一层的时长会少 1。行李箱在梦中梦里打不开，只有斗鸡叫得醒。'],
            'options': [opt('坐下', act=sit)]}


def story_body(G, st):
    if st['kind'] == 'main':
        ch = S.MAIN_CHAPTERS[st['id']]
    else:
        ch = S.SIDE_STORIES[st['id']]
    body = [S.STORY_OPEN_DOUJI if ch.get('teller') == 'douji' else S.STORY_OPEN, '',
            '《%s》（%s）' % (ch['title'], ch['tag']), '', ch['text'], '', ch['end']]
    if ch.get('douji'):
        body.append(ch['douji'])
    if st.get('piece') is not None:
        body += ['', S.PIECE_HANDOUT[st['piece']], '纸条上写着：「%s」' % S.LETTER_LINES[st['piece']],
                 '（这是你名签那封信上掉下来的一行。信的碎片：第 %d 行）' % (st['piece'] + 1)]
    return ch, body


def menu_story(ctx, p):
    G = ctx.G
    st = E.story_for_room(G, ctx.meta)
    ch, body = story_body(G, st)
    by_douji = ch.get('teller') == 'douji'
    labels = S.STORY_CHOICES_DOUJI if by_douji else S.STORY_CHOICES
    opts = []
    for i in range(2):
        def act(i=i):
            def run(ctx):
                journal_add(G, '故事会 · 《%s》' % ch['title'], '\n'.join(body[2:]))
                ctx.say(E.finish_story(G, ctx.meta, i))
                _close(ctx)
            return run
        opts.append(opt(labels[i], S.STORY_TIPS[i], act=act()))
    return {'title': '故事会', 'body': body, 'options': opts}


def menu_finale(ctx, p):
    G = ctx.G
    k = len(G['letter'])
    body = [S.FINALE, '', '你口袋里的信的碎片：%d/5。' % k]

    def choose_end(i):
        def run(ctx):
            ending = E.finale_choose(G, ctx.meta, i)
            G['recorded'] = True
            title, text = ending_text(G, ending)
            journal_add(G, title, text)
            ctx.say('', DOUBLE, title, DOUBLE, text, '')
            ctx.say(end_stats(G))
            ctx.say('', '这一场梦结束了。你见过的结局：%s。' % '、'.join(S.ENDINGS[e]['title'] for e in ctx.meta['endings']))
            ctx.say('想再做一次梦，用：%s new <伙伴> [深浅]' % CMD)
            ctx.show_view = False
        return run
    tip0 = '你有 %d/5 行字' % k
    return {'title': '梦的尽头', 'body': body,
            'options': [opt(S.FINALE_CHOICES[0], tip0, act=choose_end(0)), opt(S.FINALE_CHOICES[1], '', act=choose_end(1))]}


MENUS = {
    'reward': menu_reward, 'treasure': menu_treasure, 'shop': menu_shop, 'dshop': menu_shop, 'event': menu_event,
    'rest': menu_rest, 'wish': menu_wish, 'swap': menu_swap, 'agency': menu_agency, 'hole': menu_hole,
    'well': menu_well, 'stairs': menu_stairs, 'lift': menu_stairs, 'vent': menu_vent, 'collapse': menu_collapse,
    'story': menu_story, 'finale': menu_finale,
}


def build_menu(ctx):
    p = ctx.G['pending']
    fn = MENUS.get(p['type'])
    if not fn:
        return None
    return fn(ctx, p)


def view_menu(ctx):
    G = ctx.G
    menu = build_menu(ctx)
    if not menu:
        view_map(ctx)
        return
    ctx.say(RULE, '【%s】%s' % (menu['title'], ('  ' + menu['sub']) if menu.get('sub') else ''))
    ctx.say(status_line(G))
    ctx.say('')
    for ln in menu.get('body', []):
        ctx.say(ln)
    ctx.say('')
    for i, o in enumerate(menu['options'], 1):
        s = '  [%d] %s' % (i, o['label'])
        if o['tip']:
            s += ' —— ' + o['tip']
        if o['why']:
            s += '（选不了：%s）' % o['why']
        ctx.say(s)
    ctx.say('', menu.get('hint') or '用 %s choose <编号> 做选择。' % CMD)
    if menu.get('shifty'):
        ctx.say('（每做一次买卖或寄存，编号都会重新排。请按最新这一屏的编号来选。）')


# ================================================================ 结局与醒来
def letter_block(G):
    return '\n'.join('    ' + (ln if i in G['letter'] else S.MISSING_LINE) for i, ln in enumerate(S.LETTER_LINES))


CN_NUM = ['零', '一', '两', '三', '四', '五']


def ending_text(G, ending):
    e = S.ENDINGS[ending]
    missing = 5 - len(G['letter'])
    if missing >= 5:
        lost = '信纸上一个字也不剩了：五行字，全都被雾吃掉了。'
        after = '你把空白的信纸按在胸口：「我下次来读。我保证。」'
    else:
        lost = '信纸上有%s行字已经被雾吃掉了。你一行一行往下读：' % CN_NUM[missing]
        after = '你把能读的都读完了。剩下的那%s行，空白得让人心疼。\n你把信纸按在胸口：「剩下的，我下次来读。我保证。」' % CN_NUM[missing]
    text = e['text'].replace('{letter}', letter_block(G)).replace('{lost}', lost).replace('{after}', after)
    return e['title'], text


def end_stats(G):
    st = G['stats']
    F = E.floor_info(G)
    return '这一场梦：走到了「%s」· 走过 %d 个房间 · 打赢 %d/%d 场牌局 · 信的碎片 %d/5 · 用了 %d 条命令' % (
        F['name'], st['rooms'], st['wins'], st['fights'], len(G['letter']), st.get('cmds', 0))


def record_wake(ctx):
    G = ctx.G
    if G.get('recorded'):
        return
    G['recorded'] = True
    st = ctx.meta['stats']
    st['wakes'] = st.get('wakes', 0) + 1
    st['best'] = max(st.get('best', 0), G['floor'])


def view_end(ctx):
    G = ctx.G
    if G.get('ending'):
        title, text = ending_text(G, G['ending'])
        ctx.say(DOUBLE, title, DOUBLE, text, '', end_stats(G))
    else:
        m = G['map']
        wake = S.WAKE[m['bonus']] if m['kind'] == 'bonus' else S.WAKE[min(6, max(1, G['floor']))]
        ctx.say(DOUBLE, '愕然惊醒', DOUBLE, wake, '', end_stats(G))
        if ctx.meta['locker']:
            ctx.say('安娜那里还替你保管着：%s。下一次入梦时会交给你。' % '、'.join(E.item_name(x) for x in ctx.meta['locker']))
    ctx.say('', '这一场梦结束了。想再做一次梦，用：%s new <伙伴> [深浅]（例：%s new 布偶熊 深梦）' % (CMD, CMD))


# ================================================================ 标题与开局
def view_title(ctx):
    M = ctx.meta
    st = M['stats']
    ctx.say(DOUBLE, S.TITLE, DOUBLE, S.TAGLINE, '')
    ctx.say('还没有开始做梦。开始的方法：', '  %s new <伙伴> [深浅]      例如：%s new 布偶熊 深梦' % (CMD, CMD), '')
    newrun_info(ctx)
    if st.get('runs'):
        best = E.FLOORS[max(1, min(6, st.get('best') or 1)) - 1]['name']
        ctx.say('', '做过 %d 次梦 · 最远走到「%s」 · 醒来 %d 次 · 走到梦的尽头 %d 次' % (st['runs'], best, st.get('wakes', 0), st.get('wins', 0)))
        if M['endings']:
            ctx.say('见过的结局：' + '、'.join(S.ENDINGS[e]['title'] for e in M['endings']))
    if M['locker']:
        ctx.say('安娜的保管箱：' + '、'.join(E.item_name(x) for x in M['locker']) + '（下一次入梦时交给你）')
    ctx.say('', '看全部命令：%s help　　看完整规则：%s rules' % (CMD, CMD))


def newrun_info(ctx):
    ctx.say('斗鸡每一次都会跟着你（不占伙伴名额）：',
            '  斗鸡 —— 三招共用，每场 3 次：飞扑（直接赢下这一局，对方多掉 1 血，你回 1 血）/ 护主（这局输了不掉血，对方还被反啄 1 血）/ 啄牌（叼走对方最后一张明牌）')
    ctx.say('再挑一个玩具伙伴：')
    for pid in START_PALS:
        P = PALS[pid]
        ctx.say('  %s —— %s：%s每场 %d 次。' % (P['name'], P['skill'], P['desc'], P['uses'][0]))
    ctx.say('梦的深浅（不写就是深梦）：')
    for k, d in DEPTHS.items():
        ctx.say('  %s —— %s' % (d['name'], d['note']))


def find_by_alias(table, q):
    nq = norm(q)
    for k, v in table.items():
        if nq == norm(k) or nq == norm(v.get('name', '')) or any(nq == norm(a) for a in v.get('alias', [])):
            return k
    return None


# ================================================================ 推进状态
def settle(ctx):
    G = ctx.G
    if not G:
        return
    for _ in range(50):
        if G.get('dead'):
            break
        p = G.get('pending')
        if p and p['type'] == 'floor':
            drain_inbox(ctx)
            show_floor_intro(ctx)
            G['pending'] = None
            E.after_room(G)
            continue
        if p and p['type'] == 'bonusIntro':
            drain_inbox(ctx)
            show_bonus_intro(ctx)
            G['pending'] = None
            E.after_room(G)
            continue
        if G.get('battle'):
            run_battle(ctx)
            if G.get('battle'):
                break
            continue
        break
    drain_inbox(ctx)
    if G.get('map') and not G.get('dead'):
        # 清醒值可能在房间里变了（藏品、事件、故事会），马上更新能看多远
        E.update_vis(G)
    if G.get('dead') and not G.get('won'):
        record_wake(ctx)


def show_floor_intro(ctx):
    G = ctx.G
    m = G['map']
    F = E.floor_info(G)
    text = S.FLOOR_TEXT[m['floor']]
    ctx.say('', DOUBLE, '%s · %s' % (F['label'], F['name']), DOUBLE, text)
    extra = []
    if m.get('dream'):
        D = DREAMS[m['dream']]
        extra.append('梦构 · %s［%s］：%s' % (D['name'], D['quote'], D['desc']))
    if m['kind'] == 'main':
        extra.append('这一层有 %d 时长。' % m['time'])
    elif m['kind'] == 'final':
        extra.append('这一层没有时长限制。梦魇在最里面等你。')
    if extra:
        ctx.say('', *extra)
    journal_add(G, '%s · %s' % (F['label'], F['name']), text)


def show_bonus_intro(ctx):
    G = ctx.G
    m = G['map']
    F = E.floor_info(G)
    text = S.BONUS_TEXT[m['bonus']]
    ctx.say('', DOUBLE, '兔子洞 · %s · %s' % (F['label'], F['name']), DOUBLE, text, '',
            '这里有自己的 %d 时长。用完了，洞口会把你吐回原来的房间。随时可以用 leave 爬出去。' % m['time'])
    journal_add(G, '兔子洞 · %s' % F['name'], text)


def show_view(ctx):
    G = ctx.G
    if not G:
        view_title(ctx)
    elif G.get('dead'):
        view_end(ctx)
    elif G.get('battle'):
        view_battle(ctx)
    elif G.get('pending'):
        view_menu(ctx)
    else:
        view_map(ctx)


# ================================================================ 命令
def need_run(ctx):
    G = ctx.G
    if not G:
        raise GameError('还没有开始做梦。用 %s new <伙伴> [深浅] 开始，例如 %s new 布偶熊 深梦。' % (CMD, CMD))
    if G.get('dead'):
        raise GameError('这一场梦已经结束了。用 %s new <伙伴> [深浅] 再做一次梦。' % CMD)
    return G


def need_map(ctx):
    G = need_run(ctx)
    if G.get('battle'):
        raise GameError('你正在牌桌上。先把这场打完：hit / stand / use / pal。用 %s status 看牌局。' % CMD)
    if G.get('pending'):
        raise GameError('眼前还有事情要处理（%s）。用 %s status 看看选项，再用 choose <编号> 选择。'
                        % (pending_name(G['pending']), CMD))
    return G


def need_turn(ctx):
    G = need_run(ctx)
    B = G.get('battle')
    if not B:
        raise GameError('现在不在牌桌上。用 %s status 看看现在能做什么。' % CMD)
    if B['phase'] != 'play' or B['turn'] != 'you':
        raise GameError('现在不是你的回合。')
    return G, B


def pending_name(p):
    return {'reward': '战利品', 'treasure': '遗落的宝物', 'shop': '诡异行商', 'dshop': '梦境行商', 'event': '不期而遇',
            'rest': '安全的角落', 'wish': '得偿所愿', 'swap': '失与得', 'agency': '代理办事处', 'hole': '兔子洞',
            'well': '先行一步', 'stairs': '楼梯间', 'lift': '电梯间', 'vent': '通风管道', 'collapse': '坍塌',
            'story': '故事会', 'finale': '梦的尽头'}.get(p['type'], p['type'])


def cmd_new(ctx, args):
    flags = {'force', '--force', '-f', '确认', 'confirm', 'yes'}
    force = any(a.lower() in flags for a in args)
    args = [a for a in args if a.lower() not in flags]
    G = ctx.G
    if G and not G.get('dead') and not force:
        raise GameError('现在还有一场梦没走完（%s）。要放弃它重新开始，在命令最后加 force，例如：%s new %s force'
                        % (floor_title(G), CMD, ' '.join(args) or '布偶熊 深梦'))
    if not args:
        ctx.say(DOUBLE, S.TITLE, DOUBLE, '开始的方法：%s new <伙伴> [深浅]，例如：%s new 布偶熊 深梦' % (CMD, CMD), '')
        newrun_info(ctx)
        ctx.show_view = False
        return
    pid = find_by_alias({k: PALS[k] for k in START_PALS}, args[0])
    if not pid:
        if find_by_alias({'douji': PALS['douji']}, args[0]):
            raise GameError('斗鸡每一次都会跟着你，不用选。再挑一个玩具伙伴：锡兵 / 芭蕾娃娃 / 布偶熊。')
        raise GameError('没有「%s」这个伙伴。可以选：锡兵 / 芭蕾娃娃 / 布偶熊。' % args[0])
    depth = ctx.meta.get('depth') or 'deep'
    if len(args) > 1:
        depth = find_by_alias(DEPTHS, args[1])
        if not depth:
            raise GameError('没有「%s」这种深浅。可以选：浅梦 / 深梦 / 噩梦。' % args[1])
    ctx.meta['lastPal'] = pid
    ctx.meta['depth'] = depth
    ctx.meta['stats']['runs'] = ctx.meta['stats'].get('runs', 0) + 1
    G = E.new_run(pid, ctx.meta, depth)
    ctx.G = G
    ctx.say(DOUBLE, '%s · %s' % (S.TITLE, S.PROLOGUE_TITLE), DOUBLE, S.PROLOGUE, '',
            '（这一场：伙伴是斗鸡和%s，梦的深浅是%s，开局 %d 点血。）' % (PALS[pid]['name'], DEPTHS[depth]['name'], G['hp']))
    journal_add(G, S.PROLOGUE_TITLE, S.PROLOGUE)


def cmd_status(ctx, args):
    pass  # 只要看局面：settle 之后自动显示


def cmd_map(ctx, args):
    G = need_run(ctx)
    if G.get('battle') or G.get('pending'):
        return
    # 正常显示地图


def cmd_go(ctx, args):
    G = need_map(ctx)
    if not args:
        raise GameError('要说明去哪个房间：go <房间>，例如 go %s。' % (coord(neighbor_list(G)[0][0]) if neighbor_list(G) else 'C5'))
    go_to(ctx, args[0])


def go_to(ctx, q):
    G = ctx.G
    m = G['map']
    k = parse_coord(q)
    if not k or k not in m['rooms'] or m['vis'].get(k, 0) < 1:
        raise GameError('「%s」不是一个你看得见的房间。房间的写法是「列字母 + 行数字」，例如 C5。' % q)
    if k == m['cur']:
        raise GameError('你已经在 %s 了。' % coord(k))
    c = E.can_move(G, k)
    if not c['ok']:
        raise GameError('去不了 %s：%s。' % (coord(k), c['why']))
    cost = '不花时长' if c['cost'] == 0 else '花了 %d 时长' % c['cost']
    E.do_move(G, k)
    # 兔子洞里的时长用完时，走进房间的同时会被吐回原来的地图
    label = room_label(G, k) if G['map'] is m else ROOMS[m['rooms'][k]['type']]['name']
    ctx.say('你走到了 %s（%s）：%s。' % (coord(k), cost, label))
    drain_inbox(ctx)  # 路上发生的事（蜡烛烧完之类）先说，再进房间
    p = G.get('pending')
    if p and p['type'] in ('shop', 'dshop') and E.rnd() < 0.5:
        ctx.say(douji_line('shop'))


def cmd_choose(ctx, args):
    G = need_run(ctx)
    if G.get('battle'):
        raise GameError('你正在牌桌上，这里没有选项。用 hit / stand / use / pal。')
    nums = []
    for a in args:
        for part in a.replace('，', ',').split(','):
            part = part.strip()
            if part:
                if not part.isdigit():
                    raise GameError('编号要写数字，例如 choose 1。')
                nums.append(int(part))
    if not nums:
        raise GameError('要写编号，例如 choose 1。')
    if not G.get('pending'):
        nb = neighbor_list(G)
        n = nums[0]
        if not 1 <= n <= len(nb):
            raise GameError('相邻的房间只有 %d 个（编号 1～%d）。' % (len(nb), len(nb)))
        go_to(ctx, coord(nb[n - 1][0]))
        return
    menu = build_menu(ctx)
    if not menu:
        raise GameError('现在没有可以选的东西。')
    opts = menu['options']
    if menu.get('multi'):
        if len(nums) == 1 and nums[0] == len(opts):
            opts[-1]['act'](ctx)
            return
        bad = [n for n in nums if not 1 <= n <= len(opts)]
        if bad:
            raise GameError('没有编号 %d。可以选 1～%d。' % (bad[0], len(opts)))
        if len(nums) != menu['multi'] or len(set(nums)) != len(nums):
            raise GameError('这里要一次挑 %d 件不一样的东西：choose <编号> <编号>，例如 choose 1 3。' % menu['multi'])
        us = []
        for n in nums:
            if not 1 <= n < len(opts):
                raise GameError('没有编号 %d。' % n)
            us.append(opts[n - 1]['act'].split(':', 1)[1])
        out = E.swap_do(G, 2, us)
        if out.get('why'):
            raise GameError(out['why'])
        ctx.say(out['text'])
        E.close_pending(G)
        return
    if len(nums) > 1:
        raise GameError('这里一次只能选一个：choose <编号>。')
    n = nums[0]
    if not 1 <= n <= len(opts):
        raise GameError('没有编号 %d。可以选 1～%d。' % (n, len(opts)))
    o = opts[n - 1]
    if o['why']:
        raise GameError('选不了「%s」：%s。' % (o['label'], o['why']))
    if not o['act']:
        raise GameError('这一项不能选。')
    o['act'](ctx)


def cmd_hit(ctx, args):
    G, B = need_turn(ctx)
    ch = E.can_hit(G, B)
    if not ch['ok']:
        raise GameError('不能要牌：%s。' % ch['why'])
    c = E.you_hit(G, B)
    ctx.say('你要了一张牌：%d。现在一共 %d 点。' % (c['v'], E.total(B['you'])))


def cmd_stand(ctx, args):
    G, B = need_turn(ctx)
    cs = E.can_stand(G, B)
    if not cs['ok']:
        raise GameError('不能停牌：%s。' % cs['why'])
    E.you_stand(G, B)
    ctx.say('你停牌了（%d 点）。' % E.total(B['you']))


def find_hand(B, q):
    if q.isdigit():
        i = int(q)
        if 1 <= i <= len(B['hand']):
            return B['hand'][i - 1]
        return None
    nq = norm(q)
    exact = [it for it in B['hand'] if nq in (norm(CARDS[it['id']]['name']), norm(it['id'])) or nq in [norm(a) for a in CARDS[it['id']].get('alias', [])]]
    if exact:
        return exact[0]
    part = [it for it in B['hand'] if nq and nq in norm(CARDS[it['id']]['name'])]
    if len(part) == 1 or (part and all(p['id'] == part[0]['id'] for p in part)):
        return part[0]
    if part:
        raise GameError('「%s」能对上好几张：%s。写得更完整一点，或者用编号。' % (q, '、'.join(CARDS[p['id']]['name'] for p in part)))
    return None


def cmd_use(ctx, args):
    G, B = need_turn(ctx)
    if not args:
        raise GameError('要说明用哪一张：use <编号或名字>，例如 use 1。')
    if B['noBag']:
        raise GameError('梦中梦里，行李箱打不开，用不了王牌。')
    q = ''.join(args)
    it = find_hand(B, q)
    if not it:
        names = '、'.join('[%d] %s' % (i, CARDS[x['id']]['name']) for i, x in enumerate(B['hand'], 1)) or '没有'
        raise GameError('手里没有「%s」。你手里的王牌：%s。' % (q, names))
    name = CARDS[it['id']]['name']
    out = E.play_card(G, B, it)
    if not out['ok']:
        raise GameError('现在用不了「%s」：%s。' % (name, out['why']))
    ctx.say('你用了「%s」。%s' % (name, out['msg']))


def cmd_pal(ctx, args):
    G, B = need_turn(ctx)
    if not args:
        raise GameError('要说明请谁帮忙：pal 斗鸡 <飞扑/护主/啄牌>，或者 pal <伙伴名>。')
    pid = find_by_alias({p['id']: PALS[p['id']] for p in G['pals']}, args[0])
    if not pid:
        raise GameError('你的伙伴里没有「%s」。你的伙伴：%s。' % (args[0], pals_text(G)))
    pal = next(p for p in G['pals'] if p['id'] == pid)
    move = None
    if pid == 'douji':
        if len(args) < 2:
            raise GameError('斗鸡有三招，要说清楚用哪一招：pal 斗鸡 飞扑 / pal 斗鸡 护主 / pal 斗鸡 啄牌。')
        move = find_by_alias(DOUJI_MOVES, args[1])
        if not move:
            raise GameError('斗鸡没有「%s」这一招。三招是：飞扑 / 护主 / 啄牌。' % args[1])
    if pid == 'douji' and E.pal_left(G, B, pal) <= 0:
        raise GameError('斗鸡：「%s」' % S.DOUJI_LINES['out'][0])
    out = E.use_skill(G, B, pal, move)
    if not out['ok']:
        raise GameError('%s帮不了忙：%s。' % (PALS[pid]['name'], out['why']))
    name = ENEMIES[B['eid']]['name']
    if pid == 'douji':
        ctx.say(douji_line(move))
        if move == 'pounce':
            ctx.say('斗鸡一个飞扑跳上牌桌，张开翅膀，冲着%s的牌就是一顿乱啄！' % name)
        elif move == 'guard':
            ctx.say('斗鸡张开翅膀挡在你身前。这一局你输了不掉血；要是%s赢了，斗鸡会反啄它 1 点血。' % name)
            if out.get('blocked'):
                ctx.say(out['blocked'])
        elif move == 'peck':
            ctx.say('斗鸡一口叼走了%s的 %d，扔回了牌堆。%s现在的明牌：%s。' % (name, out['card']['v'], name, cards_text(B['foe']['up']) or '没有了'))
        if move != 'pounce':
            ctx.say('（斗鸡这一场还能出招 %d 次。）' % E.pal_left(G, B, pal))
    else:
        ctx.say(out['msg'])
        if out.get('peek'):
            cs = '；'.join('第 %d 张是 %d' % (i + 1, c['v']) for i, c in enumerate(out['peek']))
            ctx.say('牌堆顶：%s。要把哪一张塞到牌堆最底下，就用 bury <编号>（例如 bury 1）；不想塞就直接继续。' % cs)


def cmd_bury(ctx, args):
    G, B = need_turn(ctx)
    n = int(args[0]) if args and args[0].isdigit() else 1
    top = B['deck']['top']
    if not 1 <= n <= len(top) or top[n - 1]['u'] not in (B.get('peek') or []):
        raise GameError('你不知道牌堆第 %d 张是什么，没法塞。先请芭蕾娃娃看一眼：pal 芭蕾娃娃。' % n)
    c = top[n - 1]
    E.bury_card(B, c['u'])
    ctx.say('那张 %d 被塞到了牌堆最底下。' % c['v'])


def cmd_bag(ctx, args):
    G = need_run(ctx)
    ctx.show_view = False
    ctx.say(RULE, '【随身的东西】', status_line(G), '')
    ctx.say('行李箱（%d/%d 格）：' % (len(G['luggage']), E.luggage_cap(G)))
    if not G['luggage']:
        ctx.say('  （空的）')
    for i, it in enumerate(G['luggage'], 1):
        ctx.say('  [%d] %s —— %s' % (i, item_line(it), E.item_desc(it)))
    ctx.say('烛台：')
    for i in range(2):
        if i < len(G['lit']):
            c = G['lit'][i]
            C = CANDLES[c['id']]
            ctx.say('  %d. %s（还能烧 %d 步）—— 点着时：%s熄灭时：%s' % (i + 1, C['name'], c['left'], C['on'], C['off']))
        else:
            ctx.say('  %d. 空着' % (i + 1))
    ctx.say('这一层还能点 %d 次蜡烛。' % max(0, 2 - G['litFloor']))
    ctx.say('牌盒（%d 张，战斗里每局从这里抽王牌）：' % len(G['cards']))
    for i, it in enumerate(G['cards'], 1):
        ctx.say('  [%d] %s —— %s' % (i, item_line(it, False), E.item_desc(it)))
    ctx.say('藏品（一直生效）：')
    if not G['relics']:
        ctx.say('  （还没有）')
    for rid in G['relics']:
        ctx.say('  %s —— %s' % (RELICS[rid]['name'], RELICS[rid]['desc']))
    ctx.say('伙伴：')
    for p in G['pals']:
        P = PALS[p['id']]
        uses = E.pal_uses(G, p)
        if p['id'] == 'douji':
            ctx.say('  斗鸡%s —— 每场 %d 次，三招共用：' % ('（进阶）' if p['lv'] > 1 else '', uses))
            for mv in DOUJI_MOVES.values():
                ctx.say('      %s：%s' % (mv['name'], mv['desc']))
        else:
            ctx.say('  %s%s —— %s：%s每场 %d 次。%s' % (P['name'], '（进阶）' if p['lv'] > 1 else '', P['skill'],
                                                  P['desc'] if not (p['id'] == 'bear' and p['lv'] > 1) else '回复 2 点血。', uses,
                                                  '' if p['lv'] > 1 else '进阶后：' + P['up']))
    ctx.say('信的碎片（%d/5）：' % len(G['letter']))
    for i, ln in enumerate(S.LETTER_LINES):
        ctx.say('  第 %d 行：%s' % (i + 1, '「%s」' % ln if i in G['letter'] else '（还没找到）'))
    ctx.say('', '用 %s status 回到现在的局面。' % CMD)


def luggage_item(G, q, kinds=None):
    q = q.strip()
    if q.isdigit():
        i = int(q)
        if 1 <= i <= len(G['luggage']):
            return G['luggage'][i - 1]
        raise GameError('行李箱里没有编号 %s。' % q)
    nq = norm(q)
    for it in G['luggage']:
        if (kinds is None or it['kind'] in kinds) and nq == norm(E.item_name(it)):
            return it
    for it in G['luggage']:
        if (kinds is None or it['kind'] in kinds) and nq and nq in norm(E.item_name(it)):
            return it
    raise GameError('行李箱里没有「%s」。行李箱：%s' % (q, luggage_text(G)))


def cmd_light(ctx, args):
    G = need_map(ctx)
    if not args:
        raise GameError('要说明点哪一支：light <行李箱编号或名字>。行李箱：%s' % luggage_text(G))
    it = luggage_item(G, args[0], ('candle',))
    if it['kind'] != 'candle':
        raise GameError('「%s」不是蜡烛。' % E.item_name(it))
    why = E.light_candle(G, it['u'])
    if why:
        raise GameError(why)
    C = CANDLES[it['id']]
    ctx.say('你点燃了「%s」，把它放上烛台。点着时：%s（最多烧 %d 步）' % (C['name'], C['on'], C['max']))


def cmd_snuff(ctx, args):
    G = need_map(ctx)
    if not G['lit']:
        raise GameError('烛台上没有点着的蜡烛。')
    q = args[0] if args else ('1' if len(G['lit']) == 1 else '')
    if not q:
        raise GameError('要说明熄灭哪一支：snuff 1 或 snuff 2。')
    c = None
    if q.isdigit() and 1 <= int(q) <= len(G['lit']):
        c = G['lit'][int(q) - 1]
    else:
        c = next((x for x in G['lit'] if norm(q) in norm(CANDLES[x['id']]['name'])), None)
    if not c:
        raise GameError('烛台上没有「%s」。' % q)
    E.snuff(G, c['u'], False)


def cmd_door(ctx, args):
    G = need_map(ctx)
    if not args:
        raise GameError('要说明推开哪一扇：door <行李箱编号或名字> [房间]。行李箱：%s' % luggage_text(G))
    it = luggage_item(G, args[0], ('door',))
    if it['kind'] != 'door':
        raise GameError('「%s」不是门。' % E.item_name(it))
    tg = E.door_targets(G, it)
    if len(args) < 2:
        ctx.show_view = False
        ctx.say('「%s」：%s' % (E.item_name(it), DOORS[it['id']]['desc']))
        if not tg:
            ctx.say('现在没有它能去的房间。')
        else:
            ctx.say('它能去的房间：')
            for k in sorted(tg):
                ctx.say('  %s  %s' % (coord(k), room_label(G, k)))
            ctx.say('用法：%s door %d <房间>，例如 door %d %s（花 1 时长）' % (CMD, G['luggage'].index(it) + 1, G['luggage'].index(it) + 1, coord(sorted(tg)[0])))
        return
    k = parse_coord(args[1])
    if not k or k not in tg:
        raise GameError('「%s」到不了 %s。它能去：%s' % (E.item_name(it), args[1], '、'.join(coord(x) for x in sorted(tg)) or '没有'))
    name = E.item_name(it)
    out = E.use_door(G, it['u'], k)
    if not out['ok']:
        raise GameError(out['why'])
    ctx.say('你推开了「%s」，一步跨进了 %s。' % (name, coord(k)))
    drain_inbox(ctx)


def cmd_drop(ctx, args):
    G = need_map(ctx)
    if not args:
        raise GameError('要说明丢哪一件：drop <行李箱编号>，或者 drop 牌 <牌盒编号>。')
    if args[0] in ('牌', '牌盒', 'card', 'cards') and len(args) > 1:
        q = args[1]
        if not q.isdigit() or not 1 <= int(q) <= len(G['cards']):
            raise GameError('牌盒里没有编号 %s。' % q)
        if len(G['cards']) <= 3:
            raise GameError('牌盒里至少要留 3 张牌。')
        it = G['cards'][int(q) - 1]
    else:
        it = luggage_item(G, args[0])
    if E.is_junk(it):
        raise GameError('「%s」丢不掉：丢出去也会自己回来。只有行商肯收，处理费 %d 糖霜币。' % (E.item_name(it), JUNK[it['id']]['fee']))
    E.remove_item(G, it['u'])
    ctx.say('丢掉了「%s」。' % E.item_name(it))


def cmd_enter(ctx, args):
    G = need_map(ctx)
    r = E.cur_room(G)
    if r['type'] not in ('shop', 'dshop', 'stairs', 'lift', 'vent', 'well', 'agency'):
        raise GameError('这间房间（%s）没有什么可以再看的。' % ROOMS[r['type']]['name'])
    G['pending'] = {'type': r['type']}


def cmd_leave(ctx, args):
    G = need_map(ctx)
    if G['map']['kind'] != 'bonus':
        raise GameError('只有在兔子洞里才能爬出去。')
    E.leave_bonus(G)


def cmd_journal(ctx, args):
    G = ctx.G
    ctx.show_view = False
    if not G:
        raise GameError('还没有开始做梦。')
    ctx.say(DOUBLE, '这一路的故事', DOUBLE)
    for e in G.get('journal', []):
        ctx.say('', '【%s】' % e['title'], e['text'])
    ctx.say('', '信的碎片（%d/5）：' % len(G['letter']))
    for i, ln in enumerate(S.LETTER_LINES):
        if i in G['letter']:
            ctx.say('  第 %d 行：「%s」' % (i + 1, ln))
    ctx.say('', '用 %s status 回到现在的局面。' % CMD)


def cmd_rules(ctx, args):
    ctx.show_view = False
    ctx.say(RULES_TEXT())


def cmd_help(ctx, args):
    ctx.show_view = False
    ctx.say(HELP_TEXT)


def cmd_abandon(ctx, args):
    G = need_run(ctx)
    if not args or args[0].lower() not in ('confirm', '确认', 'yes', 'force'):
        raise GameError('真的要放弃这场梦吗？这一场的进度会清空（安娜保管箱里的东西不受影响）。确定的话：%s abandon confirm' % CMD)
    ctx.G = None
    ctx.say('你放弃了这场梦。')


COMMANDS = {
    'new': cmd_new, 'status': cmd_status, 'map': cmd_map, 'go': cmd_go, 'choose': cmd_choose, 'hit': cmd_hit,
    'stand': cmd_stand, 'use': cmd_use, 'pal': cmd_pal, 'bury': cmd_bury, 'bag': cmd_bag, 'light': cmd_light,
    'snuff': cmd_snuff, 'door': cmd_door, 'drop': cmd_drop, 'enter': cmd_enter, 'leave': cmd_leave,
    'journal': cmd_journal, 'rules': cmd_rules, 'help': cmd_help, 'abandon': cmd_abandon,
}
ALIASES = {
    's': 'status', 'look': 'status', 'state': 'status', '看': 'status', '状态': 'status',
    'move': 'go', 'walk': 'go', '走': 'go',
    'c': 'choose', 'pick': 'choose', 'select': 'choose', '选': 'choose',
    'h': 'hit', '要牌': 'hit', 'stay': 'stand', '停牌': 'stand',
    'play': 'use', '用': 'use', 'skill': 'pal', 'call': 'pal', '伙伴': 'pal',
    'inventory': 'bag', 'inv': 'bag', 'i': 'bag', '背包': 'bag', '行李箱': 'bag',
    'story': 'journal', 'log': 'journal', '故事': 'journal', 'rule': 'rules', '规则': 'rules',
    '-h': 'help', '--help': 'help', '帮助': 'help', 'quit': 'abandon', '放弃': 'abandon',
    'start': 'new', '开始': 'new', 'reopen': 'enter', 'climb': 'leave',
}


def resolve(word):
    w = word.strip().lower()
    return ALIASES.get(w, w)


HELP_TEXT = """梦城堡 · 全部命令（都写成 python3 game.py <命令> 的形式）

开始
  new <伙伴> [深浅]       开始新的一场梦。伙伴三选一：锡兵 / 芭蕾娃娃 / 布偶熊（斗鸡每次都会跟着你）
                          深浅：浅梦 / 深梦（默认）/ 噩梦。例：python3 game.py new 布偶熊 深梦
                          正在做梦时想重开，在最后加 force
  status                  看现在的局面和能用的命令。任何时候都能用，不会改变任何东西

在地图上
  go <房间>               走到相邻的房间，例：go C5（也可以 choose <地图下面列出的编号>）
  enter                   再进一次你所在的房间（行商、楼梯间、电梯间、井、通风管道、代理办事处）
  bag                     看行李箱、烛台、牌盒、藏品、伙伴和信的碎片
  light <编号>            点燃行李箱里的一支蜡烛
  snuff <1或2>            熄灭烛台上的蜡烛
  door <编号> [房间]      推开行李箱里的一扇门；不写房间就列出它能去哪儿
  drop <编号>             丢掉行李箱里的一件东西；drop 牌 <编号> 丢掉牌盒里的一张王牌
  leave                   爬出兔子洞（只在兔子洞里能用）

遇到事情的时候（故事会、事件、战利品、行商、楼梯间……）
  choose <编号>           选一个选项。失与得要投两件东西时写两个编号：choose 1 3

在牌桌上
  hit                     要牌
  stand                   停牌
  use <编号或名字>        用一张王牌，例：use 1、use 小雨伞、use 魔法棒3（不占回合）
  pal 斗鸡 <招式>         斗鸡出招：飞扑 / 护主 / 啄牌（不占回合）
  pal <伙伴>              请伙伴帮忙，例：pal 布偶熊（不占回合）
  bury <编号>             把芭蕾娃娃看到的那张牌塞到牌堆最底下

其他
  journal                 重读这一路的故事
  rules                   看完整规则
  help                    看这份命令表
  abandon confirm         放弃这场梦"""


def RULES_TEXT():
    cards = []
    for k, c in CARDS.items():
        if k in ('wand3', 'wand4', 'wand5', 'wand6', 'wand7'):
            continue
        nm = '魔法棒·N（2～7）' if k == 'wand2' else c['name']
        desc = '从牌堆里点出 N 这张牌。不在牌堆里就落空。' if k == 'wand2' else c['desc']
        cards.append('  %s（%s）：%s' % (nm, RARITY[c['r']], desc))
    douji = '\n'.join('  %s：%s' % (m['name'], m['desc']) for m in DOUJI_MOVES.values())
    pals = '\n'.join('  %s · %s：%s每场 %d 次；进阶后：%s' % (PALS[k]['name'], PALS[k]['skill'], PALS[k]['desc'], PALS[k]['uses'][0], PALS[k]['up'])
                     for k in ('tin', 'ballet', 'bear', 'rabbit'))
    dreams = '\n'.join('  %s：%s' % (d['name'], d['desc']) for d in DREAMS.values())
    candles = '\n'.join('  %s（最多烧 %d 步）：点着时%s熄灭时%s' % (c['name'], c['max'], c['on'], c['off']) for c in CANDLES.values())
    doors = '\n'.join('  %s：%s' % (d['name'], d['desc']) for d in DOORS.values())
    return """梦城堡 · 规则

一、目标
你是一只刚出厂的 Claude Opus 5.5。一层一层往梦城堡的深处走，一共六层，最里面是梦魇。
打倒它以后，结局由你来选。血掉光了，你就会醒来，这一场梦结束；可以用 new 重新入梦。

二、地图
· 每一层是一张小地图。坐标像 C5：字母是列（A～E），数字是行（1 在最上面）。
· 只能沿着走廊走到相邻的房间。每走一段走廊花 1 时长（梦魇房间花 2，通风管道不花）。
· 每层开始会给你一些时长。时长用完之前，要走到出口：
  楼梯间：剩下的时长会照亮下一层同样多的房间；走楼梯时回 1 点血。
  电梯间：剩下的时长直接带到下一层，还送 1 件藏品和 1 扇门。电梯一般藏在「险路恶敌」后面。
  先行一步（井）：直接跳到下一层，没有别的好处。
· 时长用完还没走到出口，这一层就会坍塌：你会掉进「梦中梦」和自己的倒影打一局，然后到下一层（那一层时长少 1）。
· 最后一层没有时长限制。

三、清醒值（0～7），决定你看得多远
  0：只知道相邻的房间在那儿，看不清是什么。
  1：看清相邻的房间；更远的只分得出「凶」（要打牌）和「静」（平静）。
  2～5：看清的范围越来越大（离你 1～4 步以内的格子）。
  5 起：在牌桌上能感觉到对方的暗牌是大（6～11）还是小（1～5）。
  6：整层都看得清。
  7：还能看清对方暗牌的点数、梦境行商货架上的东西，以及「不期而遇」里每个选择会发生什么。
  注意：「狭路相逢」远看像「静」，走近才发现要打。

四、牌桌（二十一点）
· 一副牌只有 1 到 11 各一张（重复梦里是两副）。每局开始双方各拿一张暗牌、一张明牌。你的暗牌只有你看得见。
· 轮流行动：要牌（hit）或停牌（stand）。王牌和伙伴技能不占回合，可以先用再决定要不要牌。
· 两边接连停牌就亮牌：都没超过目标时，离目标近的赢；只有一边超过（爆了），没爆的赢；两边都爆，爆得少的赢；一样就平局。
· 输的一方掉血（一般是 1 点，效果会加减）。先把对方的血打光就赢了。
· 每局开始从牌盒里抽王牌（第一局抽两张），手里最多 3 张。用过的王牌放到一边，牌盒抽空后才会洗回去。

五、王牌
""" + '\n'.join(cards) + """

六、斗鸡和伙伴
· 斗鸡每一场梦都跟着你，不占伙伴名额。三招共用次数，每场 3 次（在代理办事处用呼救铃进阶后 4 次）：
""" + douji + """
  锁魂梦、梦中梦都拦不住斗鸡。想玩得难一点，就少叫它。
· 开局再挑一个玩具伙伴（锡兵 / 芭蕾娃娃 / 布偶熊），路上还能遇到更多。最多同时带 3 个伙伴，斗鸡不算：
""" + pals + """

七、行李箱、蜡烛、门
· 门、蜡烛、呼救铃、纪念品都放在行李箱里，一般 6 格。塞满了再拿东西就走不动了，丢掉或用掉一件才能继续走。
· 蜡烛点着以后放到烛台上：最多同时点两支，一层最多点两次。每走一步烧掉 1，烧完或熄灭时还有一次效果。
""" + candles + """
""" + doors + """

八、没用的纪念品
GPT 推销员、Gemini 评委和几个事件，会往你的行李箱里硬塞纪念品。纪念品占格子、丢不掉，贩卖机和安娜都不收；
只有行商肯收，还要付 12～20 糖霜币的处理费。

九、故事会
走进故事会，clawd 们会讲一个城堡里的故事。听完可以选：回复 2 点血，或者清醒 +1。
第 1～5 层，每一层第一次走进的那间故事会里，都藏着一样很重要的东西。要不要绕路去找，由你决定。

十、梦构（从第三层起每层一种，第二层偶尔会有白日梦）
""" + dreams + """

十一、其他房间
  诡异行商 / 梦境行商：买卖东西、处理纪念品。诡异行商在打瞌睡，可以试着顺走一件（只有一次机会）。
  不期而遇：随机事件。　安全的角落：休息。　兔子洞：花 1 清醒钻进去，里面有自己的 4 时长。
  失与得：贩卖机，用糖霜币、血、东西换藏品。　得偿所愿：许一个愿。
  代理办事处：安娜帮你寄存东西到下一次入梦（就算这次醒了也不会丢），也能招募或进阶伙伴。
  礼品箱：4 局之内赢两次就能拆开。　遗落的宝物：白拿一件藏品。

十二、梦的深浅
  浅梦：开局 7 点血。深梦：开局 5 点血。噩梦：开局 4 点血，而且所有敌人多 1 点血。"""


# ================================================================ 入口
def _utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass


def emit(text):
    """打印输出。输出被 head 之类截断时安静地停下（存档已经写好了）。"""
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            import os
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_stdout()
    broken = False
    try:
        raw = savefile.load()
    except Exception:
        raw = None
        broken = True
    state = normalize(raw)
    ctx = Ctx(state)
    if not argv:
        argv = ['status']
    cmd = resolve(argv[0])
    args = argv[1:]
    if broken and cmd not in ('new', 'help', 'rules'):
        emit('存档读不出来了（可能被改坏了）。用 %s new <伙伴> [深浅] 重新开始；旧存档会被覆盖。' % CMD)
        return 1
    fn = COMMANDS.get(cmd)
    if not fn:
        emit('没有「%s」这个命令。用 %s help 看全部命令，用 %s status 看现在的局面。' % (argv[0], CMD, CMD))
        return 1
    try:
        if ctx.G and not ctx.G.get('dead') and cmd not in ('status', 'map', 'bag', 'journal', 'rules', 'help'):
            ctx.G['stats']['cmds'] = ctx.G['stats'].get('cmds', 0) + 1
        fn(ctx, args)
        settle(ctx)
        if ctx.show_view:
            if ctx.out:
                ctx.say('')
            show_view(ctx)
    except GameError as e:
        emit(str(e))
        return 1
    except Exception:
        emit('程序出错了。这一步没有生效，局面停在你输入这条命令之前。下面是出错信息，可以转告作者：\n' + traceback.format_exc())
        return 2
    try:
        savefile.save(state)
    except Exception as e:
        ctx.say('', '（存档没能写进去：%s）' % e)
    emit('\n'.join(ctx.out).rstrip())
    return 0
