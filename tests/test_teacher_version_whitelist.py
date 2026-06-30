import pytest

from codesetarena.constants import (
    KIND_PROBLEMS,
    KIND_REVIEWS,
    KIND_REVISION,
    ROLE_STUDENT,
    STAGE1,
    STAGE2,
    STAGE3,
)
from codesetarena.packages import PackageError
from codesetarena.teacher_version_gate import assert_student_package_version_allowed


def test_student_package_version_whitelist_allows_only_configured_versions():
    settings = {"allowed_student_versions": ["v7.1.6", "v7.1.5"]}
    for stage, kind in [(STAGE1, KIND_PROBLEMS), (STAGE2, KIND_REVIEWS), (STAGE3, KIND_REVISION)]:
        assert_student_package_version_allowed(
            {
                "package_role": ROLE_STUDENT,
                "package_stage": stage,
                "package_kind": kind,
                "version_tag": "v7.1.6",
            },
            settings,
        )


def test_student_package_version_whitelist_rejects_missing_or_disallowed_version():
    settings = {"allowed_student_versions": ["v7.1.6"]}

    with pytest.raises(PackageError, match="学生端版本 v7.1.5 不在当前允许列表"):
        assert_student_package_version_allowed(
            {
                "package_role": ROLE_STUDENT,
                "package_stage": STAGE1,
                "package_kind": KIND_PROBLEMS,
                "version_tag": "v7.1.5",
            },
            settings,
        )

    with pytest.raises(PackageError, match="学生包缺少 version_tag"):
        assert_student_package_version_allowed(
            {
                "package_role": ROLE_STUDENT,
                "package_stage": STAGE1,
                "package_kind": KIND_PROBLEMS,
            },
            settings,
        )
