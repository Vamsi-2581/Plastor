#!/usr/bin/env bash
# 공개 저장소 올리기: 로컬 이력 없이 현재 커밋 상태만, 공개하지 않을 경로를 빼고 올린다.
# 이유: 로컬 이력에는 다른 프로젝트 그림에서 나온 고정물(fixtures/ 등)이 들어 있어, 이력째 올리면 그것까지 공개된다.
# 공개 저장소의 이력은 지키며 그 위에 새 상태를 한 커밋으로 쌓는다(강제 푸시 안 함). 외부 기여자의 포크·합치기 요청이 깨지지 않게.
# 지난번에 올린 뒤 공개 저장소에 외부 변경(합친 PR 등)이 있으면 덮어쓰지 않고 멈춘다: 먼저 그 변경을 로컬로 가져온다.
# 사용: bash tools/publish_public.sh <깃허브 주인/저장소>   (처음 한 번은 저장소가 없으면 만든다)
set -euo pipefail
REPO="${1:?깃허브 주인/저장소 를 주세요}"
SRC="$(git rev-parse --show-toplevel)"
LAST="$SRC/.git/mh_public_last"
TMP="${TMPDIR:-/tmp}/mh_publish_$$"
EXCLUDE=(fixtures results packs sessions experiments bench/m0/real_bird bench/m0/real_bison)
rm -rf "$TMP"
git clone -q --no-hardlinks "$SRC" "$TMP"
cd "$TMP"
git checkout -q --orphan public
for p in "${EXCLUDE[@]}"; do
  if [ -e "$p" ]; then git rm -r -q --cached "$p"; rm -rf "$p"; fi
done
TREE=$(git write-tree)
MSG="공개본: $(git -C "$SRC" log -1 --format=%h) 시점 상태(공개하지 않을 경로 뺌)"
ID=(-c user.name="$(git -C "$SRC" config user.name)" -c user.email="$(git -C "$SRC" config user.email)")
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --description "LLM 이 숙련 3D 모델러처럼 크리처 도면에서 3D 메시를 만들게 돕는 무료 로컬 하네스(Blender + Rust)" >/dev/null
fi
git remote add public "https://github.com/$REPO.git"
if git fetch -q public main 2>/dev/null; then
  HEAD_PUB=$(git rev-parse FETCH_HEAD)
  if [ -f "$LAST" ] && [ "$(cat "$LAST")" != "$HEAD_PUB" ]; then
    echo "멈춤: 지난번에 올린 뒤 공개 저장소 main 에 외부 변경이 있다($HEAD_PUB). 먼저 그 변경을 로컬로 가져온 뒤 다시 올린다." >&2
    exit 1
  fi
  if [ "$(git rev-parse "FETCH_HEAD^{tree}")" = "$TREE" ]; then
    echo "바뀐 것 없음: https://github.com/$REPO"
    cd "$SRC"; rm -rf "$TMP"; exit 0
  fi
  C=$(git "${ID[@]}" commit-tree "$TREE" -p "$HEAD_PUB" -m "$MSG")
else
  C=$(git "${ID[@]}" commit-tree "$TREE" -m "$MSG")
fi
git push -q public "$C:refs/heads/main"
echo "$C" > "$LAST"
echo "올림: https://github.com/$REPO (파일 $(git ls-tree -r --name-only "$C" | wc -l)개, 커밋 ${C:0:7})"
cd "$SRC"
rm -rf "$TMP"
