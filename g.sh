#!/bin/sh
# 汉化仓库速查：g 查看最近提交 / s 看未提交改动 / d 看某次改了什么
#             p 开工前自检（每次动文件前先跑这个）
#             b 构建 + 部署到游戏（默认），加 --no-install 只出包
#             i 同 b（老习惯，保留）
#             c 提交并推 GitHub —— 推上去就自动出包、发两端发行版，不用管别的
# 用法：sh g.sh [s|d <n>|p|g|b [--no-install|--check|--force]|i|c "<提交说明>"]
cd "$(dirname "$0")" || exit 1

GH_REPO="mctrr/Off_the_Record_Plus-Chinese-.git"
# 推 GitHub 的两条路，先试代理再试直连。
# 这台机器的网络状态会变：有时只有 v2rayN 的 10808 通、直连 443 超时；
# 有时反过来（节点挂了直连反而好）。两种都试，谁通算谁的。
GH_PROXY="http://127.0.0.1:10808"

case "$1" in
  b|i)
    shift
    exec "${PYTHON:-python}" build.py "$@"
    ;;
  p)
    echo "=== 开工前自检 ==="
    echo "HEAD     : $(git rev-parse --short HEAD)  $(git log -1 --format=%s)"
    echo "分支     : $(git branch --show-current)"
    n=$(git status --porcelain | wc -l)
    if [ "$n" -gt 0 ]; then
      echo "工作区   : ★ 脏 —— 有 $n 处未提交改动，先看清再动"
      git status --short
    else
      echo "工作区   : 干净（磁盘 == HEAD）"
    fi
    echo "补丁文件 : $(wc -c < 新的汉化补丁.txt) 字节  $(ls -l --time-style=+%Y-%m-%d_%H:%M 新的汉化补丁.txt | awk '{print $6}')"
    echo "ID 行数  : $(sed '1s/^\xEF\xBB\xBF//' 新的汉化补丁.txt | grep -cE '^[0-9]{5} ')"
    if [ "$(sed '1s/^\xEF\xBB\xBF//' str_en.txt | cut -c1-5)" = "$(sed '1s/^\xEF\xBB\xBF//' 新的汉化补丁.txt | cut -c1-5)" ]; then
      echo "ID 序列  : 与 str_en 完全一致"
    else
      echo "ID 序列  : ★ 与 str_en 不一致"
    fi
    if [ "$(git show HEAD:新的汉化补丁.txt 2>/dev/null | tr -cd '\r' | wc -c)" -gt 0 ]; then
      echo "仓库行尾 : CRLF（与磁盘一致）"
    else
      echo "仓库行尾 : ★ 仓库里存的是 LF，恢复出来的文件不等于磁盘文件"
    fi
    ;;

  s|"")
    echo "=== 未提交改动 ==="
    git status --short
    echo
    echo "=== 改动统计（按 ID 粒度）==="
    git diff --numstat
    ;;
  g)
    echo "=== 最近 15 次提交 ==="
    git log --format="%h %ad %s" --date=short -15
    ;;
  d)
    n="${2:-HEAD}"
    echo "=== $n 改动的 ID 行 ==="
    git show "$n" --format="%h %s" --unified=0 -- "新的汉化补丁.txt" \
      | grep -E '^[+-][0-9]{5} ' | head -100
    ;;
  f)
    cp 新的汉化补丁.txt _c.txt && ./BCS_TXT.exe _c.txt >/dev/null 2>&1 \
      && cp _c.bcs 新的汉化补丁.bcs && rm -f _c.txt _c.bcs \
      && echo "已打包 新的汉化补丁.bcs"
    ;;

  c)
    # 一条命令走完：提交 -> 推 GitHub -> 那边 CI 自动出包并发两端发行版。
    # GitCode 由 GitHub 上的「镜像到 GitCode」工作流反向覆盖，不用本地推。
    #
    # token 存在 .git/gh_token（不进仓库），没有就提示去建。
    shift
    MSG="${1:-}"
    if [ -z "$MSG" ]; then
      echo "用法：sh g.sh c \"提交说明\"" >&2
      exit 2
    fi

    TOKEN_FILE=".git/gh_token"
    if [ ! -f "$TOKEN_FILE" ]; then
      echo "缺 $TOKEN_FILE —— 把 GitHub 令牌（repo 权限）写进去，一行：" >&2
      echo "  echo ghp_xxxx > .git/gh_token" >&2
      exit 3
    fi
    TOKEN=$(tr -d ' \r\n' < "$TOKEN_FILE")

    git add -A || exit 1
    if git diff --cached --quiet; then
      echo "没有要提交的改动"
    else
      git commit -m "$MSG" || exit 1
    fi
    echo "提交： $(git log -1 --format='%h %s')"
    echo "推 GitHub……"

    URL="https://x-access-token:$TOKEN@github.com/$GH_REPO"
    HEAD_SHA=$(git rev-parse HEAD)

    # 清掉环境里的代理变量：这台机器上的 HTTP(S)_PROXY 指向沙箱代理，
    # 对 github.com 是 TLS 握手即断。之后依次试「走 v2rayN」和「直连」，
    # 因为这两个通道时好时坏，谁通算谁的。
    RC=1
    for mode in proxy direct; do
      if [ "$mode" = proxy ]; then
        echo "  [1/2] 经 $GH_PROXY ……"
        PCFG="-c http.proxy=$GH_PROXY -c https.proxy=$GH_PROXY"
      else
        echo "  [2/2] 直连 ……"
        PCFG="-c http.proxy= -c https.proxy="
      fi
      env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
        git $PCFG -c credential.helper= \
        push "$URL" HEAD:refs/heads/main && RC=0 && MODE_OK=$mode && break
      RC=$?
      echo "    这条不通（exit $RC），换下一条"
    done

    if [ "$RC" -ne 0 ]; then
      echo "★ 两条路都不通（exit $RC）。改动已提交在本地，没丢。" >&2
      echo "  换个 VPN 节点，或换个网络后重试：" >&2
      echo "  sh g.sh c \"$MSG\"      # 会重新走一遍，已提交则只推" >&2
      exit "$RC"
    fi
    echo "  通了（$MODE_OK）"

    # 复核：远端真的变成这个 SHA 才算成（git push 有过 exit 0 但没推上去的情况）
    GOT=$(env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
          git $PCFG -c credential.helper= ls-remote "$URL" refs/heads/main 2>/dev/null | cut -f1)
    if [ "$GOT" != "$HEAD_SHA" ]; then
      echo "★ 远端 main 是 ${GOT:-空}，不是本地的 $HEAD_SHA —— 没推上去" >&2
      exit 4
    fi
    echo "GitHub main = $(echo "$HEAD_SHA" | cut -c1-7)  已核对"
    echo "GitHub Actions 会自动出包并发两端发行版，约 3-5 分钟。"
    echo "看进度： https://github.com/mctrr/Off_the_Record_Plus-Chinese-/actions"
    ;;
esac
