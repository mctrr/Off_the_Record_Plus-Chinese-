#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键构建《丧尸围城2：绝密档案 Plus》汉化补丁。

    python build.py            体检 + 打包 + 出 build/ 社区包
    python build.py --check    只体检，不打包
    python build.py --install  再额外覆盖到游戏目录（覆盖前自动备份）
    python build.py --force    体检有错也照样打包（危险）

流程：结构体检 -> 硬伤阻断 -> 打包 .bcs -> 解包回读逐字节复核 -> 落盘
      -> 出 build/（str_en.bcs + 安装说明 + 源码 + zip）-> [--install] 部署。

.bcs 只在全部复核通过后才覆盖，中途失败不会动到已有的 .bcs。
--install 覆盖游戏文件前一定会先备份到 _backup/（保留最近 20 份）。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

# 本补丁的发布版本号。改版本只需改这一行；git 标签用于对账。
# 版本号递增口诀：0.2a -> 0.2b -> ... -> 0.2z -> 0.3a
VERSION = '1.1'

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows 上 sys.stdout 在输出被重定向（GitHub Actions、管道、IDE 输出窗口）时
# 仍是 cp1252，一 print 中文就 UnicodeEncodeError。PYTHONIOENCODING 对这种
# 「非控制台」情形不生效，必须在进程内 reconfigure。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


TARGET_TXT = os.path.join(HERE, '新的汉化补丁.txt')
EN_TXT = os.path.join(HERE, 'str_en.txt')
TARGET_BCS = os.path.join(HERE, '新的汉化补丁.bcs')
PACKER = os.path.join(HERE, 'BCS_TXT.exe')

# 社区发布包（直接上传这一整个目录 / 里面的 zip）
BUILD_DIR = os.path.join(HERE, 'build')
# 部署到游戏前的备份（不进 build/，免得跟发布包混在一起）
BACKUP_DIR = os.path.join(HERE, '_backup')
KEEP_BACKUPS = 20

# 项目里有两级 .tools/（工作区根一个、仓库上层一个），一律多路径探测，哪个在就用哪个
_ROOTS = [HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]


def _find(*rel):
    for r in _ROOTS:
        p = os.path.normpath(os.path.join(r, *rel))
        if os.path.exists(p):
            return p
    return None


# 3DM 官方中文表 = 游戏点阵字体的字集代理（实测确认：晨/岗/朗/崛 确实缺）。
GLYPH_SOURCES = [p for p in (_find('.tools', '_au3', '_pkg.txt'),
                             os.path.join(HERE, '原汉化补丁.txt')) if p]
# 第二套判据（允许字集.txt），与上面交叉印证：
# 两套都说缺 = 高置信缺字；只有一套说缺 = 存疑（判据本身互相矛盾，
# 例：允许字集说「印/译/符」在集内，3DM 官方表说缺）。
GLYPH_CROSS = [p for p in (_find('.tools', '允许字集.txt'),) if p]

GAME_BCS = (r'E:\SteamLibrary\steamapps\common\Dead Rising 2 Off the Record'
            r'\data\frontend\str_en.bcs')

ATKEY = re.compile(r'\[@([\w]+)\]')
COLOR = re.compile(r'\[([0-9A-Fa-f]{8}),')
PH = re.compile(r'%[0-9]?[sd]')
HAN = re.compile(r'[\u4e00-\u9fff]')
ROW = re.compile(r'^([0-9]{5}) (.*)$')
MARKERS = ('placeholder', '...')

fails, warns = [], []


def fail(name, detail):
    fails.append((name, detail))


def warn(name, detail):
    warns.append((name, detail))


def ok(name, detail=''):
    print('  [OK] %-22s %s' % (name, detail))


def bad(name, detail):
    print('  [!!] %-22s %s' % (name, detail))


def info(name, detail=''):
    print('  [--] %-22s %s' % (name, detail))


