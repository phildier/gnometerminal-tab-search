# Configurable Roots And Post Command Design

## Goal

Add an optional user config file at `~/.config/gnometerminal-tab-search/config.toml` that can define the directory roots used for launcher discovery and an optional global bash snippet to run after changing into a launched directory.

## Approved Decisions

- Config path: `~/.config/gnometerminal-tab-search/config.toml`
- Config format: TOML
- Config roots replace all built-in launcher roots and become the only source of truth when the config file exists
- Root precedence is list order; earlier roots win and later duplicate basenames are dropped
- The post-directory command is a single global command
- The post-directory command is explicitly bash-only
- If the config file is missing, the tool falls back to existing tab-switcher-only behavior

## Config Shape

```toml
roots = [
  "~/pmg",
  "~/projects",
]

post_cd_command = "my_shell_function"
```

## Runtime Behavior

### Missing Config

- If `config.toml` does not exist, preserve the current tab-switcher behavior only
- No directory discovery is attempted in this mode

### Present Config

- Expand `~` in each configured root
- Validate `roots` as a non-empty list of strings
- Validate `post_cd_command` as a string when present
- Scan only immediate children of each configured root
- Apply precedence in list order; keep the first basename seen and drop later duplicates
- Merge discovered directories with open tabs, omitting any directory whose basename exactly matches an open tab title

### Launching Directories

- If no `post_cd_command` is configured:
  - keep the current existing-window tab launch behavior using the harvested terminal environment
- If `post_cd_command` is configured:
  - launch via bash so functions loaded through `~/.bashrc` are available
  - start the new terminal in the target directory
  - execute the configured bash snippet
  - leave the user in an interactive bash session afterward

## Error Handling

- Missing config: fall back to tab-only mode
- Existing but malformed TOML: exit with a clear parse error and file path
- Existing config with missing or invalid `roots`: exit with a validation error
- Existing config with invalid root paths: exit with a validation error identifying the root
- Existing config with non-string `post_cd_command`: exit with a validation error

## Testing

- Missing-config fallback to tab-only mode
- TOML parsing and validation
- Ordered root precedence and duplicate dropping
- Dedupe against open tab names
- Launch command construction with and without `post_cd_command`
- Bash snippet launch path for function-friendly execution
