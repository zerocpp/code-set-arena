#!/usr/bin/env bash
set -euo pipefail

VERSION_TAG="${VERSION_TAG:-v7.1.9}"
DIST_ROOT="dist"
DIST_DIR="${DIST_ROOT}/${VERSION_TAG}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
PLATFORM_LABEL="${TARGET_PLATFORM//\//-}"
STUDENT_IMAGE="codesetarena-student:${VERSION_TAG}"
TEACHER_IMAGE="codesetarena-teacher:${VERSION_TAG}"
RUNTIME_IMAGE="codesetarena-runtime:${VERSION_TAG}"
STUDENT_RELEASE_DIR="${DIST_DIR}/codesetarena-student-local-${VERSION_TAG}-${PLATFORM_LABEL}"
TEACHER_RELEASE_DIR="${DIST_DIR}/codesetarena-teacher-local-${VERSION_TAG}-${PLATFORM_LABEL}"
STUDENT_ARCHIVE="${DIST_DIR}/codesetarena-student-local-${VERSION_TAG}-${PLATFORM_LABEL}.tar.gz"
TEACHER_ARCHIVE="${DIST_DIR}/codesetarena-teacher-local-${VERSION_TAG}-${PLATFORM_LABEL}.tar.gz"
DOCKER_OFFLINE_DIR="${DIST_DIR}/docker-offline-${VERSION_TAG}"

build_image() {
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build --platform "${TARGET_PLATFORM}" --load "$@"
  else
    docker build --platform "${TARGET_PLATFORM}" "$@"
  fi
}

rm -rf \
  "${STUDENT_RELEASE_DIR}" \
  "${TEACHER_RELEASE_DIR}" \
  "${DIST_DIR}/student" \
  "${DIST_DIR}/teacher" \
  "${DIST_DIR}/codesetarena-student-local-${VERSION_TAG}" \
  "${DIST_DIR}/codesetarena-teacher-local-${VERSION_TAG}" \
  "${DIST_DIR}/codesetarena-student-local-${VERSION_TAG}.tar.gz" \
  "${DIST_DIR}/codesetarena-teacher-local-${VERSION_TAG}.tar.gz"
mkdir -p "${STUDENT_RELEASE_DIR}" "${TEACHER_RELEASE_DIR}"

build_image --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" --build-arg "PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}" -f docker/student/Dockerfile -t "${STUDENT_IMAGE}" .
build_image --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" --build-arg "PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}" -f docker/teacher/Dockerfile -t "${TEACHER_IMAGE}" .
build_image -f docker/runtime/Dockerfile -t "${RUNTIME_IMAGE}" .

docker save "${STUDENT_IMAGE}" -o "${STUDENT_RELEASE_DIR}/codesetarena-student-${VERSION_TAG}.image.tar"
docker save "${TEACHER_IMAGE}" -o "${TEACHER_RELEASE_DIR}/codesetarena-teacher-${VERSION_TAG}.image.tar"

{
  echo "target_platform=${TARGET_PLATFORM}"
  echo "platform_label=${PLATFORM_LABEL}"
  echo "student_image=${STUDENT_IMAGE}"
  docker image inspect "${STUDENT_IMAGE}" --format 'student_image_os_arch={{.Os}}/{{.Architecture}}' || true
  echo "teacher_image=${TEACHER_IMAGE}"
  docker image inspect "${TEACHER_IMAGE}" --format 'teacher_image_os_arch={{.Os}}/{{.Architecture}}' || true
} > "${STUDENT_RELEASE_DIR}/PLATFORM.txt"
cp "${STUDENT_RELEASE_DIR}/PLATFORM.txt" "${TEACHER_RELEASE_DIR}/PLATFORM.txt"

cp deploy/student/docker-compose.yml "${STUDENT_RELEASE_DIR}/"
cp deploy/teacher/docker-compose.yml "${TEACHER_RELEASE_DIR}/"

if [[ -d "${DOCKER_OFFLINE_DIR}" ]]; then
  mkdir -p "${STUDENT_RELEASE_DIR}/docker-offline" "${TEACHER_RELEASE_DIR}/docker-offline"
  tar --exclude='*.part' --exclude='*.md' --exclude='*.pdf' --exclude='./codesetarena' -cf - -C "${DOCKER_OFFLINE_DIR}" . | tar -xf - -C "${STUDENT_RELEASE_DIR}/docker-offline"
  tar --exclude='*.part' --exclude='*.md' --exclude='*.pdf' --exclude='./codesetarena' -cf - -C "${DOCKER_OFFLINE_DIR}" . | tar -xf - -C "${TEACHER_RELEASE_DIR}/docker-offline"
fi

tar -czf "${STUDENT_ARCHIVE}" -C "${DIST_DIR}" "codesetarena-student-local-${VERSION_TAG}-${PLATFORM_LABEL}"
tar -czf "${TEACHER_ARCHIVE}" -C "${DIST_DIR}" "codesetarena-teacher-local-${VERSION_TAG}-${PLATFORM_LABEL}"

(
  cd "${DIST_DIR}"
  shasum -a 256 ./*.tar.gz > SHA256SUMS.txt
)

echo "created ${STUDENT_ARCHIVE}"
echo "created ${TEACHER_ARCHIVE}"
echo "updated ${DIST_DIR}/SHA256SUMS.txt"
