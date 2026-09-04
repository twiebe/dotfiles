# claude-box as a Python CLI

Replace the zsh function layer in `claude-box/.zshrc.d/90-claude-box.zsh` with a
single-file Python CLI named `cb`, and make the image's language toolchains
optional at build time.

## Why

The zsh layer has outgrown its shape. Five commands now repeat the same prologue:

```zsh
local CB_DIND="${CB_DIND:-false}" CB_FORCE="${CB_FORCE:-false}"
local -a cb_argv
_cb_gate "$@" || return
_cb_dind "${cb_argv[@]}" || return
```

`_cb_gate` and `_cb_dind` communicate by assigning into the caller's `local`
variables through zsh's dynamic scoping, and by leaving their leftovers in an
array the caller declared. That works, but it is four copies of a convention
that nothing enforces, and adding a second persisted setting would make it six.

Concrete gains beyond the cleanup:

- **Privilege reconciliation.** `cbrecreate` without `--dind` silently hands back
  an unprivileged box. Nothing compares the request against the container that
  exists. In Python this is one `docker inspect` and a prompt.
- **A real exec.** `os.execvp` replaces the shell's nested call, so the final
  `devcontainer exec` inherits the terminal directly and cb leaves the process
  tree. Signals and exit codes stop being forwarded by hand.
- **No npm on the host.** `_cb_claude_version` shells out to `npm view`. A
  `urllib` request to `registry.npmjs.org` does the same job and drops the
  requirement.
- **Tests.** The pure functions — slug, path hash, settings merge, argument
  splitting — are the ones that break silently today and are untestable in their
  current form.

## Non-goals

- Project-local `.devcontainer/` support is **removed**, not ported. It costs a
  branch in build, ensure-image, rebuild-image and update-claude, and boxes
  created that way carry a different `config_file` label, so `cb ls` and
  `cb down --all` never saw them anyway. A repo with its own `.devcontainer/` is
  `devcontainer up`'s job.
- No deprecation shims for `cbup`, `cbrecreate`, `cbupdate`, `cbrebuild`,
  `cbls`, `cbdown`, `dcls`, `dcdown`. They are dropped; `cb <subcommand>` is the
  muscle memory worth building.
- Per-project image variants. Image features are global — see below.

## Layout

```
claude-box/
  .local/bin/cb                  # the CLI: one file, stdlib only, no extension
  .config/claude-box/            # devcontainer.json, Dockerfile, cb-dockerd
  .zshrc.d/90-claude-box.zsh     # shrinks to a completion function + `cbc` alias
tests/test_cb.py                 # outside the package, see below
```

Two placement constraints, both consequences of stow:

**Mutable state cannot live under `~/.config/claude-box/`.** Stow folds a
directory it alone owns into a single symlink, so `~/.config/claude-box` points
at the repo. Writing state there writes into the dotfiles checkout. State goes
to `${XDG_STATE_HOME:-~/.local/state}/claude-box/` instead. The alternative,
remembering `stow --no-folding` forever, is one forgotten flag away from the
same bug.

**Tests cannot live inside the package either.** Stow maps every top-level
entry of a package into the target, so `claude-box/tests/` would land in
`$HOME`. A `.stow-local-ignore` would exclude it, but supplying that file
*replaces* stow's entire default ignore list rather than adding to it, which
would quietly start stowing backup files and `.gitignore` the day one appears
there. The tests go in a top-level `tests/`, alongside `docs/` — neither is a
stow package.

Target Python 3.9 — the system `python3` on macOS — and the standard library
only. `subprocess` for docker and devcontainer, `urllib` for the registry
lookup, `os.execvp` for the final exec.

The file is organized in the sections a package split would use if it outgrows
roughly 600 lines: paths, identity, settings, docker wrappers, devcontainer
wrappers, image, gate, commands, CLI.

## Commands

