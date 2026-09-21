---
name: github-remote
description: Use when the user invokes $github-remote, mentions GitHub Remote, or requests supported GitHub Remote data or operations.
---

# GitHub Remote

## Overview

Use this skill for requests within the verified GitHub Remote capability boundary. Select a live callable tool from the catalog below and report provider evidence without inventing unsupported facts.

## Core Rules

- Use the bound `github-remote` MCP only when its live callable tools are available in the current runtime.
- Select the narrowest live callable operation that directly answers the request and follow its current interface.
- Preserve exact tool names, returned identifiers, status values, timestamps, units, and scope.
- Do not invent provider facts, records, prices, dates, permissions, or operation results.
- Do not recreate this connector with shell commands, direct HTTP requests, or hand-written protocol calls.
- Keep credentials, private content, and authorization material out of prompts, logs, and final answers.
- Require explicit confirmation before any external write, send, purchase, order, deletion, publication, merge, or permission change.

## Tools

- `add_comment_to_pending_review`: Add review comment to the requester's latest pending pull request review.
- `add_issue_comment`: Add a comment and/or reaction to a specific issue or issue comment in a GitHub repository.
- `add_reply_to_pull_request_comment`: Add a reply and/or reaction to an existing pull request comment.
- `create_branch`: Create a new branch in a GitHub repository.
- `create_or_update_file`: Create or update a single file in a GitHub repository.
- `create_pull_request`: Create a new pull request in a GitHub repository.
- `create_repository`: Create a new GitHub repository in your account or specified organization.
- `delete_file`: Delete a file from a GitHub repository.
- `fork_repository`: Fork a GitHub repository to your account or specified organization.
- `get_commit`: Get details for a commit from a GitHub repository.
- `get_file_contents`: Get the contents of a file or directory from a GitHub repository.
- `get_label`: Get a specific label from a repository.
- `get_latest_release`: Get the latest release in a GitHub repository.
- `get_me`: Get details of the authenticated GitHub user.
- `get_release_by_tag`: Get a specific release by its tag name in a GitHub repository.
- `get_tag`: Get details about a specific git tag in a GitHub repository.
- `get_team_members`: Get member usernames of a specific team in an organization.
- `get_teams`: Get details of the teams the user is a member of.
- `issue_read`: Get information about a specific issue in a GitHub repository.
- `issue_write`: Create a new or update an existing issue in a GitHub repository.
- `list_branches`: List branches in a GitHub repository.
- `list_commits`: Get list of commits of a branch in a GitHub repository.
- `list_issue_fields`: List issue fields for a repository or organization.
- `list_issue_types`: List supported issue types for a repository or its owner organization.
- `list_issues`: List issues in a GitHub repository.
- `list_pull_requests`: List pull requests in a GitHub repository.
- `list_releases`: List releases in a GitHub repository.
- `list_repository_collaborators`: List collaborators of a GitHub repository.
- `list_tags`: List git tags in a GitHub repository.
- `merge_pull_request`: Merge a pull request in a GitHub repository.
- `pull_request_read`: Get information on a specific pull request in GitHub repository.
- `pull_request_review_write`: Create and/or submit, delete review of a pull request.
- `push_files`: Push multiple files to a GitHub repository in a single commit.
- `request_copilot_review`: Request a GitHub Copilot code review for a pull request.
- `run_secret_scanning`: Scan files, content, or recent changes for secrets such as API keys, passwords, tokens, and credentials.
- `search_code`: Fast and precise code search across ALL GitHub repositories using GitHub's native search engine.
- `search_commits`: Search for commits across GitHub repositories using GitHub's commit search syntax.
- `search_issues`: Search issues using natural-language semantic matching.
- `search_pull_requests`: Search for pull requests in GitHub repositories using issues search syntax already scoped to is:pr.
- `search_repositories`: Find GitHub repositories by name, description, readme, topics, or other metadata.
- `search_users`: Find GitHub users by username, real name, or other profile information.
- `sub_issue_write`: Add a sub-issue to a parent issue in a GitHub repository.
- `update_pull_request`: Update an existing pull request in a GitHub repository.
- `update_pull_request_branch`: Update the branch of a pull request with the latest changes from the base branch.
- Choose the narrowest live callable tool that directly satisfies the user's intent; use returned identifiers to chain follow-up operations only when necessary.

## Workflow

1. Identify the requested entity, identifier, scope, time range, filters, operation, and output format.
2. Classify the request as lookup, search, analysis, creation, update, export, deletion, sending, purchase, permission change, or another provider operation.
3. Resolve ambiguous identifiers with a live lookup when available; never guess a code, ID, path, coordinate, record, order, or account.
4. Pass only currently supported arguments and preserve provider pagination, status, units, timestamps, and returned identifiers.
5. Inspect the outer tool error and provider status before reading result fields; do not treat an empty or partial response as complete success.

## Query Guidance

- Ask only for missing inputs required to select or safely execute the operation.
- Keep unrelated entities, time windows, accounts, and writes separate.
- State filters, result limits, sort order, output format, and data time when available.
- Preserve the user's requested scope and label any normalization or model interpretation.

## Failure Handling

- If no live GitHub Remote callable tool is available, report that the connector is unavailable in the current runtime.
- For authorization, quota, timeout, invalid-argument, permission, provider, or missing-tool errors, report the failed operation without exposing secrets.
- Retry at most once only after a safe correction such as narrowing scope, supplying a known identifier, reducing page size, or removing an unsupported optional field.
- For empty or partial results, report the exact query scope and provider status; never fill missing fields from memory.
- Do not silently substitute another provider when this connector was specifically requested.

## Result Contract

- Separate returned provider facts from model interpretation and derived calculations.
- Preserve identifiers, URLs, paths, dates, timestamps, units, filters, page scope, totals, status, and provider caveats when returned.
- Do not describe one page, sample, or preview as complete unless the provider confirms completeness.
