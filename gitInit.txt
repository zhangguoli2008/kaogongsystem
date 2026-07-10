#!/usr/bin/env bash
set -euo pipefail

code_root=/Users/zhangguoli/Documents/Code
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

if [[ "$project_dir" == "$code_root" ]]; then
  printf '拒绝操作：请先把 gitInit.txt 复制到新工程目录，再运行 bash gitInit.txt。\n' >&2
  exit 1
fi

if [[ -e "$project_dir/.git" || -L "$project_dir/.git" ]]; then
  printf 'Git 已初始化：%s\n' "$project_dir"
else
  git init -b main "$project_dir"
fi

gitignore="$project_dir/.gitignore"
if [[ ! -e "$gitignore" ]]; then
  printf '# Common ignores added by gitInit\n' > "$gitignore"
elif [[ -s "$gitignore" && -n "$(tail -c 1 "$gitignore")" ]]; then
  printf '\n' >> "$gitignore"
fi

rules=(
  '.DS_Store'
  '*.log'
  '.env'
  '.env.*'
  '!.env.example'
  '.idea/'
  '.vscode/'
  'node_modules/'
  'dist/'
  'build/'
  '.gradle/'
  'DerivedData/'
  'Pods/'
  '__pycache__/'
  '*.py[cod]'
  '.venv/'
  'venv/'
  'target/'
  'out/'
  '*.class'
)

for rule in "${rules[@]}"; do
  if ! grep -Fqx -- "$rule" "$gitignore"; then
    printf '%s\n' "$rule" >> "$gitignore"
  fi
done

printf '\n本地 Git 初始化完成：%s\n' "$project_dir"
printf '首次本地提交：\n  git add .\n  git commit -m "Initial commit"\n'
printf '查看修改：\n  git status\n  git diff\n'
printf '比较最近两个版本：\n  git diff HEAD~1 HEAD\n'
printf '查看版本历史：\n  git log --oneline --graph --decorate\n'
