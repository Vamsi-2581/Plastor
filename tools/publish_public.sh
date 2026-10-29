#!/usr/bin/env bash
# 공개 저장소 올리기: 이력 없이 현재 커밋 상태만, 공개하지 않을 경로를 빼고 올린다.
# 이유: 로컬 이력에는 다른 프로젝트 그림에서 나온 고정물(fixtures/ 등)이 들어 있어, 이력째 올리면 그것까지 공개된다.
# 사용: bash tools/publish_public.sh <깃허브 주인/저장소>   (처음 한 번은 저장소가 없으면 만든다)
set -euo pipefail
REPO="${1:?깃허브 주인/저장소 를 주세요}"
SRC="$(git rev-parse --show-toplevel)"
TMP="${TMPDIR:-/tmp}/mh_publish_$$"
EXCLUDE=(fixtures results packs sessions experiments bench/m0/real_bird bench/m0/real_bison)
rm -rf "$TMP"
git clone -q --no-hardlinks "$SRC" "$TMP"
cd "$TMP"
git checkout -q --orphan public
for p in "${EXCLUDE[@]}"; do
  if [ -e "$p" ]; then git rm -r -q --cached "$p"; rm -rf "$p"; fi
done
git -c user.name="$(git -C "$SRC" config user.name)" -c user.email="$(git -C "$SRC" config user.email)" \
  commit -q -m "공개본: $(git -C "$SRC" log -1 --format=%h) 시점 상태(이력 없이, 공개하지 않을 경로 뺌)"
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --description "LLM 이 숙련 3D 모델러처럼 크리처 도면에서 3D 메시를 만들게 돕는 무료 로컬 하네스(Blender + Rust)" >/dev/null
fi
git remote add public "https://github.com/$REPO.git"
git push -q -f public public:main
echo "올림: https://github.com/$REPO (파일 $(git ls-files | wc -l)개)"
cd "$SRC"
rm -rf "$TMP"