| Command | Replaces | Behavior |
|---|---|---|
| `cb [up] [claude args…]` | `cb` | Ensure image, ensure box, exec claude |
| `cb up --no-attach` | `cbup` | Box only |
| `cb exec CMD…` | `cbexec` | |
| `cb shell` | — | `exec zsh` |
| `cb down [--all\|--any]` | `cbdown`, `dcdown` | |
| `cb ls [--any]` | `cbls`, `dcls` | |
| `cb recreate` | `cbrecreate` | Container only; image untouched |
| `cb update-claude` | `cbupdate` | Resolve version, cached build, recreate a box that exists |
| `cb rebuild-image [--no-cache]` | `cbrebuild` | Builds only; `--no-cache` is the old nuclear option |
| `cb config [KEY [VALUE]]` | — | Show or set, with provenance |

Scope flags are consistent across `ls` and `down`: no flag means this directory,
`--all` means every cb box, `--any` means every devcontainer on the machine.
`--any` prompts before removing anything unless `-y` is given. This retires the
`cb*`/`dc*` naming split — the scope is an argument, not a second command
family.

`--dind` disappears as a flag name. Container privilege is `--docker` /
`--no-docker` on any command that creates a container, and setting it persists.

## Argument splitting

```python
SUBCOMMANDS = {"up", "down", "ls", "exec", "shell",
               "recreate", "rebuild-image", "update-claude", "config"}
CB_FLAGS    = {"--docker", "--no-docker", "--force", "-y", "--dry-run"}
```

If `argv[0]` names a subcommand, cb parses the rest itself. Otherwise the
subcommand is implicitly `up`, and everything remaining after cb's own flags are
stripped is forwarded to claude. cb's flags are recognized wherever they appear
on the line, matching what `_cb_gate` does with `--force` today. `--` ends cb's
parsing and forwards the remainder verbatim.

The reserved set was checked against claude's flags; there is no overlap today.
`cb --help` prints cb's help, `cb -- --help` reaches claude's. Claude's exit
code becomes cb's.

## Settings

Per-directory, in `${XDG_STATE_HOME:-~/.local/state}/claude-box/projects/<slug>-<hash>.json`,
keyed by the same slug and path hash the container name uses:

```json
{"version": 1, "path": "/Users/…/git/repo", "docker": true, "force": false}
```

Resolution is CLI flag, then file, then default (`docker: false`, `force:
false`). A flag also writes the file, so `cb --docker` once is permanent, and
`--force` approves an out-of-roots directory once rather than on every
invocation. `path` is stored so `cb config --prune` can drop entries whose
directory is gone.

`cb config` with no arguments prints each key with where its value came from.

This is the source of truth that feeds `CB_DIND` into `devcontainer.json`; the
container plumbing is unchanged.

## Reconciliation

`cb up` against an existing container compares the resolved `docker` setting
with the container's actual `HostConfig.Privileged`. On a mismatch it prints
both values and prompts to recreate; `-y` skips the prompt, declining runs the
box as it is.

This is the failure the current `--dind` flag cannot prevent, because
`--privileged` applies only at creation time and nothing checks afterwards.

## Directory gate

Unchanged in substance: `~/git` and `~/tmp`, compared as resolved paths so a
symlinked root still matches. The roots stay a constant in the script, with an
environment override for tests. `--force` now persists, so an approved directory
stays approved.

## Image features

The toolchains are optional at build time: `rust`, `sqlx` (implies `rust`), `go`,
`docker`, `playwright`. All default to on, so a bare `docker build` in
`.config/claude-box` still produces the full image — the rule the Dockerfile
header already sets, because the image is built directly to give it one fixed
name instead of the per-workspace name the devcontainer CLI would choose.

Features are **global**, a property of the image rather than of a box. The tag
stays `claude-box:latest` and `devcontainer.json` is untouched. Per-project
variants were considered and rejected: each combination is a multi-GB build on
first use in a directory, and the images accumulate silently.

Two mechanisms, because one does not cover both cases.

**apt, cargo and npx features use `ARG` plus a shell guard.** The layer always
exists and does nothing when off:

```dockerfile
ARG WITH_RUST=1
RUN if [ "$WITH_RUST" = 1 ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends rustup clang cbindgen \
      && rm -rf /var/lib/apt/lists/*; \
    fi
```

