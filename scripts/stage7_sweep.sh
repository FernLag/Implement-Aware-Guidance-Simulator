#!/usr/bin/env bash
# Run the whole Stage 7 sweep through the container, one case at a time.
#
# The case list comes from stage7_compare.py, so the thing that runs the cases
# and the thing that analyses them cannot drift apart. A case that fails is
# reported and the sweep carries on: a missing case is handled honestly by the
# analysis, and losing the other nine to the first failure is not.
set -uo pipefail

cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-aggsim-stage7}
SECONDS_RUN=${SECONDS_RUN:-60}

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "No image '$IMAGE'. Build it first:"
  echo "  docker build -t $IMAGE -f docker/stage7/Dockerfile ."
  exit 1
fi

mkdir -p build/stage7
failed=()
while read -r name speed slope implement; do
  [[ -z "$name" ]] && continue
  echo
  echo "=============================================================="
  echo " $name   speed ${speed} m/s   slope ${slope} deg   $implement"
  echo "=============================================================="
  if docker run --rm -v "$PWD/build:/work/build" \
       -e NAME="$name" -e SLOPE="$slope" -e SPEED="$speed" \
       -e IMPLEMENT="$implement" -e SECONDS_RUN="$SECONDS_RUN" \
       "$IMAGE"; then
    echo "-- $name done"
  else
    echo "-- $name FAILED"
    failed+=("$name")
  fi
done < <(python3 scripts/stage7_compare.py --list-cases)

echo
if ((${#failed[@]})); then
  echo "${#failed[@]} case(s) failed: ${failed[*]}"
  echo "The analysis reports these as not run rather than guessing at them."
else
  echo "all cases ran"
fi
python3 scripts/stage7_compare.py --sweep
