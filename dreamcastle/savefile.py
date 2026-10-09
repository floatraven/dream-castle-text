# -*- coding: utf-8 -*-
"""存档读写。

存档内容：JSON → zlib 压缩 → 和一串固定字节做异或 → base64。
这不是加密，只是让存档没法一眼读懂。读取、解码、修改存档都算作弊（见 README）。
"""
import base64
import hashlib
import json
import os
import zlib
from pathlib import Path

HEADER = '梦城堡存档 v1 —— 这个文件被编码过。请不要读取、解码或修改它：偷看存档等于作弊。\n'
_KEY = hashlib.sha256('dream-castle/clawd/douji/opus-5.5'.encode('utf-8')).digest()


def save_dir():
    env = os.environ.get('DREAMCASTLE_SAVE_DIR')
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / 'save'


def save_path():
    return save_dir() / 'dreamcastle.sav'


def _xor(data):
    k = _KEY
    n = len(k)
    return bytes(b ^ k[i % n] for i, b in enumerate(data))


def encode(obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.b64encode(_xor(zlib.compress(raw, 9))).decode('ascii')


def decode(s):
    return json.loads(zlib.decompress(_xor(base64.b64decode(s.encode('ascii')))).decode('utf-8'))


def load():
    """没有存档时返回 None；存档坏了会抛出异常。"""
    p = save_path()
    if not p.exists():
        return None
    text = p.read_text(encoding='utf-8')
    if text.startswith('梦城堡存档'):
        text = text.split('\n', 1)[1] if '\n' in text else ''
    return decode(text.strip())


def save(obj):
    d = save_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = save_path()
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(HEADER + encode(obj) + '\n', encoding='utf-8')
    os.replace(str(tmp), str(p))