**Go uses a stage alias, because `COPY --from=go` cannot be guarded.** A shell
`if` would have to copy the 250 MB in and delete it afterwards, which leaves it
in the layer:

```dockerfile
ARG WITH_GO=1
FROM golang:${GO_VERSION}-trixie AS go-1
FROM node:26-trixie-slim AS go-0
RUN mkdir -p /usr/local/go
FROM go-${WITH_GO} AS go
```

`WITH_GO` must be declared before the first `FROM`, for the reason the existing
comment gives for `GO_VERSION`: the global ARG scope ends there.

Three adjustments while in the file:

- `just` moves out of the rust block into the base apt list. It is a general
  task runner that merely ships next to rust in the current grouping; losing it
  with `--without-rust` would be a surprise.
- `sqlx-cli` becomes its own toggle implying `rust`. It is a several-minute
  from-source build, and wanting rust without it is the common case.
- `cb-dockerd` and `groupadd docker` stay unconditional even with `docker` off:
  2 KB and a group, and `cb-dockerd` already exits 0 when `CB_DIND` is not true.

Layer order is unaffected. The toggled layers keep their current
expensive-first arrangement and claude-code stays last, which is what lets
`cb update-claude` pick up a release without `--no-cache`.

### Where the answer lives

The image carries the truth as a label:

```dockerfile
LABEL cb.features="rust=${WITH_RUST},sqlx=${WITH_SQLX},go=${WITH_GO},docker=${WITH_DOCKER},playwright=${WITH_PLAYWRIGHT}"
```

`docker inspect` then answers what the image actually has, even if the state
file is lost or hand-edited. `~/.local/state/claude-box/image.json` holds only
the remembered set for the next build: `cb rebuild-image` with no feature flags
reuses it, `--with-X` and `--without-X` mutate and persist it, and
`cb update-claude` never changes it.

This makes the two-level docker check exact. Container privilege and the
presence of the docker binaries are separate things, so a box whose settings say
`docker: true` running on an image labeled `docker=0` gets a daemon that cannot
start. `cb up` catches that and names `cb rebuild-image --with-docker` as the
fix, instead of letting it fail in `cb-dockerd`'s log.

`cb config` prints the image's feature set alongside the box settings.

Neither `cb rebuild-image` nor `cb update-claude` creates a box. The image is
shared, so recreating whichever box happens to sit in the current directory
would be an arbitrary half-measure, and in a directory without one it would
make a container as a side effect of a build. `rebuild-image` therefore builds
and stops; `update-claude` recreates only a box that already exists, because
running the new binary is its point. Both say what they left alone.

## Error handling

A missing `docker` or `devcontainer` binary exits 127 with one line naming it.
A stopped daemon is caught on the first inspect and reported as such rather than
as a failed subprocess. Build and exec failures propagate their exit codes
unwrapped.

## Testing

`python3 -m unittest discover tests`, standard library only. Covers the pure
functions:

- slug edge cases: `.dotfiles` → `dotfiles`, all-punctuation → `box`, runs of
  dashes collapsed, edges trimmed, lowercased
- path hash stability and its independence from the slug
- settings merge and provenance, including flag-over-file-over-default
- argument splitting: subcommand detection, cb flags recognized at any position,
  `--` terminating cb's parsing
- the workspace path: `$PWD` preferred over `os.getcwd()` so a checkout reached
  through a symlink keeps one identity, with a fallback when `$PWD` is stale,
  relative, or gone

Code that shells out to docker is not unit tested.

## Migration

The slug and path-hash algorithms are unchanged, so existing containers keep
their names and labels and `cb ls` and `cb down` find boxes the zsh version
created. That holds only if cb hashes the path the same way the shell spelled
it: `os.getcwd()` resolves symlinks and zsh's `$PWD` does not, so cb reads
`$PWD` and falls back to `os.getcwd()` when it no longer names this directory.
`devcontainer.json` needs no edit: `CB_DIND` still arrives through the
environment, cb merely sources it from the settings file instead of a flag.

Boxes created from a project-local `.devcontainer/` become invisible to cb, as
they effectively already were.
