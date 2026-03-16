"""Tests for JobRepository."""

from library_layer.repositories.job_repo import JobRepository


def test_upsert_and_find(job_repo: JobRepository) -> None:
    job_repo.upsert("job-001", "running", 440)
    result = job_repo.find("job-001")
    assert result is not None
    assert result["job_id"] == "job-001"
    assert result["status"] == "running"
    assert result["appid"] == 440


def test_upsert_updates_status(job_repo: JobRepository) -> None:
    job_repo.upsert("job-002", "running", 730)
    job_repo.upsert("job-002", "complete", 730)
    result = job_repo.find("job-002")
    assert result is not None
    assert result["status"] == "complete"
    assert result["appid"] == 730


def test_find_missing_returns_none(job_repo: JobRepository) -> None:
    result = job_repo.find("nonexistent-job-id")
    assert result is None
