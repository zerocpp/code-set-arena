from pathlib import Path

import pytest

from codesetarena.constants import (
    AI_REVIEWER_STUDENT_NUMBER,
    KIND_PROBLEMS,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    KIND_REVIEWS,
    KIND_REVISION,
    STAGE1,
    STAGE2,
    STAGE3,
)
from codesetarena.package_names import (
    PackageNameError,
    assert_student_archive,
    assert_teacher_archive,
    student_package_name,
    teacher_bulk_name,
    teacher_package_name,
)


def test_v7_package_names():
    assert (
        student_package_name("2026000001", STAGE1, KIND_PROBLEMS)
        == "2026000001-student-stage1-problems.tar.gz"
    )
    assert (
        student_package_name("2026000001", STAGE2, KIND_REVIEWS)
        == "2026000001-student-stage2-reviews.tar.gz"
    )
    assert (
        student_package_name("2026000001", STAGE3, KIND_REVISION)
        == "2026000001-student-stage3-revision.tar.gz"
    )
    assert (
        teacher_package_name("2026000001", STAGE2, KIND_REVIEW_ASSIGNMENT)
        == "2026000001-teacher-stage2-review-assignment.tar.gz"
    )
    assert (
        teacher_package_name(AI_REVIEWER_STUDENT_NUMBER, STAGE2, KIND_REVIEW_ASSIGNMENT)
        == "AI-teacher-stage2-review-assignment.tar.gz"
    )
    assert (
        teacher_package_name("2026000001", STAGE3, KIND_REVIEW_FEEDBACK)
        == "2026000001-teacher-stage3-review-feedback.tar.gz"
    )
    assert teacher_bulk_name(STAGE2, "review-assignments") == (
        "teacher-stage2-review-assignments.tar.gz"
    )
    assert teacher_bulk_name(STAGE3, "review-feedbacks") == (
        "teacher-stage3-review-feedbacks.tar.gz"
    )


def test_role_sensitive_filename_assertions():
    assert_student_archive(
        Path("2026000001-student-stage1-problems.tar.gz"),
        "2026000001",
        STAGE1,
        KIND_PROBLEMS,
    )
    assert_teacher_archive(
        Path("2026000001-teacher-stage2-review-assignment.tar.gz"),
        "2026000001",
        STAGE2,
        KIND_REVIEW_ASSIGNMENT,
    )
    with pytest.raises(PackageNameError):
        assert_student_archive(
            Path("2026000001-teacher-stage2-review-assignment.tar.gz"),
            "2026000001",
            STAGE2,
            KIND_REVIEWS,
        )
