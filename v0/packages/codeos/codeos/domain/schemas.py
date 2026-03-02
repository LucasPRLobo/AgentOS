"""CodeOS I/O schemas — Pydantic v2 models for all CodeOS tools."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── FileRead ──────────────────────────────────────────────────────


class FileReadInput(BaseModel):
    path: str = Field(description="File path to read (relative to workspace root)")
    offset: int = Field(default=0, ge=0, description="Line offset to start reading from")
    limit: int = Field(default=0, ge=0, description="Max lines to read (0 = all)")


class FileReadOutput(BaseModel):
    content: str = Field(description="File content")
    lines: int = Field(ge=0, description="Number of lines returned")
    total_lines: int = Field(ge=0, description="Total lines in the file")


# ── FileWrite ─────────────────────────────────────────────────────


class FileWriteInput(BaseModel):
    path: str = Field(description="File path to write (relative to workspace root)")
    content: str = Field(description="Content to write to the file")


class FileWriteOutput(BaseModel):
    path: str = Field(description="Path that was written")
    bytes_written: int = Field(ge=0, description="Number of bytes written")
    sha256: str = Field(description="SHA-256 hash of the written content")


# ── Grep ──────────────────────────────────────────────────────────


class GrepMatch(BaseModel):
    file: str = Field(description="File path containing the match")
    line: int = Field(ge=1, description="Line number of the match")
    content: str = Field(description="Line content")


class GrepInput(BaseModel):
    pattern: str = Field(description="Regex pattern to search for")
    path: str = Field(default=".", description="Directory or file to search in")
    glob: str = Field(default="*", description="Glob pattern to filter files")


class GrepOutput(BaseModel):
    matches: list[GrepMatch] = Field(default_factory=list, description="List of matches")


# ── RunCommand ────────────────────────────────────────────────────


class RunCommandInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=30, gt=0, le=300, description="Timeout in seconds")


class RunCommandOutput(BaseModel):
    stdout: str = Field(description="Standard output")
    stderr: str = Field(description="Standard error")
    exit_code: int = Field(description="Process exit code")
    timed_out: bool = Field(default=False, description="Whether the command timed out")


# ── GitStatus ─────────────────────────────────────────────────────


class GitStatusInput(BaseModel):
    pass


class GitStatusOutput(BaseModel):
    branch: str = Field(description="Current branch name")
    staged: list[str] = Field(default_factory=list, description="Staged files")
    modified: list[str] = Field(default_factory=list, description="Modified files")
    untracked: list[str] = Field(default_factory=list, description="Untracked files")


# ── GitDiff ───────────────────────────────────────────────────────


class GitDiffInput(BaseModel):
    path: str = Field(default="", description="Path to diff (empty = all)")
    staged: bool = Field(default=False, description="Show staged changes")


class GitDiffOutput(BaseModel):
    diff: str = Field(description="Diff output")
    files_changed: int = Field(ge=0, description="Number of files changed")


# ── GitCommit ─────────────────────────────────────────────────────


class GitCommitInput(BaseModel):
    message: str = Field(description="Commit message")
    files: list[str] = Field(default_factory=list, description="Files to stage before commit")


class GitCommitOutput(BaseModel):
    sha: str = Field(description="Commit SHA")
    message: str = Field(description="Commit message used")
    files_committed: int = Field(ge=0, description="Number of files committed")
