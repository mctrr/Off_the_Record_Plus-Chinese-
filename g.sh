#!/bin/sh
# 汉化仓库速查：g 查看最近提交 / s 看未提交改动 / d 看某次改了什么
#             p 开工前自检（每次动文件前先跑这个）
#             b 构建（体检 + 打包 bcs + 出 build/ 发布包），多余参数透传给 build.py
#             i 构建并部署到游戏（覆盖前自动备份到 _backup/）
# 用法：sh g.sh [s|d <n>|p|g|b [--check|--install|--force]|i]
cd "$(dirname "$0")" || exit 1

case "$1" in
  b)
    shift
    exec "${PYTHON:-python}" build.py "$@"
    ;;
  i)
    shift
    exec "${PYTHON:-python}" build.py --install "$@"
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
esac