# ---------------------------------------------------------------- 读取
def read_rows(path):
    """返回 (原始字节, 是否带 BOM, [(id 或 None, 正文)])，按 CRLF 切行。"""
    raw = open(path, 'rb').read()
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig', errors='replace')
    rows = []
    for ln in text.split('\r\n'):
        if ln == '':
            continue
        m = ROW.match(ln)
        rows.append((m.group(1), m.group(2)) if m else (None, ln))
    return raw, bom, rows


def git_version():
    """(版本串, 短哈希, 提交数)：拿不到 git 就退回日期。"""
    try:
        g = lambda *a: subprocess.run(
            ['git', *a], cwd=HERE, capture_output=True, text=True,
            errors='replace').stdout.strip()
        n = g('rev-list', '--count', 'HEAD')
        h = g('rev-parse', '--short', 'HEAD')
        if n and h:
            return 'V%s (build %s)' % (VERSION, h), h, n
    except Exception:
        pass
    return 'V%s (%s)' % (VERSION, time.strftime('%Y-%m-%d')), 'nogit', '0'


INSTALL_README = """\
《丧尸围城2：绝密档案 Plus》简体中文补丁
=========================================
{ver}    打包日期 {date}

【这是个什么东西】
把 OTR Plus 模组的界面/对白文本换成简体中文。基于 3DM 蒹葭汉化组的
原版汉化补丁做底本，按 Plus 模组新增的文本逐条补齐、逐条校对。

【装之前要什么】
  1. 《丧尸围城2：绝密档案》(Dead Rising 2: Off the Record) 正版
  2. Off the Record Plus 模组（必须！本补丁是为它做的）

【怎么装】三步，不用找文件
  1. 装 Off the Record Plus 模组。
  2. 把本压缩包**整个解压到游戏根目录**，提示「替换文件」选「是」。
     解压完长这样就对了：
         <游戏目录>\\data\\frontend\\str_en.bcs   ← 本补丁自动放到这
     游戏目录在哪：Steam 里右键游戏 → 管理 → 浏览本地文件，
                  能看到 data 文件夹的那一层就是。
  3. 进游戏。

     压缩包里的 data 文件夹会直接盖到游戏目录上，不用自己挪位置。
     安装说明.txt 会一起解到游戏根目录，不影响游戏、不想要可以删。

  还想装 3DM 蒹葭汉化组的原版补丁 V1.0？可以装，但**必须装在这个补丁之前**——
  模组和本补丁都会覆盖它。本补丁自带全部中文文本，不装也不影响。

【怎么还原成英文】
把模组压缩包里的 data\\frontend\\str_en.bcs 拷回去盖掉即可。
或者 Steam 里右键游戏 → 属性 → 本地文件 → 验证游戏文件完整性。

【说明】
- 文本覆盖 mod 英文原表全部 {n} 条ID；ID 序列与英文表逐条一致。
- UTF-8 带 BOM、CRLF；文件内所有 ID、按键引用 [@xxx]、颜色码、%s/%d
  占位符都与模组英文原表严格一一对应，已逐字节回读复核。
- 文本按 UI 框宽手动断行（\\0A）。面板/对白/播片字幕的框宽不一样，
  断行是逐条读出来切的，不是按字符数硬截。
- 仍有少量条目保持英文（专名、按键名、缩写），属预期。

【免责】
仅供学习交流。请支持正版游戏与模组作者。
"""


