#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成发行说明，写到文件 + 追加到 GITHUB_OUTPUT。

单独成文件而不是写进 YAML 的 heredoc：
YAML 的块标量会统一裁掉缩进，heredoc 里的列表、代码块容易被吃掉空白。
用 Python 拼字符串，所见即所得。

用法：python gc_notes.py --tag v0.2a --txt 新的汉化补丁.txt --out /tmp/notes.md
"""
import argparse
import os
import re
import subprocess
import sys

TEMPLATE = """\
把 **Off the Record Plus** 模组的界面 / 对白文本换成简体中文。

## 安装

1. 装 Off the Record Plus 模组
2. 下载下面的 zip，**整个解压到游戏根目录**，提示「替换文件」选「是」
3. 进游戏

zip 里已经带好 `data/frontend/str_en.bcs` 的完整路径，解压就落到正确位置，
不用自己挪文件。游戏目录在：Steam 里右键游戏 → 管理 → 浏览本地文件。

## 说明

- 文本表 {rows} 条，ID 序列与模组英文原表逐条一致
- 构建提交 `{sha}`，打包后已解包回读、逐字节比对通过
- 本包由 GitHub Actions 自动构建，GitHub 与 GitCode 两边的发行版是同一份产物

## 已知问题

- 游戏点阵字体按 3DM 原版译文构建字集，少量生僻字会显示空白
- 少量条目超出 UI 框宽度，可能掉字或出框（构建日志里有逐条明细）

反馈请提单 issue。

---

仅供学习交流。请支持正版游戏与模组作者。
"""


def count_rows(path):
    """数 ID 行数。去掉 BOM 再数，别让首行被算丢。"""
    if not os.path.exists(path):
        return 0
    txt = open(path, 'rb').read().decode('utf-8-sig', errors='replace')
    return len(re.findall(r'(?m)^[0-9]{5} ', txt))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--txt', default='新的汉化补丁.txt')
    ap.add_argument('--out', required=True)
    ap.add_argument('--sha', default=None)
    args = ap.parse_args()

    sha = args.sha
    if not sha:
        try:
            sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                                 capture_output=True, text=True,
                                 errors='replace').stdout.strip()
        except Exception:
            sha = 'unknown'

    body = TEMPLATE.format(rows=count_rows(args.txt), sha=sha or 'unknown')
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    print('已生成 %s（%d 条 ID）' % (args.out, count_rows(args.txt)))

    # 多行输出给后续步骤：GITHUB_OUTPUT 用分隔符写法
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a', encoding='utf-8', newline='\n') as f:
            f.write('body<<NOTES_EOF\n%s\nNOTES_EOF\n' % body.rstrip('\n'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
