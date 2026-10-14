#!/usr/bin/env bash
# 在 Linux 上把新编的 SideStore 换进 LiveContainer+SideStore 合体包（不用 Mac / GitHub Actions）。
#
#   tools/linux-embed-sidestore.sh <底包 LiveContainer+SideStore.ipa> <SideStore.ipa> -v <版本> [-o OUT.ipa]
#
# 底包里 LiveContainer 本身不动（Info.plist 的 SideStore 键、设置项、SideStoreSupport.framework 都是现成的），
# 来自 SideStore 的部分照 .github/build_github.sh 重做一遍：SideStoreApp.framework（dylib 化）、两份 intentdefinition、
# Metadata.appintents、小组件。-v 写进 LiveContainer 的版本号：SideStore 拿它跟源里的 version 比是否有更新，
# 用四段（如 3.8.10.1）——不是语义化版本时按字符串比，不同就提示更新。
# SideStore.ipa 用 SideStore-LC 仓库的 tools/linux-build.sh 出。需要 ~/data/sdk/rcodesign（ad-hoc 签名，代替 ldid）。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OUT=build/linux/LiveContainer+SideStore.ipa VER=
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUT=$2; shift ;;
    -v) VER=$2; shift ;;
    -*) sed -n '2,11p' "$0"; exit 2 ;;
    *) args+=("$1") ;;
  esac
  shift
done
[ ${#args[@]} = 2 ] && [ -n "$VER" ] || { sed -n '2,11p' "$0"; exit 2; }
BASE=$(realpath "${args[0]}") SS=$(realpath "${args[1]}")
RCS=${RCODESIGN:-$HOME/data/sdk/rcodesign/rcodesign}
B=build/linux/embed
rm -rf $B && mkdir -p $B/ss
unzip -q "$BASE" -d $B
unzip -q "$SS" -d $B/ss
A=$B/Payload/LiveContainer.app F=$A/Frameworks/SideStoreApp.framework
[ -d $A/Frameworks/SideStoreSupport.framework ] || { echo "底包不是 LiveContainer+SideStore 合体包"; exit 1; }

# 1. 去掉底包里来自旧 SideStore 的部分
rm -rf $F $A/PlugIns/LiveWidgetExtension.appex $A/Metadata.appintents $A/Intents.intentdefinition $A/ViewApp.intentdefinition
find $A -name _CodeSignature -prune -exec rm -rf {} +  # 装的时候 SideStore 统一重签

# 2. SideStore.app → SideStoreApp.framework，主程序改成 LiveContainer 能加载的 dylib
mv $B/ss/Payload/SideStore.app $F
python3 tools/linux/dylibify.py $F/SideStore
$RCS sign $F/SideStore >/dev/null 2>&1  # ad-hoc，同 build_github.sh 的 ldid -S""
cp .github/sidelc/LCAppInfo.plist $F/

# 3. Intents：两份定义和 App Intents 元数据放到 LiveContainer 顶层，刷新意图的类型改指 SideStoreSupport 里的同名实现
cp $F/Intents.intentdefinition $F/ViewApp.intentdefinition $A/
cp -R $F/Metadata.appintents $A/Metadata.appintents
python3 - $A/Metadata.appintents/extract.actionsdata <<'PY'
import sys
p = sys.argv[1]
s = open(p, "rb").read()
for name in (b"20RefreshAllAppsIntentV", b"26RefreshAllAppsWidgetIntentV"):
    assert b"9SideStore" + name in s, name
    s = s.replace(b"9SideStore" + name, b"16SideStoreSupport" + name)
open(p, "wb").write(s)
PY

# 4. 小组件：AltWidgetExtension → LiveWidgetExtension
W=$A/PlugIns/LiveWidgetExtension.appex
mv $F/PlugIns/AltWidgetExtension.appex $W
mv $W/AltWidgetExtension $W/LiveWidgetExtension
python3 - $W/Info.plist <<'PY'
import plistlib, sys
p = sys.argv[1]
d = plistlib.load(open(p, "rb"))
d["CFBundleIdentifier"], d["CFBundleExecutable"] = "com.kdt.livecontainer.LiveWidget", "LiveWidgetExtension"
plistlib.dump(d, open(p, "wb"), fmt=plistlib.FMT_BINARY)
PY
$RCS sign -e .github/sidelc/LiveWidgetExtension_adhoc.xml $W/LiveWidgetExtension >/dev/null 2>&1

# 5. 版本号，打包
python3 - $A/Info.plist "$VER" <<'PY'
import plistlib, sys
p, ver = sys.argv[1:]
d = plistlib.load(open(p, "rb"))
d["CFBundleShortVersionString"] = d["CFBundleVersion"] = ver
plistlib.dump(d, open(p, "wb"), fmt=plistlib.FMT_BINARY)
PY
mkdir -p "$(dirname "$OUT")"
OUT=$(realpath "$OUT")
rm -f "$OUT" && (cd $B && zip -qry "$OUT" Payload)
ssver=$(python3 -c 'import plistlib,sys;print(plistlib.load(open(sys.argv[1],"rb"))["CFBundleShortVersionString"])' $F/Info.plist)
echo "== 出包 $OUT ($(du -h "$OUT" | cut -f1)，LiveContainer $VER + SideStore $ssver)"
