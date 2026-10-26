#!/bin/sh
# 把本地仓库推去 GitHub，覆盖那份 2025-06 的旧快照。
# 用法：sh push_github.sh <你的GitHub用户名> <PAT>
#
# 例：sh push_github.sh mctrr ghp_xxxxxxxxxxxx
#
# 推完会自动删掉带 token 的 remote，不给后续操作留痕迹。
cd "$(dirname "$0")" || exit 1

USER="${1:-}"
TOKEN="${2:-}"

if [ -z "$USER" ] || [ -z "$TOKEN" ]; then
  cat <<'EOF'
用法：sh push_github.sh <用户名> <PAT>

PAT 怎么来：
  https://github.com/settings/tokens → Generate new token (classic)
  勾 repo + workflow 两项，生成后复制 ghp_ 开头的字符串

注意：PAT 等于密码。这条命令只在本机执行，别把 PAT 贴到公开地方。
EOF
  exit 1
fi

GH="https://github.com/mctrr/Off_the_Record_Plus-Chinese-.git"

echo "=== 当前 HEAD ==="
git log --oneline -1
echo
echo "=== 将要覆盖 $GH ==="
printf "确认要 force push 到 GitHub 吗？这会把仓里的旧内容全部覆盖（旧内容仍留在 git 历史里）。\n  输入 yes 继续："
read -r ans
if [ "$ans" != "yes" ]; then
  echo "已取消"
  exit 0
fi

# 用 extraheader 而不是把 token 拼进 URL：失败时 git 会回显完整 URL
BASIC=$(printf '%s:%s' "$USER" "$TOKEN" | base64 -w0)
git config http.https://github.com/.extraheader "Authorization: Basic $BASIC"

cleanup() { git config --unset http.https://github.com/.extraheader 2>/dev/null; }
trap cleanup EXIT INT TERM

echo
echo "=== 推 main（force） ==="
if ! git push "$GH" HEAD:refs/heads/main --force; then
  echo "推送失败。常见原因："
  echo "  - PAT 权限不足（要勾 repo + workflow）"
  echo "  - 用户名写错"
  echo "  - 网络问题（这台机器访问 GitHub 偶尔要关掉证书吊销检查）"
  echo
  echo "网络问题的临时办法（只影响这一次）："
  echo "  git -c http.sslVerify=false push ..."
  exit 1
fi

echo
echo "=== 推 v* tag ==="
git tag -l 'v*' | while read -r t; do
  echo "  $t"
  git push "$GH" "refs/tags/$t:refs/tags/$t" --force 2>&1 | tail -1
done

echo
echo "=== 验证 ==="
sleep 3
REMOTE=$(git ls-remote "$GH" refs/heads/main | cut -f1)
LOCAL=$(git rev-parse HEAD)
echo "本地 $LOCAL"
echo "远端 $REMOTE"
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "✓ 一致"
else
  echo "✗ 不一致（推送可能未真正生效，重试一次）"
fi

echo
echo "下一步：去配 GITCODE_TOKEN Secret"
echo "  https://github.com/mctrr/Off_the_Record_Plus-Chinese-/settings/secrets/actions"
echo "  Name  GITCODE_TOKEN"
echo "  Value GitCode 访问令牌（write_repository 权限）"
