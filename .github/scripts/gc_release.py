#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在 GitCode 建发行版并上传附件。供 GitHub Actions 调用。

GitCode API 的两个坑（都实测确认过）：
1. **token 走 query 参数 `?access_token=`**，不接受 `Authorization: token xxx`
   头。用头认证一律 401，这也是本地脚本最初失败的原因。
2. **附件不是 POST 表单上传**，而是先 GET `.../releases/:tag/upload_url`
   拿一个预签名 OBS 地址和一组必须原样带回的 headers，再 PUT 文件过去。

用法：
    python gc_release.py --token T --tag v0.2a --zip path.zip [--body-file f]
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

OWNER = 'Fallend'
REPO = 'Off_the_Record_Plus'
API = 'https://api.gitcode.com/api/v5/repos/%s/%s' % (OWNER, REPO)


def call(method, path, token, body=None, raw=False, ctype=None):
    url = '%s%s' % (API, path)
    sep = '&' if '?' in url else '?'
    url = '%s%saccess_token=%s' % (url, sep, urllib.parse.quote(token))

    data = None
    headers = {'Accept': 'application/json',
               'User-Agent': 'github-actions-gc-release/1.0'}
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        else:
            data = body
            if ctype:
                headers['Content-Type'] = ctype

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = r.read()
            return r.status, (payload if raw else payload.decode('utf-8', 'replace'))
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
    args = ap.parse_args()

    if not os.path.exists(args.zip):
        print('找不到附件：%s' % args.zip)
        return 2

    body = ''
    if args.body_file and os.path.exists(args.body_file):
        body = open(args.body_file, encoding='utf-8').read()

    name = args.name or ('汉化补丁 %s' % args.tag)

    # ---- 1. 建发行版（tag 不存在时 GitCode 会拒绝，所以 tag 必须先推上去）
    print('=== 建发行版 %s ===' % args.tag)
    payload = {'tag_name': args.tag, 'name': name, 'body': body,
               'prerelease': False}
    code, resp = call('POST', '/releases', args.token, payload)
    if code in (200, 201):
        print('  已创建')
    elif code in (400, 409):
        # 已存在——改成更新描述，保证脚本可重复运行。
        # 更新必须用 PATCH：PUT 返回 404 Route Not Found（实测）
        print('  已存在（%s），改为更新' % code)
        code, resp = call('PATCH', '/releases/%s' % urllib.parse.quote(args.tag),
                          args.token, payload)
        print('  更新 -> %s %s' % (code, (resp or '')[:200]))
        if code not in (200, 201):
            return 1
    else:
        print('  失败 -> %s %s' % (code, resp[:400]))
        return 1

    # ---- 2. 取预签名上传地址
    fn = os.path.basename(args.zip)
    q = urllib.parse.urlencode({'file_name': fn})
    print('=== 取上传地址 %s ===' % fn)
    code, resp = call('GET', '/releases/%s/upload_url?%s'
                      % (urllib.parse.quote(args.tag), q), args.token)
    if code != 200:
        print('  失败 -> %s %s' % (code, resp[:400]))
        return 1
    try:
        info = json.loads(resp)
        up_url = info['url']
        up_headers = info.get('headers') or {}
    except Exception as e:
        print('  响应解析失败：%s\n%s' % (e, resp[:400]))
        return 1
    print('  拿到预签名地址')

    # ---- 3. PUT 上传（返回的 headers 必须原样带上，缺了 OBS 会拒）
    print('=== 上传附件 ===')
    content = open(args.zip, 'rb').read()
    h = dict(up_headers)
    if not any(k.lower() == 'content-type' for k in h):
        h['Content-Type'] = mimetypes.guess_type(fn)[0] or 'application/octet-stream'
    req = urllib.request.Request(up_url, data=content, headers=h, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            print('  上传成功 %s，%d 字节' % (r.status, len(content)))
    except urllib.error.HTTPError as e:
        print('  上传失败 %s %s' % (e.code, e.read().decode('utf-8', 'replace')[:400]))
        return 1
    except Exception as e:
        print('  上传失败 %s: %s' % (type(e).__name__, e))
        return 1

    print('=== 完成 ===')
    print('  https://gitcode.com/%s/%s/releases' % (OWNER, REPO))
    return 0


if __name__ == '__main__':
    sys.exit(main())
