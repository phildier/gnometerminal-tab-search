# Configurable Roots And Post Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional TOML configuration for launcher roots and a bash-only post-directory command while preserving tab-only behavior when the config file is absent.

**Architecture:** Keep runtime orchestration in `tab-search.py` and extend `tab_search_core.py` with pure helpers for config parsing, precedence, and launch command construction. Use TDD to add config behavior without disturbing the working tab-switch and existing-window terminal launch paths.

**Tech Stack:** Python 3, standard library `tomllib`, GNOME Terminal, xdotool, unittest

---

### Task 1: Config Parsing Helpers

**Files:**
- Modify: `tab_search_core.py`
- Modify: `tests/test_tab_search_core.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_missing_config_returns_none():
    ...

def test_parse_config_reads_roots_and_post_command():
    ...

def test_parse_config_rejects_invalid_roots():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_tab_search_core.py' -v`
Expected: import or assertion failures for missing config helpers

- [ ] **Step 3: Write minimal implementation**

Add a small config loader in `tab_search_core.py` that:
- reads TOML with `tomllib`
- returns `None` when the config file is absent
- validates `roots` and `post_cd_command`

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_tab_search_core.py' -v`
Expected: PASS

### Task 2: Config-Driven Directory Discovery

**Files:**
- Modify: `tab_search_core.py`
- Modify: `tests/test_tab_search_core.py`
- Modify: `tab-search.py`

- [ ] **Step 1: Write the failing tests**

Add tests for config-present precedence behavior and config-missing fallback behavior.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL because runtime still uses hardcoded launcher roots

- [ ] **Step 3: Write minimal implementation**

Update `tab-search.py` to:
- load config before directory discovery
- skip directory discovery entirely when config is absent
- use config roots when present

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

### Task 3: Post Command Launch Path

**Files:**
- Modify: `tab_search_core.py`
- Modify: `tests/test_tab_search_core.py`
- Modify: `tests/test_tab_search_runtime.py`
- Modify: `tab-search.py`

- [ ] **Step 1: Write the failing tests**

Add tests for launch command construction:

```python
def test_build_post_command_terminal_invocation():
    ...
```

and runtime behavior that uses the bash-based command path when `post_cd_command` is configured.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL because launch flow currently only uses `--working-directory`

- [ ] **Step 3: Write minimal implementation**

Add a launch helper that builds a bash command sequence which:
- enters the target directory
- runs the configured snippet
- ends in `exec bash`

Use the harvested remote terminal env for existing-window launches as before.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

### Task 4: Docs And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update docs**

Document:
- config path
- config format
- missing-config fallback behavior
- bash-only post command behavior

- [ ] **Step 2: Run verification**

Run: `python3 -m unittest discover -s tests -v && python3 -m py_compile tab-search.py tab_search_core.py`
Expected: all tests pass and compile succeeds
