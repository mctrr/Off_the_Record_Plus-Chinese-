#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""建/更新 GitHub 发行版并上传附件。供 GitHub Actions 调用。

为什么不用 softprops/action-gh-release：
  它上传附件时会走「把文件名塞进 URL、不显式给 name」的路径，中文名
  `丧尸围城2绝密档案Plus-汉化补丁-v1.1.zip` 会被截成 `2.Plus-.-v1.1.zip`
  （实测）。这里改成两步：POST /releases 建发行版，再用
  POST <upload_url>?name=<原文件名> 显式带 name 上传附件。

用法：
    python gh_release.py --token T --tag v1.1 --zip path.zip \
        --body-file notes.md [--name "汉化补丁 v1.1"]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OWNER = 'mctrr'
REPO = 'Off_the_Record_Plus-Chinese-'
API = 'https://api.github.com/repos/%s/%s' % (OWNER, REPO)


def call(url, token, method='GET', body=None, raw=None, ctype=None):
    h = {'Authorization': 'Bearer ' + token,
         'Accept': 'application/vnd.github+json',
         'X-GitHub-Api-Version': '2022-11-28',
         'User-Agent': 'gh-release-script/1.0'}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    elif raw is not None:
        data = raw
        h['Content-Type'] = ctype or 'application/octet-stream'
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--zip', required=True)
    ap.add_argument('--body-file', default=None)
    ap.add_argument('--name', default=None)
    a = ap.parse_args()

    if not os.path.exists(a.zip):
        print('找不到附件：%s' % a.zip)
        return 2
    body = ''
    if a.body_file and os.path.exists(a.body_file):
        body = open(a.body_file, encoding='utf-8').read()
    name = a.name or ('汉化补丁 %s' % a.tag)

    payload = {'tag_name': a.tag, 'name': name, 'body': body,
               'draft': False, 'prerelease': False}

    print('=== 建发行版 %s ===' % a.tag)
    code, resp = call(API + '/releases', a.token, 'POST', payload)
    rel = None
    if code in (200, 201):
        rel = json.loads(resp)
        print('  已创建')
    elif code == 422:
        # 已存在：取回来改描述
        print('  已存在，改为更新')
        c2, r2 = call(API + '/releases/tags/' + urllib.parse.quote(a.tag), a.token)
        if c2 != 200:
            print('  取发行版失败 %s %s' % (c2, r2[:200]))
            return 1
        rel = json.loads(r2)
        c3, r3 = call('%s/releases/%d' % (API, rel['id']), a.token, 'PATCH',
                      {'name': name, 'body': body})
        if c3 not in (200, 201):
            print('  更新失败 %s %s' % (c3, r3[:200]))
            return 1
        print('  已更新')
    else:
        print('  失败 %s %s' % (code, resp[:300]))
        return 1

    fn = os.path.basename(a.zip)

    # GitHub 的 uploads API 不接受非 ASCII 附件名：实测传 name=测试汉化.zip
    # 会落成 default.zip，传中文全名会 422。所以附件名一律用 ASCII，
    # 中文版本信息放在发行版标题里（GitHub 支持）。
    ascii_name = 'DR2-OTR-Plus-CHS-v%s.zip' % a.tag.lstrip('v')

    # 附件列表要从 GET /releases/<id> 现取：POST /releases 的响应体里
    # assets 是空数组，靠它找不到已有附件，上传同名会 422 already_exists。
    c, r = call('%s/releases/%d' % (API, rel['id']), a.token)
    if c == 200:
        rel = json.loads(r)

    for asset in rel.get('assets', []):
        if asset['name'].endswith('.zip'):
            c, _ = call('%s/releases/assets/%d' % (API, asset['id']), a.token,
                        'DELETE')
            print('  删掉旧附件 %s -> %s' % (asset['name'], c))
            # 删除是异步的：紧跟着用同一个 name 上传会拿到 404 / 422
            # （实测）。等它真的从列表里消失再继续。
            for _ in range(10):
                time.sleep(1.5)
                cc, rr = call('%s/releases/%d/assets' % (API, rel['id']), a.token)
                if cc != 200:
                    continue
                names = [x['name'] for x in json.loads(rr) if x['name'].endswith('.zip')]
                if not names:
                    break
                print('    仍在列表里：%s，继续等' % names)

    upload_url = rel['upload_url'].split('{')[0]
    url = '%s?name=%s' % (upload_url, urllib.parse.quote(ascii_name))
    print('=== 上传附件 %s（本地名 %s） ===' % (ascii_name, fn))
    data = open(a.zip, 'rb').read()
    code, resp = call(url, a.token, 'POST', raw=data, ctype='application/zip')
    if code not in (200, 201):
        print('  失败 %s %s' % (code, resp[:300]))
        return 1
    info = json.loads(resp)
    print('  成功 name=%s size=%s' % (info.get('name'), info.get('size')))
    print('=== 完成 ===')
    print('  https://github.com/%s/%s/releases' % (OWNER, REPO))
    return 0


if __name__ == '__main__':
    sys.exit(main())
