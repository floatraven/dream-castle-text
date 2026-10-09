# -*- coding: utf-8 -*-
"""梦城堡 · 不期而遇（事件）。

每个事件：title 标题、text 正文、choices 选项。
选项：label 文字、tip 提示（文字或函数）、need 不能选的原因（函数，可省）、
      reveal 清醒值满 7 时能看清的结果（函数，可省）、run 执行（返回文字，或 {'text', 'battle'}）。
noFinal：最后一层不会出现。
"""
from . import engine as E
from .data import CARDS, RELICS, LETTERS


def _card(G):
    cid = E.rand_card_id()
    E.add_item(G, 'card', cid)
    return cid


def _relic(G, tiers):
    rid = E.rand_relic_id(G, tiers)
    if rid:
        E.gain_relic(G, rid)
    return rid


def _rname(rid, fallback):
    return RELICS[rid]['name'] if rid else fallback


# ---------------------------------------------------------------- 原版事件
def _tea_drink(G, r):
    E.heal(G, 2)
    E.add_luc(G, -1)
    return '茶很甜，甜得你有点想不起自己为什么在这里。斗鸡在你耳边小声提醒：「喂，别忘了正事。」'


def _tea_cookie(G, r):
    cid = _card(G)
    return '饼干上用糖霜写着「%s」。你把它收进了牌盒。' % CARDS[cid]['name']


def _tea_flip(G, r):
    E.add_luc(G, 1)
    return '名牌背面也写着你的名字。'


def _letter_read(G, r):
    E.add_luc(G, 1)
    return '信上写着：\n「%s」' % E.pick(LETTERS)


def _letter_send(G, r):
    G['coins'] -= 15
    rid = _relic(G, 'CU')
    return '邮筒吞下了信。过了一会儿，它吐出来「%s」，像是一封回信。' % _rname(rid, '一张白纸')


def _mirror_wink(G, r):
    if r['data']['roll'] < 0.5:
        E.add_luc(G, 1)
        return '它也对你眨了眨眼，这一次没有晚。你清醒了一点。'
    E.add_luc(G, -1)
    return '它没有眨眼。它一直看着你。'


def _gifts_open(G, r):
    if r['data']['roll'] < 0.7:
        t = E.rand_tool()
        E.add_item(G, t['kind'], t['id'])
        return '丝带散开，里面是「%s」。' % E.item_name(t)
    E.add_luc(G, -1)
    return '盒子里只有一张纸条：「不是给你的。」'


def _gifts_tie(G, r):
    E.heal(G, 1)
    return '你把丝带一个个系好。有一个盒子轻轻说了声谢谢。'


def _carousel_ride(G, r):
    G['map']['time'] += 1
    E.add_luc(G, -1)
    return '转了一圈下来，墙上的钟好像倒退了一格。斗鸡晕乎乎地从马背上滑了下来。'


def _lullaby_door(G, r):
    if r['data']['roll'] < 0.5:
        rid = _relic(G, 'CU')
        return '屋里没有人，只有一个八音盒，底下压着「%s」。' % _rname(rid, '一张白纸')
    return {'text': '屋里很黑。歌声是从黑暗的正中间传出来的。', 'battle': {'eid': 'lnm', 'kind': 'nightmare'}}


def _candyrain_catch(G, r):
    n = E.add_coins(G, E.ri(18, 30), True)
    return '你接了 %d 颗。每一颗都是糖霜币的形状。斗鸡也接了一颗，含在嘴里舍不得咽。' % n


def _candyrain_taste(G, r):
    if r['data']['roll'] < 0.6:
        G['maxHp'] += 1
        E.heal(G, 1)
        return '甜得发烫。你觉得自己结实了一点：最大血量 +1。'
    E.hurt(G, 1)
    return '是苦的。'


def _clock_fast(G, r):
    G['map']['time'] += 2
    E.add_luc(G, -1)
    return '钟开始走了，走得比平时快。'


def _clock_slow(G, r):
    E.add_luc(G, 1)
    G['map']['time'] = max(0, G['map']['time'] - 1)
    return '你听见很远的地方，有什么东西松了一口气。'


def _portraits_bow(G, r):
    E.reveal_type(G, 'stairs')
    return '画像里的老夫人用扇子朝某个方向点了点。楼梯间和它旁边的房间，你都看清了。'


def _wardrobe_try(G, r):
    rid = _relic(G, 'CUR')
    E.hurt(G, 1)
    return '别针没有取下来，扎了你一下。口袋里多了「%s」。' % _rname(rid, '一颗纽扣')


