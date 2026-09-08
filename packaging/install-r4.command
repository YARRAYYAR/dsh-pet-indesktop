#!/bin/zsh
set -eu
script_dir="${0:A:h}"
app_source="$script_dir/DSH-Pet-r4.app"
install_target="/Applications/DSH-Pet-r4.app"
trash_dir="$HOME/.Trash"
archive="${script_dir:h}/DSH-Pet-r4.zip"

if [[ ! -d "$app_source" ]]; then
  echo '请先解压 ZIP，再运行安装脚本。'
  exit 1
fi
"$app_source/Contents/MacOS/DSH-Pet-r4" --selftest
mkdir -p "$trash_dir"
if [[ -e "$install_target" ]]; then
  mv "$install_target" "$trash_dir/DSH-Pet-r4-previous-$(date +%Y%m%d-%H%M%S)-$$.app"
fi
ditto "$app_source" "$install_target"
"$install_target/Contents/MacOS/DSH-Pet-r4" --selftest
open "$install_target"
sleep 3
if ! /usr/bin/pgrep -f '/Applications/DSH-Pet-r4.app/Contents/MacOS/DSH-Pet-r4' >/dev/null; then
  echo '应用尚未成功启动，保留 ZIP 和解压目录，请手动检查。'
  exit 1
fi

# 仅清理本安装包的标准解压目录；被移动或重命名时保留下载文件。
if [[ "${script_dir:t}" == 'DSH-Pet-r4' ]]; then
  [[ ! -f "$archive" ]] || mv "$archive" "$trash_dir/DSH-Pet-r4-$(date +%Y%m%d-%H%M%S)-$$.zip"
  mv "$script_dir" "$trash_dir/DSH-Pet-r4-unpacked-$(date +%Y%m%d-%H%M%S)-$$"
fi
echo '安装完成。下载包已移入废纸篓，可恢复。'
