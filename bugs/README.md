# Worktreeflow Bug Repository

This directory contains detailed documentation for all identified bugs in the worktreeflow codebase.

## Summary

**Total Bugs Found:** 12

### By Severity
- **Critical:** 3 bugs (B01, B02, B03)
- **High Priority:** 2 bugs (B04, B05)
- **Medium Priority:** 4 bugs (B06, B07, B08, B09)
- **Low Priority:** 3 bugs (B10, B11, B12)

## Bug Index

### Critical Bugs (Fix Immediately)

| ID | Title | Location | Impact |
|----|-------|----------|--------|
| [B01](b01.md) | Off-by-One Error in Branch Name Parsing | wtf.py:1490 | Branch names display with leading slash |
| [B02](b02.md) | Shell Injection Vulnerability in PR Creation | wtf.py:1143-1156 | Security risk: arbitrary command execution |
| [B03](b03.md) | Potential IndexError with merge_base | wtf.py:714, 881 | Application crashes with unhelpful error |

### High Priority Bugs

| ID | Title | Location | Impact |
|----|-------|----------|--------|
| [B04](b04.md) | Unconditional sync_main() in wt_new() | wtf.py:942 | Unexpected failures and side effects |
| [B05](b05.md) | Path Injection in Shell Commands | wtf.py:952-956 | Potential failures with special characters in paths |

### Medium Priority Bugs

| ID | Title | Location | Impact |
|----|-------|----------|--------|
| [B06](b06.md) | Redundant json imports | wtf.py:1072, 1392, 1602 | Code quality/consistency |
| [B07](b07.md) | Overly Broad Exception Handling | Multiple locations | Hides real bugs, makes debugging hard |
| [B08](b08.md) | Hardcoded Default Upstream Repository | wtf.py:49 | Wrong defaults for all other projects |
| [B09](b09.md) | Unsafe Repo Name Extraction | wtf.py:577 | Crashes on malformed upstream repo |

### Low Priority Bugs

| ID | Title | Location | Impact |
|----|-------|----------|--------|
| [B10](b10.md) | Inconsistent Title/Body Default Checks | wtf.py:1113, 1125 | Edge case: explicit defaults get overridden |
| [B11](b11.md) | Missing Resource Cleanup for Subprocesses | Throughout | Theoretical: zombie processes (unlikely) |
| [B12](b12.md) | Unformatted datetime in User Messages | wtf.py:298 | Cosmetic: messy timestamp format |

## Quick Start

1. **Review critical bugs first:** Start with B01, B02, B03
2. **Read each bug file:** Contains detailed description, impact, and proposed fixes
3. **Prioritize fixes:** Critical → High → Medium → Low
4. **Test after fixes:** Each bug file includes test cases where applicable

## Bug File Format

Each bug file contains:
- **Severity**: Critical/High/Medium/Low
- **Location**: File and line numbers
- **Description**: What the bug is
- **Current Code**: Code snippet showing the problem
- **Problem**: Detailed explanation
- **Impact**: What happens because of this bug
- **Proposed Fix**: One or more solutions with code examples
- **Recommendation**: Best approach to fix

## Contributing

When fixing bugs:
1. Read the full bug documentation
2. Implement the recommended fix (or propose an alternative)
3. Add tests to prevent regression
4. Update the bug file with "Fixed in commit: [hash]"
5. Move the bug file to `bugs/fixed/` directory

## Related Documentation

- [Main README](../README.md)
- [Source Code](../src/worktreeflow/wtf.py)