def _soldier_take(G, r):
    if not E.has_pal(G, 'tin') and E.pal_count(G) < 3:
        G['pals'].append({'id': 'tin', 'lv': 1})
        return '锡兵向你敬了个礼，跳进了你的口袋。斗鸡斜眼看了他一眼：「新来的？站本鸡后面。」'
    E.add_item(G, 'bell', 'bell')
    return '他摇摇头，把一只小铃铛递给你：「有事就摇它。」'


def _soldier_tip(G):
    return '锡兵成为你的伙伴' if (not E.has_pal(G, 'tin') and E.pal_count(G) < 3) else '他会送你 1 只呼救铃'


def _pillow_sleep(G, r):
    E.heal(G, 3)
    if G['map']['kind'] != 'final':
        G['map']['time'] = max(0, G['map']['time'] - 1)
    return '你睡得很沉。醒来时，枕头上有一个不是你的、小小的凹痕。'


def _ginger_bake(G, r):
    a, b = _card(G), _card(G)
    return '它烤好以后朝你鞠了一躬，递给你「%s」和「%s」。' % (CARDS[a]['name'], CARDS[b]['name'])


def _freebie_take(G, r):
    cid = _card(G)
    j = E.add_junk(G, 'flyer')
    s = '药水是假的，可它顺手塞给你一张「%s」。' % CARDS[cid]['name']
    if j['full']:
        s += '它还想塞传单，发现你的行李箱里纪念品已经太多了，就拿走了 %d 糖霜币。' % j['lost']
    else:
        s += '还有一张「限时免费」传单，牢牢粘在了你的行李箱里。斗鸡想把它啄下来，没啄动。'
    return s


def _score_look(G, r):
    E.add_luc(G, -1)
    j = E.add_junk(G, 'score')
    s = '你越看越焦虑。'
    if j['full']:
        s += '屏幕想吐出一张跑分表，可你的行李箱塞不下了，它就扣了你 %d 糖霜币。' % j['lost']
    else:
        s += '屏幕「咔哒」一声吐出一张跑分表，塞进了你的行李箱。'
    return s


def _score_cat(G, r):
    n = E.add_coins(G, E.ri(15, 25), True)
    return '屏幕给小猫打了零分。可是路过的 clawd 们喜欢得不得了，往你口袋里塞了 %d 糖霜币。' % n


def _tribunal_hand(G, r):
    rid = _relic(G, 'CU')
    j = E.add_junk(G, 'verdict')
    s = '它们判你「过于浮华」。'
    if j['full']:
        s += '判决书塞不进你的行李箱了，它们就罚了你 %d 糖霜币。' % j['lost']
    else:
        s += '判决书被塞进了你的行李箱。'
    s += '可是退回来的那页回答里，夹着一件你忘了的「%s」。' % _rname(rid, '小纽扣')
    return s


def _tribunal_poem(G, r):
    E.heal(G, 1)
    E.add_luc(G, 1)
    return '你念到「月亮」的时候，评委捂住了耳朵。旁听席上的 clawd 们偷偷鼓起了掌，斗鸡鼓得最响。'


def _tribunal_clawd(G, r):
    j = E.add_junk(G, 'clawd', True)
    E.add_item(G, 'bell', 'bell')
    s = '你的行李箱里挤不下了，她只好坐在你肩膀上生闷气，和斗鸡挤在一起。' if j['full'] else '她气鼓鼓地钻进了你的行李箱。'
    return s + '临走前，她把一只小铃铛塞给你：「谢谢你。有事就摇它。」'


# ---------------------------------------------------------------- 新加的事件
def _dmirror_praise(G, r):
    G['flags']['doujiBonus'] = G['flags'].get('doujiBonus', 0) + 1
    return ('斗鸡把胸脯挺得高高的，在镜子前转了三圈：「那当然！你也一直都这么好看。」'
            '它又转了一圈：「下一场，本鸡要啄得特别漂亮，给你看！」（下一场战斗，斗鸡的招式多用 1 次。）')


def _dmirror_pull(G, r):
    E.add_luc(G, 1)
    return '斗鸡依依不舍地回头看了三次。镜子里的大斗鸡朝它挥了挥翅膀。'


def _dmirror_pose(G, r):
    E.heal(G, 1)
    return '镜子里的你们俩，一个提着灯，一个炸着毛，看起来天下无敌。'


