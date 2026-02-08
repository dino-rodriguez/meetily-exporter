# CLAUDE.md

## Project

Meetily Exporter is a standalone Python CLI that reads Meetily's SQLite database and exports meetings as markdown files.

## Python Style

### Typing
- Use full type hints on all public functions and methods.
- Prefer modern typing syntax: `list[str]`, `dict[str, int]`, `X | None`.

### Docstrings
- Use Google-style docstrings.
- Do not repeat types in docstrings — types belong in the signature.
- Docstrings explain behavior, intent, side effects, and errors.

Template:

```python
"""Short summary.

Optional details about behavior and edge cases.

Args:
    param: Description of purpose.

Returns:
    Description of what the caller receives.

Raises:
    ErrorType: When and why it happens.
"""
```
