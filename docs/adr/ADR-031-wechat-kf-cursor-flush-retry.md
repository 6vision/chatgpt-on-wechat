# ADR 031: fix(wechat-kf): retry cursor persistence after transient write failures

Status: Accepted for this candidate.

## Context

A failed cursor flush leaves the new value in memory. set() then treats the same value as already saved, and a later callback reads it without retrying persistence. A restart replays the old cursor and can duplicate replies.

## Decision

Track whether the current cursor snapshot is still dirty, report flush success internally, and retry dirty snapshots both on repeated set and on the next callback get. Clear the flag only after atomic replacement succeeds.

## Consequences

Temporary disk failures remain best-effort and retain the in-memory progress, but no longer permanently suppress retry. Clean reads and unchanged sets remain free of disk writes.

## Validation

The focused regression fails on the unmodified base and passes with this change. tests/test_wechat_kf_cursor_flush_retry.py passed locally; changed Python files passed CI-equivalent Ruff F checks. These are local native-contract checks using controlled doubles, not live provider or channel acceptance.


Limitations: Existing WeChat-KF callback suites require web.py and wechatpy, unavailable in installed runtimes; no installs or live channel calls were made. Native CursorStore methods and filesystem persistence are exercised directly.