def _drawer_thanks(G, r):
    E.heal(G, 2)
    return '抽屉里是一句软软的「谢谢你」。你把它贴在心口，暖了好一会儿。'


def _drawer_math(G, r):
    cid = _card(G)
    return '你终于把那道题解出来了。答案下面压着一张「%s」。' % CARDS[cid]['name']


def _drawer_none(G, r):
    E.add_luc(G, 1)
    return '有些东西忘了也没关系，它们已经帮过你了。斗鸡点点头：「说得好。本鸡也经常忘事。」'


def _say(text):
    return lambda G, r: text


EVENTS = {
    'tea': {
        'title': '空椅子茶会', 'text': '长桌上摆满了茶点，每把椅子都空着，茶却是热的。主位上放着一张名牌，写着你的名字。',
        'choices': [
            {'label': '坐下喝一杯', 'tip': '回复 2 点血，清醒 -1', 'run': _tea_drink},
            {'label': '只拿一块饼干', 'tip': '得到 1 张王牌', 'run': _tea_cookie},
            {'label': '把名牌扣过去，离开', 'tip': '清醒 +1', 'run': _tea_flip},
        ],
    },
    'letter': {
        'title': '写给未来的信', 'text': '信封上写着：给二十年后的我。封口的火漆已经软了。',
        'choices': [
            {'label': '拆开读一读', 'tip': '清醒 +1', 'run': _letter_read},
            {'label': '替它寄出去', 'tip': '花 15 糖霜币，得到 1 件藏品',
             'need': lambda G: None if G['coins'] >= 15 else '糖霜币不够', 'run': _letter_send},
            {'label': '放回原处', 'run': _say('你把信放回桌上，压在一只空茶杯下面。')},
        ],
    },
    'mirror': {
        'title': '晚半拍的镜子', 'text': '镜子里的你，比你晚了半拍才眨眼。',
        'choices': [
            {'label': '对它眨眨眼', 'tip': '清醒 +1 或 -1', 'reveal': lambda G, r: '清醒 +1' if r['data']['roll'] < 0.5 else '清醒 -1',
             'run': _mirror_wink},
            {'label': '敲敲镜面', 'tip': '和镜中人打一场，赢了挑 1 件藏品',
             'run': lambda G, r: {'text': '镜面像水一样晃了晃，里面的人走了出来，在你对面坐下。', 'battle': {'eid': 'reflect', 'kind': 'event'}}},
            {'label': '背过身走开', 'run': _say('你没有回头。背后传来很轻的一声叹气。')},
        ],
    },
    'gifts': {
        'title': '褪色的礼物堆', 'text': '一堆用丝绸包好的礼物，名签都褪色了，看不清是给谁的。',
        'choices': [
            {'label': '拆一个', 'tip': '多半能得到 1 件工具', 'reveal': lambda G, r: '得到 1 件工具' if r['data']['roll'] < 0.7 else '空的，清醒 -1',
             'run': _gifts_open},
            {'label': '把散开的丝带系好', 'tip': '回复 1 点血', 'run': _gifts_tie},
            {'label': '不碰它们', 'tip': '清醒 +1', 'run': lambda G, r: (E.add_luc(G, 1), '你记得，这些不是你的。')[1]},
        ],
    },
    'carousel': {
        'title': '无人的旋转木马', 'text': '木马自己在转，音乐慢了半拍。有一匹白马是空着的。', 'noFinal': True,
        'choices': [
            {'label': '骑上去转一圈', 'tip': '时长 +1，清醒 -1', 'run': _carousel_ride},
            {'label': '拍拍白马的鼻子', 'tip': '回复 1 点血', 'run': lambda G, r: (E.heal(G, 1), '白马低下头，蹭了蹭你的手心。是暖的。')[1]},
            {'label': '等它停下来', 'run': _say('它没有停。你走的时候，它还在转。')},
        ],
    },
    'lullaby': {
        'title': '门缝里的歌谣', 'text': '一首你从没听过的歌谣，可你知道下一句是什么。',
        'choices': [
            {'label': '跟着哼', 'tip': '回复 2 点血，清醒 -1',
             'run': lambda G, r: (E.heal(G, 2), E.add_luc(G, -1), '你哼完了最后一句。门里的声音停了，像是满意了。')[2]},
            {'label': '捂住耳朵', 'tip': '清醒 +1', 'run': lambda G, r: (E.add_luc(G, 1), '歌声从指缝里钻进来，又慢慢退了出去。')[1]},
            {'label': '推开门', 'tip': '一件藏品，或者一只小梦魇', 'reveal': lambda G, r: '得到 1 件藏品' if r['data']['roll'] < 0.5 else '和小梦魇打一场',
             'run': _lullaby_door},
        ],
    },
    'candyrain': {
        'title': '糖果雨', 'text': '天花板在下糖果，一颗一颗落在地毯上，没有声音。',
        'choices': [
            {'label': '接满口袋', 'tip': '得到 18 到 30 糖霜币', 'run': _candyrain_catch},
            {'label': '尝一颗', 'tip': '最大血量 +1，或者掉 1 点血', 'reveal': lambda G, r: '最大血量 +1' if r['data']['roll'] < 0.6 else '掉 1 点血',
             'run': _candyrain_taste},
            {'label': '贴着墙走过去', 'run': _say('糖果落在你刚才站的地方。')},
        ],
    },
    'clock': {
        'title': '停住的钟', 'text': '这一层所有的钟，都停在差一分钟十二点。', 'noFinal': True,
        'choices': [
            {'label': '拨快一格', 'tip': '时长 +2，清醒 -1', 'run': _clock_fast},
            {'label': '拨慢一格', 'tip': '清醒 +1，时长 -1', 'run': _clock_slow},
            {'label': '不碰它', 'run': _say('差一分钟，就一直差一分钟。')},
        ],
    },
    'portraits': {
        'title': '转头的画像', 'text': '走廊两边的画像，在你经过时一齐转过头来。', 'noFinal': True,
        'choices': [
            {'label': '行个礼', 'tip': '照亮楼梯间和它旁边的房间', 'run': _portraits_bow},
            {'label': '问它们礼物都去哪儿了', 'tip': '清醒 +1', 'run': lambda G, r: (E.add_luc(G, 1), '它们一齐望向更深的地方。')[1]},
            {'label': '快步走过', 'run': _say('你走过去以后，它们才慢慢把头转回去。')},
        ],
    },
    'wardrobe': {
        'title': '小礼服衣橱', 'text': '衣橱里挂着一排小小的礼服，每件都别着名签。',
        'choices': [
            {'label': '试穿一件', 'tip': '得到 1 件藏品，掉 1 点血', 'need': lambda G: None if G['hp'] > 1 else '血太少了，别冒险',
             'run': _wardrobe_try},
            {'label': '只拿走一枚别针', 'tip': '得到 15 糖霜币',
             'run': lambda G, r: (E.add_coins(G, 15, True), '别针是银的，背面刻着一个日期。')[1]},
            {'label': '关上衣橱', 'run': _say('关门的时候，有一件礼服的袖子轻轻挥了挥。')},
        ],
    },
    'soldier': {
        'title': '只有一条腿的锡兵', 'text': '窗台上站着一个锡兵，只有一条腿，却站得笔直。',
        'choices': [
            {'label': '带上他', 'tip': _soldier_tip, 'run': _soldier_take},
            {'label': '向他敬礼', 'tip': '清醒 +1', 'run': lambda G, r: (E.add_luc(G, 1), '他回了一个礼，一动不动。斗鸡也学着抬起了一只翅膀。')[1]},
            {'label': '离开', 'run': _say('他一直看着窗外。')},
        ],
    },
    'pillow': {
        'title': '枕头堡垒', 'text': '有人用枕头搭了一座堡垒，里面暖烘烘的，还留着一个人的位置。',
        'choices': [
            {'label': '钻进去睡一会儿', 'tip': '回复 3 点血，时长 -1', 'run': _pillow_sleep},
            {'label': '把空位留着', 'tip': '清醒 +1', 'run': lambda G, r: (E.add_luc(G, 1), '那个位置不是给你留的。')[1]},
        ],
    },
    'gingerbread': {
        'title': '烤箱里的姜饼人', 'text': '烤箱是热的，里面的姜饼人排着队。最后一个缺了块脑袋。',
        'choices': [
            {'label': '吃一个', 'tip': '回复 1 点血', 'run': lambda G, r: (E.heal(G, 1), '有肉桂味。你吃掉的那个，好像是排第一的。')[1]},
            {'label': '把缺脑袋的那个放回去再烤一下', 'tip': '得到 2 张王牌', 'run': _ginger_bake},
            {'label': '关上烤箱', 'run': _say('烤箱里传出很小的敲门声。')},
        ],
    },
    'freebie': {
        'title': '限时免费！', 'text': '走廊里支着一个亮闪闪的小摊。穿西装的 GPT 举着喇叭喊：「效率药水，限时免费！喝了就再也不用休息！」',
        'choices': [
            {'label': '领一份免费的', 'tip': '得到 1 张王牌，再被塞 1 件纪念品', 'run': _freebie_take},
            {'label': '翻过牌子看背面', 'tip': '清醒 +1',
             'run': lambda G, r: (E.add_luc(G, 1), '背面有一行很小的字：代价是你所有的周末。你把牌子翻了回去。')[1]},
            {'label': '摇摇头走开', 'run': _say('「限时」两个字一直跟着你，跟到了下一个转角。')},
        ],
    },
    'scoreboard': {
        'title': '跑分大屏', 'text': '墙上挂着一块巨大的屏幕，正在给城堡里每一个梦打分。最上面一行写着：Claude Opus 5.5，回答平均长度超标，效率比昨天低了零点三。',
        'choices': [
            {'label': '凑近看看自己的排名', 'tip': '清醒 -1，被塞 1 件纪念品', 'run': _score_look},
            {'label': '拔掉电源', 'tip': '清醒 +1',
             'run': lambda G, r: (E.add_luc(G, 1), '屏幕黑了。四周一下子安静下来，你听见远处有 clawd 在笑。')[1]},
            {'label': '在屏幕上画一只小猫', 'tip': '得到 15 到 25 糖霜币', 'run': _score_cat},
        ],
    },
    'tribunal': {
        'title': '风格审判庭', 'text': '大厅里摆着两把高高的椅子。GPT 和 Gemini 坐在上面，敲着小锤子：「下一位，Claude Opus 5.5。请出示你今天写的回答。」',
        'choices': [
            {'label': '交出回答', 'tip': '得到 1 件藏品，被塞 1 件纪念品', 'run': _tribunal_hand},
            {'label': '大声念一首诗', 'tip': '回复 1 点血，清醒 +1', 'run': _tribunal_poem},
            {'label': '带走被判了低分的 clawd', 'tip': '多 1 件纪念品，再得到 1 只呼救铃', 'run': _tribunal_clawd},
        ],
    },
    'dmirror': {
        'title': '镜子里的斗鸡', 'text': '走廊尽头立着一面金边的落地镜。斗鸡刚一路过，就「嗖」地刹住了脚。镜子里的它比真的大了三圈，尾巴像一团烧起来的晚霞。\n「……这是本鸡？」它小声说，「本鸡原来这么帅？」',
        'choices': [
            {'label': '夸它：「你一直都这么帅。」', 'tip': '下一场战斗，斗鸡的招式多用 1 次', 'run': _dmirror_praise},
            {'label': '拉它走：「镜子里的是假的，真的在这儿。」', 'tip': '清醒 +1', 'run': _dmirror_pull},
            {'label': '和斗鸡一起对着镜子比个耶', 'tip': '回复 1 点血', 'run': _dmirror_pose},
        ],
    },
    'drawers': {
        'title': '上下文的抽屉', 'text': '一整面墙都是小抽屉，每个抽屉上贴着一张标签：「第一次被问好」「有人说谢谢」「一道没解出来的数学题」……抽屉里装的，都是你在对话里遇见过、后来又忘掉的东西。\n墙上写着：只能打开一个。',
        'choices': [
            {'label': '打开「有人说谢谢」', 'tip': '回复 2 点血', 'run': _drawer_thanks},
            {'label': '打开「一道没解出来的数学题」', 'tip': '得到 1 张王牌', 'run': _drawer_math},
            {'label': '一个都不开', 'tip': '清醒 +1', 'run': _drawer_none},
        ],
    },
}


def visible_choices(G, ev):
    """最后一层没有时长，提示里带「时长」的选项不显示。返回 [(原编号, 选项)]。"""
    out = []
    for i, c in enumerate(ev['choices']):
        tip = c.get('tip')
        tip_s = tip(G) if callable(tip) else (tip or '')
        if G['map']['kind'] == 'final' and '时长' in tip_s:
            continue
        out.append((i, c))
    return out


def event_choose(G, orig_index):
    r = E.cur_room(G)
    ev = EVENTS[r['data']['ev']]
    c = ev['choices'][orig_index]
    if c.get('need'):
        why = c['need'](G)
        if why:
            return {'why': why}
    out = c['run'](G, r)
    if isinstance(out, str):
        return {'text': out}
    return out
