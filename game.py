#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""梦城堡 · 文字版 —— 入口。

用法：python3 game.py <命令>。看全部命令：python3 game.py help
"""
import os
import sys

if sys.version_info < (3, 6):
    sys.stdout.write('梦城堡需要 Python 3.6 或更新的版本。\n')
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dreamcastle.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