def publish(row_count):
    """出 build/：按游戏目录结构摆好的发布包 + zip（解压到游戏根目录即装好）。"""
    print('\n=== 发布包 ===')
    ver, sha, n = git_version()
    date = time.strftime('%Y-%m-%d')

    # build/ 自身就镜像游戏目录：data/frontend/str_en.bcs 在该在的位置，
    # 这样「上传 build/ 里的 zip」和「直接把 build/ 拖进游戏目录」两条路都通。
    # 旧版是三个平铺文件（str_en.bcs 在顶层），玩家解压后还得自己挪位置——
    # 2026-10-14 改为带完整路径，解压即用。
    #
    # 发行版只放玩家要用的东西：bcs + 安装说明。
    # 「新的汉化补丁.txt」782KB 可编辑文本表**不进包**（用户 2026-10-14 定）：
    # 玩家没有 BCS_TXT.exe，编辑它也没法自己打包，纯属混淆视听。
    # 它继续留在仓库里（GitHub/GitCode 上按源码查得到），只是不打进发行版。
    files = []                                  # [(zip 内路径, 磁盘路径)]

    bcs_dir = os.path.join(BUILD_DIR, 'data', 'frontend')
    os.makedirs(bcs_dir, exist_ok=True)
    dst_bcs = os.path.join(bcs_dir, 'str_en.bcs')
    shutil.copyfile(TARGET_BCS, dst_bcs)
    files.append(('data/frontend/str_en.bcs', dst_bcs))

    readme = os.path.join(BUILD_DIR, '安装说明.txt')
    with open(readme, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(INSTALL_README.format(ver=ver, date=date, n=row_count))
    files.append(('安装说明.txt', readme))

    # build/ 里不留旧版残留的源码表
    stale = os.path.join(BUILD_DIR, '新的汉化补丁.txt')
    if os.path.exists(stale):
        os.remove(stale)
        info('清理', 'build/新的汉化补丁.txt（不进发行版）')

    for name, p in files:
        ok('出包', '%s  %d 字节' % (name, os.path.getsize(p)))

    zip_name = '丧尸围城2绝密档案Plus-汉化补丁-v%s.zip' % VERSION
    zip_path = os.path.join(BUILD_DIR, zip_name)
    # 旧版本号的 zip 别留在 build/ 里混淆发布对象（只清 zip，别的文件不动）
    for f in os.listdir(BUILD_DIR):
        if f.startswith('丧尸围城2绝密档案Plus-汉化补丁') and f.endswith('.zip') \
                and f != zip_name:
            os.remove(os.path.join(BUILD_DIR, f))
            info('清理旧包', f)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, p in files:
            z.write(p, name)
    ok('压缩包', '%s  %d 字节' % (zip_name, os.path.getsize(zip_path)))

    # 自检：zip 顶层必须带 data/，否则玩家「解压到游戏根目录」装不上
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    if 'data/frontend/str_en.bcs' not in names:
        bad('压缩包结构', '缺 data/frontend/str_en.bcs，解压后装不上')
    else:
        ok('压缩包结构', '解压到游戏根目录即装好：%s'
           % '、'.join(n.replace('/', '\\') for n in names))
    return zip_path


def install():
    """部署到游戏目录 —— 覆盖前先把现有文件备份走。"""
    print('\n=== 部署到游戏 ===')
    dst_dir = os.path.dirname(GAME_BCS)
    if not os.path.isdir(dst_dir):
        bad('部署', '游戏目录不存在：%s' % dst_dir)
        return False

    if os.path.exists(GAME_BCS):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        bk = os.path.join(BACKUP_DIR, 'str_en.bcs.%s'
                          % time.strftime('%Y%m%d_%H%M%S'))
        shutil.copyfile(GAME_BCS, bk)
        ok('备份原文件', '%s（%d 字节）'
           % (os.path.relpath(bk, HERE), os.path.getsize(bk)))
        # 只留最近 N 份
        olds = sorted(f for f in os.listdir(BACKUP_DIR)
                      if f.startswith('str_en.bcs.'))
        for f in olds[:-KEEP_BACKUPS]:
            os.remove(os.path.join(BACKUP_DIR, f))

    shutil.copyfile(TARGET_BCS, GAME_BCS)
    same = open(GAME_BCS, 'rb').read() == open(TARGET_BCS, 'rb').read()
    (ok if same else bad)('部署', '%s（%d 字节）%s'
                         % (GAME_BCS, os.path.getsize(GAME_BCS),
                            '' if same else '  ← 拷过去后字节不一致！'))
    return same


def main():
    print('=== 汉化补丁构建 ===')
    print('  产出文件 %s' % TARGET_TXT)
    # --check 只体检不打包，没有打包器也能跑（CI 的 Linux 任务靠这个）
    need = (TARGET_TXT, EN_TXT) if '--check' in sys.argv else (TARGET_TXT, EN_TXT, PACKER)
    for p in need:
        if not os.path.exists(p):
            print('  [!!] 缺少必需文件：%s' % p)
            return 2

    raw, bom, rows = read_rows(TARGET_TXT)
    _, _, en_rows = read_rows(EN_TXT)
    zh = dict(rows)
    # mod 英文表本身有重复 ID（Janey / Snowflake / Anim / Vanessa …），
    # 同一 ID 可对应多条英文。中文只需匹配其中**任意一条**变体，不能压成一条比对。
    en = {}
    for i, b in en_rows:
        en.setdefault(i, []).append(b)

    # ------------------------------------------------------------ 结构体检
    print('\n--- 结构体检 ---')
    (ok if bom else bad)('BOM', 'UTF-8 BOM 在位' if bom else '缺少 EF BB BF 头')
    if not bom:
        fail('BOM', '缺少 UTF-8 BOM')

    n_crlf = raw.count(b'\r\n')
    n_lf = raw.count(b'\n')
    if n_lf == n_crlf == len(rows):
        ok('行尾', 'CRLF × %d' % n_crlf)
    else:
        bad('行尾', 'CRLF %d / LF %d / 行数 %d' % (n_crlf, n_lf, len(rows)))
        fail('行尾', '行尾被改动（应为纯 CRLF）')

    try:
        raw.decode('utf-8')
        ok('UTF-8 解码', '0 失败')
    except UnicodeDecodeError as e:
        bad('UTF-8 解码', str(e))
        fail('UTF-8 解码', str(e))

    if [i for i, _ in rows] == [i for i, _ in en_rows]:
        ok('ID 序列', '%d 条，与 str_en 完全一致' % len(rows))
    else:
        only_zh = [i for i, _ in rows if i not in en]
        only_en = [i for i, _ in en_rows if i not in zh]
        detail = '产出 %d / 英文 %d；多出 %s 缺失 %s' % (
            len(rows), len(en_rows), only_zh[:5], only_en[:5])
        bad('ID 序列', detail)
        fail('ID 序列', detail)

    ctrl = [i for i, b in rows
            if i and any(ord(c) < 0x20 and c != '\t' for c in b)]
    if ctrl:
        bad('非法控制字节', '%d 条：%s' % (len(ctrl), ', '.join(ctrl[:8])))
        fail('非法控制字节', '字面 \\0A 被写成真实控制字节会读不出换行')
    else:
        ok('非法控制字节', '0 条')

    # 未翻条目（信息性，专名/按键名本来就保持英文）
    untrans = [i for i, b in rows if i and b in en.get(i, ())]
    info('仍为英文', '%d 条 (%.1f%%)  例: %s'
         % (len(untrans), 100.0 * len(untrans) / max(len(rows), 1),
            ', '.join(untrans[:8])))

    dup = sorted(i for i, v in en.items() if len(v) > 1)
    if dup:
        info('英文重复 ID', '%d 个：%s' % (len(dup), ', '.join(dup[:8])))

    # ------------------------------------------------------------ token 体检
    print('\n--- token 体检 ---')
    b_at, b_color, b_ph, b_nl, b_mark = [], [], [], [], []
    for i, z in rows:
        if not i or i not in en:
            continue
        variants = en[i]
        if ATKEY.findall(z) not in [ATKEY.findall(e) for e in variants]:
            b_at.append((i, '|'.join(''.join(x) for x in
                                     [ATKEY.findall(e) for e in variants]),
                         ''.join(ATKEY.findall(z)) or '(无)'))
        cz = COLOR.findall(z)
        if not any(not (set(COLOR.findall(e)) - set(cz))
                   and len(COLOR.findall(e)) == len(cz) for e in variants):
            b_color.append((i, '|'.join(','.join(COLOR.findall(e)) for e in variants),
                            ','.join(cz) or '(无)'))
        if PH.findall(z) not in [PH.findall(e) for e in variants]:
            b_ph.append((i, '|'.join(''.join(PH.findall(e)) for e in variants),
                         ''.join(PH.findall(z)) or '(无)'))
        # \0A：中文侧多于英文侧是尾句切段的预期结果，只查「原文有而译文完全没有」
        if min(e.count('\\0A') for e in variants) and not z.count('\\0A'):
            b_nl.append((i, '/'.join(str(e.count('\\0A')) for e in variants), 0))
        # 英文原文本身就是标记时，中文不能变成别的内容
        if (all(e.strip() in MARKERS for e in variants)
                and z.strip() not in [e.strip() for e in variants]):
            b_mark.append((i, variants[0].strip(), z.strip()[:30]))

    def report(name, lst, fatal, hint=''):
        if not lst:
            ok(name, '0 条')
            return
        bad(name, '%d 条%s' % (len(lst), ('  ' + hint) if hint else ''))
        for row in lst[:8]:
            print('        %s  EN %s -> ZH %s' % row)
        if len(lst) > 8:
            print('        ...另有 %d 条' % (len(lst) - 8))
        if fatal:
            fail(name, '%d 条' % len(lst))

    report('[@key] 取值', b_at, True, '<- 键名被译掉了，游戏查不到资源')
    report('色码取值', b_color, True, '<- 色值丢失或数量变化')
    report('占位符 %s/%d', b_ph, True)
    report(r'\0A 换行', b_nl, True, '<- 原文断行而译文一处未断，会整段被丢弃')
    report('标记行', b_mark, True, '<- placeholder / ... 被填成了别的内容')

    # ------------------------------------------------------------ 字形覆盖
    print('\n--- 字形覆盖 ---')
    src = next((p for p in GLYPH_SOURCES if os.path.exists(p)), None)
    if src is None:
        warn('字形覆盖', '找不到 3DM 官方表，跳过')
    else:
        official = set(HAN.findall(
            open(src, 'rb').read().decode('utf-8-sig', errors='replace')))
        used = set()
        for _, b in rows:
            used |= set(HAN.findall(b))
        miss_a = used - official

        cross = next((p for p in GLYPH_CROSS if os.path.exists(p)), None)
        if cross:
            alt = set(open(cross, 'rb').read()
                      .decode('utf-8-sig', errors='replace'))
            miss_b = used - alt
            core = sorted(miss_a & miss_b)      # 两套判据都判缺
            doubt = sorted(miss_a ^ miss_b)     # 判据不一致
        else:
            core, doubt = sorted(miss_a), []

        def show(chars, tag):
            rows_hit = sum(1 for _, b in rows if set(b) & set(chars))
            print('  [%s] %-20s 缺 %d 字：%s  | 受影响 %d 行'
                  % ('!!' if tag == '高置信' else '~~', tag, len(chars),
                     ''.join(chars), rows_hit))
            for ch in chars:
                hit = [i for i, b in rows if ch in b][:6]
                print('        「%s」 %s' % (ch, ', '.join(hit)))

        if core:
            show(core, '高置信')
            warn('字形覆盖', '高置信缺字 %d 个：%s（两套判据一致）'
                 % (len(core), ''.join(core)))
        if doubt:
            show(doubt, '存疑')
            warn('字形覆盖', '判据不一致 %d 个：%s' % (len(doubt), ''.join(doubt)))
        if not core and not doubt:
            ok('字形覆盖', '官方表 %d 字，全部覆盖' % len(official))

    # ------------------------------------------------------------ 长行宽度
    # 面板区（[@tut_cmn_star] 相邻两标题之间）传说是固定宽度不折行、超宽整段丢弃，
    # 实测阈值取 24。但 3DM 原补丁自己的面板条目 66% 都超 24（最宽 114），
    # 所以这**不是**硬规则，只报数不阻断。
    print('\n--- 长行宽度（参考，不阻断） ---')

    def strip_tokens(s):
        """挖掉 [@key] 与 [色码,内文] 整块——引擎单独排版，不计入可见宽度。
        用正反括号平衡扫描，因为色码可以嵌套（[A,甲里[B,乙]）。
        别用 COLOR 正则直接 sub：它只匹配 `[RRGGBBAA,` 前缀，会把内文留下算进宽度。"""
        out, i, n = [], 0, len(s)
        while i < n:
            if s[i] == '[' and (s.startswith('[@', i)
                                or re.match(r'\[[0-9A-Fa-f]{8},', s[i:i + 11])):
                depth, k = 0, i
                while k < n:
                    if s[k] == '[':
                        depth += 1
                    elif s[k] == ']':
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                if k < n:
                    i = k + 1
                    continue
            out.append(s[i])
            i += 1
        return ''.join(out)

    def vis(s):
        return sum(2 if ord(c) > 0x1100 else 1 for c in strip_tokens(s))

    ti = [n for n, (i, b) in enumerate(en_rows) if '[@tut_cmn_star]' in b]
    panel_ids = set()
    for a, z in zip(ti, ti[1:]):
        panel_ids.update(en_rows[n][0] for n in range(a + 1, z))

    # A 类：英文原表**自己**带 \0A 的条目 —— 作者手切的断点就是那条文本的框宽。
    # 英文放得下的宽度，中文（同一个宽度口径）必然也放得下。
    # 这是唯一可机械验证的宽度判据，其余阈值都是从 3DM 已发布补丁里估出来的。
    a_ok, a_bad, a_seen = 0, [], 0
    for i, z in rows:
        variants = en.get(i)
        if not z or not variants:
            continue
        es = [e for e in variants if '\\0A' in e]
        if not es:
            continue
        a_seen += 1
        cap = max(vis(s) for e in es for s in e.split('\\0A'))
        w = max(vis(s) for s in z.split('\\0A'))
        if w > cap:
            a_bad.append((w - cap, i, cap, w))
        else:
            a_ok += 1
    if a_seen:
        if not a_bad:
            ok('A 类宽度对照', '%d 条：中文最长段均不超过英文同条最长段'
               % a_seen)
        else:
            a_bad.sort(reverse=True)
            warn('A 类宽度对照', '%d 条中文段比英文同条更宽：%s'
                 % (len(a_bad), ', '.join('%s(+%d)' % (i, d)
                                          for d, i, _, _ in a_bad[:8])))
            print('  [~~] %-20s 英文自带断行的条目共 %d 条，其中 %d 条超标'
                  % ('A 类宽度对照', a_seen, len(a_bad)))
            for d, i, cap, w in a_bad[:8]:
                print('        %s  英文最长段 %d，中文最长段 %d' % (i, cap, w))
    else:
        info('A 类宽度对照', '英文原表没有自带断行的条目，跳过')

    # B/C 类：没有英文断点可作依据，退回经验阈值。
    # 54 来自「3DM 原补丁单行中文宽度的硬悬崖」：48-53 有 458 条，54-59 只剩 20 条。
    CAP = 54
    b_over, b_all = [], 0
    c_over, c_all = [], 0
    for i, z in rows:
        if not z or not en.get(i):
            continue
        e_has = any('\\0A' in e for e in en[i])
        if e_has:
            continue
        if '\\0A' in z:
            b_all += 1
            w = max(vis(s) for s in z.split('\\0A'))
            if w > CAP:
                b_over.append((w, i))
        else:
            c_all += 1
            w = vis(z)
            if w > CAP:
                c_over.append((w, i))
    for tag, over, tot, note in (
            ('B 类 >%d 宽' % CAP, b_over, b_all, '英文没断、断行是后加的'),
            ('C 类 >%d 宽' % CAP, c_over, c_all, '中文单行、两侧都没断')):
        over.sort(reverse=True)
        if not tot:
            continue
        if over:
            warn('长行宽度 ' + tag, '%d / %d 条：%s'
                 % (len(over), tot, ', '.join('%s(%d)' % (i, w)
                                              for w, i in over[:8])))
            print('  [~~] %-20s %d / %d 条（%s）'
                  % (tag, len(over), tot, note))
            print('        %s' % ', '.join('%s(%d)' % (i, w)
                                           for w, i in over[:40]))
            if len(over) > 40:
                print('        ……另有 %d 条' % (len(over) - 40))
        else:
            ok(tag, '%d 条全部不超' % tot)

    # 图鉴面板区：固定宽度文本框，阈值传说是 24 —— 但 3DM 自己的面板条目
    # 66%% 都超 24（最宽 114），所以只报数不阻断。
    segs = [vis(s) for i, b in rows if i in panel_ids for s in b.split('\\0A')]
    if segs:
        ov = sum(1 for w in segs if w > 24)
        info('图鉴面板区 >24 宽', '%d / %d 段 (%.0f%%)，最宽 %d'
             % (ov, len(segs), 100.0 * ov / len(segs), max(segs)))
        if ov:
            hit = sorted({i for i, b in rows if i in panel_ids
                          and any(vis(s) > 24 for s in b.split('\\0A'))})
            print('        待切 ID：%s' % ', '.join(hit))
        ref_rows = read_rows(os.path.join(HERE, '原汉化补丁.txt'))[2] \
            if os.path.exists(os.path.join(HERE, '原汉化补丁.txt')) else []
        ref_map = dict(ref_rows)
        base = [vis(s) for i in panel_ids if i in ref_map
                for s in ref_map[i].split('\\0A')]
        if base:
            info('3DM 同区基线', '%d / %d 段超 24 (%.0f%%)，最宽 %d  <- 规则并不硬'
                 % (sum(1 for w in base if w > 24), len(base),
                    100.0 * sum(1 for w in base if w > 24) / len(base),
                    max(base)))


    # ------------------------------------------------------------ 打包
    summary = '硬伤 %d 项 / 提示 %d 项' % (len(fails), len(warns))
    if fails and '--force' not in sys.argv:
        print('\n=== 体检未通过（%s），已中止打包 ===' % summary)
        for name, detail in fails:
            print('  阻断：%s —— %s' % (name, detail))
        return 1

    if '--check' in sys.argv:
        print('\n=== 只体检（%s），未打包 ===' % summary)
        return 1 if fails else 0

    print('\n=== 打包 ===')
    if fails:
        print('  [!!] --force：带着 %d 项硬伤继续打包' % len(fails))

    old_size = os.path.getsize(TARGET_BCS) if os.path.exists(TARGET_BCS) else 0
    tmp = tempfile.mkdtemp(prefix='bcsbuild_')
    try:
        src_txt = os.path.join(tmp, 'new.txt')
        shutil.copyfile(TARGET_TXT, src_txt)
        r = subprocess.run([PACKER, 'new.txt'], cwd=tmp,
                           capture_output=True, text=True, errors='replace')
        packed = os.path.join(tmp, 'new.bcs')
        if r.returncode != 0 or not os.path.exists(packed):
            bad('打包', 'BCS_TXT.exe 失败 rc=%d' % r.returncode)
            print((r.stdout or '') + (r.stderr or ''))
            return 2
        size = os.path.getsize(packed)
        ok('打包', '%s（%d 字节，原 %d，%+d）'
           % (os.path.basename(TARGET_BCS), size, old_size, size - old_size))

        # 解包回读逐字节复核：能抓出打包器静默丢字/改字
        rt_bcs = os.path.join(tmp, 'rt.bcs')
        shutil.copyfile(packed, rt_bcs)
        r = subprocess.run([PACKER, 'rt.bcs'], cwd=tmp,
                           capture_output=True, text=True, errors='replace')
        rt_txt = os.path.join(tmp, 'rt.txt')
        if r.returncode != 0 or not os.path.exists(rt_txt):
            bad('往返复核', '解包失败 rc=%d' % r.returncode)
            return 2
        if open(rt_txt, 'rb').read() == raw:
            ok('往返复核', '解包结果与源文件逐字节一致')
        else:
            bad('往返复核', '解包结果与源文件不一致，拒绝落盘')
            return 2

        shutil.copyfile(packed, TARGET_BCS)
        ok('落盘', TARGET_BCS)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------ 发布包
    publish(len(rows))

    # ------------------------------------------------------------ 部署
    if '--install' in sys.argv and not install():
        return 2

    print('\n=== 完成：%s ===' % summary)
    for name, detail in warns:
        print('  提示：%s —— %s' % (name, detail))
    print('  提示：改完记得 git add/commit；未提交的改动不影响本脚本。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
