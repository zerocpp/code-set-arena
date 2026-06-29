#!/usr/bin/env bash
set -euo pipefail

VERSION_TAG="v7.1.3"
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
STUDENT_MANUAL="output/pdf/CodeSetArena-学生端-安装使用手册-${VERSION_TAG}.pdf"
TEACHER_MANUAL="output/pdf/CodeSetArena-助教端-安装使用手册-${VERSION_TAG}.pdf"
STUDENT_CLI_MANUAL="output/pdf/CodeSetArena-学生端-CLI使用手册-${VERSION_TAG}.pdf"
TEACHER_CLI_MANUAL="output/pdf/CodeSetArena-助教端-CLI使用手册-${VERSION_TAG}.pdf"
RELEASE_NOTES_MD="output/release-notes/CodeSetArena-${VERSION_TAG}-测试人员更新日志.md"
RELEASE_NOTES_PDF="output/pdf/CodeSetArena-${VERSION_TAG}-测试人员更新日志.pdf"
DOCKER_OFFLINE_DIR="${DIST_DIR}/docker-offline-${VERSION_TAG}"

build_image() {
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build --platform "${TARGET_PLATFORM}" --load "$@"
  else
    docker build --platform "${TARGET_PLATFORM}" "$@"
  fi
}

if [[ ! -f "${STUDENT_MANUAL}" || ! -f "${TEACHER_MANUAL}" || ! -f "${STUDENT_CLI_MANUAL}" || ! -f "${TEACHER_CLI_MANUAL}" ]]; then
  echo "missing PDF manuals under output/pdf; run scripts/generate_install_manuals_v713.py and scripts/generate_cli_manuals_v713.py first" >&2
  exit 1
fi
if [[ ! -f "${RELEASE_NOTES_MD}" || ! -f "${RELEASE_NOTES_PDF}" ]]; then
  echo "missing release notes; run scripts/generate_release_notes_v713.py first" >&2
  exit 1
fi

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

cp deploy/student/docker-compose.yml deploy/student/.env.example deploy/student/README.md "${STUDENT_RELEASE_DIR}/"
cp deploy/teacher/docker-compose.yml deploy/teacher/.env.example deploy/teacher/README.md "${TEACHER_RELEASE_DIR}/"
cp "${STUDENT_MANUAL}" "${DIST_DIR}/CodeSetArena-学生端-安装使用手册-${VERSION_TAG}.pdf"
cp "${TEACHER_MANUAL}" "${DIST_DIR}/CodeSetArena-助教端-安装使用手册-${VERSION_TAG}.pdf"
cp "${STUDENT_CLI_MANUAL}" "${DIST_DIR}/CodeSetArena-学生端-CLI使用手册-${VERSION_TAG}.pdf"
cp "${TEACHER_CLI_MANUAL}" "${DIST_DIR}/CodeSetArena-助教端-CLI使用手册-${VERSION_TAG}.pdf"
cp "${RELEASE_NOTES_MD}" "${DIST_DIR}/"
cp "${RELEASE_NOTES_PDF}" "${DIST_DIR}/"
cp "${STUDENT_MANUAL}" "${STUDENT_RELEASE_DIR}/"
cp "${TEACHER_MANUAL}" "${TEACHER_RELEASE_DIR}/"
cp "${STUDENT_CLI_MANUAL}" "${STUDENT_RELEASE_DIR}/"
cp "${TEACHER_CLI_MANUAL}" "${TEACHER_RELEASE_DIR}/"
cp "${RELEASE_NOTES_MD}" "${STUDENT_RELEASE_DIR}/"
cp "${RELEASE_NOTES_MD}" "${TEACHER_RELEASE_DIR}/"
cp "${RELEASE_NOTES_PDF}" "${STUDENT_RELEASE_DIR}/"
cp "${RELEASE_NOTES_PDF}" "${TEACHER_RELEASE_DIR}/"

if [[ -d "${DOCKER_OFFLINE_DIR}" ]]; then
  mkdir -p "${STUDENT_RELEASE_DIR}/docker-offline" "${TEACHER_RELEASE_DIR}/docker-offline"
  tar --exclude='*.part' --exclude='./codesetarena' -cf - -C "${DOCKER_OFFLINE_DIR}" . | tar -xf - -C "${STUDENT_RELEASE_DIR}/docker-offline"
  tar --exclude='*.part' --exclude='./codesetarena' -cf - -C "${DOCKER_OFFLINE_DIR}" . | tar -xf - -C "${TEACHER_RELEASE_DIR}/docker-offline"
fi

tar -czf "${STUDENT_ARCHIVE}" -C "${DIST_DIR}" "codesetarena-student-local-${VERSION_TAG}-${PLATFORM_LABEL}"
tar -czf "${TEACHER_ARCHIVE}" -C "${DIST_DIR}" "codesetarena-teacher-local-${VERSION_TAG}-${PLATFORM_LABEL}"

echo "created ${STUDENT_ARCHIVE}"
echo "created ${TEACHER_ARCHIVE}"
