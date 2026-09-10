"""Unit tests for the pure half of cb.

Everything that shells out to docker is out of scope; what is covered here is
the logic that decides *what* docker gets called with, which is the part that
used to fail silently in the zsh version.

cb has no .py extension — it is an executable on PATH — so it is loaded by path
rather than imported by name.

These live outside claude-box/ deliberately. Every top-level entry of a stow
package is mapped into the target, so claude-box/tests/ would land in $HOME; the
alternative, a .stow-local-ignore, replaces stow's entire default ignore list
rather than adding to it, which would quietly start stowing backup files and
.gitignore the day one appears in that directory.
"""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

CB_PATH = Path(__file__).resolve().parents[1] / "claude-box" / ".local" / "bin" / "cb"


def _load_cb():
    spec = importlib.util.spec_from_loader(
        "cb", importlib.machinery.SourceFileLoader("cb", str(CB_PATH))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cb = _load_cb()


class SlugTest(unittest.TestCase):
    """The slug names the container and the workspace path inside the box, so it
    has to survive being used as a hostname: [a-z0-9-] only, and neither leading
    nor trailing dashes."""

    def test_passes_through_a_plain_name(self):
        self.assertEqual(cb.slug("myrepo"), "myrepo")

    def test_lowercases(self):
        self.assertEqual(cb.slug("MyRepo"), "myrepo")

    def test_keeps_inner_dashes(self):
        self.assertEqual(cb.slug("claude-box"), "claude-box")

    def test_replaces_disallowed_characters_with_dashes(self):
        self.assertEqual(cb.slug("my_repo.git"), "my-repo-git")

    def test_collapses_runs_of_dashes(self):
        self.assertEqual(cb.slug("my___repo"), "my-repo")

    def test_trims_leading_dashes(self):
        # ~/.dotfiles must not become "-dotfiles": that is an invalid hostname
        # and reads badly as /workspaces/-dotfiles.
        self.assertEqual(cb.slug(".dotfiles"), "dotfiles")

    def test_trims_trailing_dashes(self):
        self.assertEqual(cb.slug("repo."), "repo")

    def test_falls_back_when_nothing_survives(self):
        self.assertEqual(cb.slug("..."), "box")

    def test_falls_back_on_an_empty_name(self):
        self.assertEqual(cb.slug(""), "box")


class PathHashTest(unittest.TestCase):
    """The hash tells two checkouts with the same directory name apart."""

    def test_is_eight_hex_characters(self):
        digest = cb.path_hash("/home/user/git/repo")
        self.assertEqual(len(digest), 8)
        self.assertRegex(digest, r"\A[0-9a-f]{8}\Z")

    def test_is_stable(self):
        self.assertEqual(
            cb.path_hash("/home/user/git/repo"),
            cb.path_hash("/home/user/git/repo"),
        )

    def test_differs_between_paths_with_the_same_basename(self):
        self.assertNotEqual(
            cb.path_hash("/home/user/git/repo"),
            cb.path_hash("/home/user/tmp/repo"),
        )

    def test_matches_the_zsh_implementation(self):
        # The zsh version took the first 8 characters of `shasum -a 256` over
        # $PWD. Existing containers are named with it, so cb has to agree or it
        # would start a second box for a directory that already has one.
        self.assertEqual(cb.path_hash("/home/node/git/dotfiles"), "50184199")


class ContainerNameTest(unittest.TestCase):
    def test_joins_the_prefix_slug_and_hash(self):
        name = cb.container_name("/home/user/git/My_Repo")
        self.assertEqual(name, "cb-my-repo-" + cb.path_hash("/home/user/git/My_Repo"))


class WorkspaceTest(unittest.TestCase):
    """The workspace path is what the container name is hashed from, so it has
    to be spelled the way the shell spells it: os.getcwd() resolves symlinks and
    $PWD does not, and a checkout reached through a symlink would otherwise get
    a second identity and a second box."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.real = base / "real"
        self.real.mkdir()
        self.link = base / "link"
        self.link.symlink_to(self.real)

        self.addCleanup(os.chdir, os.getcwd())
        self.addCleanup(os.environ.pop, "PWD", None)
        os.chdir(str(self.real))

    def test_prefers_the_shells_spelling(self):
        os.environ["PWD"] = str(self.link)
        self.assertEqual(cb.current_workspace(), str(self.link))

    def test_falls_back_when_pwd_is_stale(self):
        # A subshell that chdir'd without updating PWD, or an exported PWD from
        # somewhere else entirely.
        os.environ["PWD"] = str(self.real.parent)
        self.assertEqual(cb.current_workspace(), str(self.real))

    def test_falls_back_when_pwd_names_nothing(self):
        os.environ["PWD"] = str(self.real / "gone")
        self.assertEqual(cb.current_workspace(), str(self.real))

    def test_falls_back_when_pwd_is_unset(self):
        os.environ.pop("PWD", None)
        self.assertEqual(cb.current_workspace(), str(self.real))

    def test_falls_back_when_pwd_is_relative(self):
        os.environ["PWD"] = "."
        self.assertEqual(cb.current_workspace(), str(self.real))


class ResolveSettingsTest(unittest.TestCase):
    """Flag beats file beats default, and every answer carries where it came
    from so `cb config` can show it."""

    def test_falls_back_to_defaults(self):
        resolved = cb.resolve_settings(stored={}, overrides={})
        self.assertEqual(resolved["docker"], (False, "default"))
        self.assertEqual(resolved["force"], (False, "default"))

    def test_stored_value_wins_over_the_default(self):
        resolved = cb.resolve_settings(stored={"docker": True}, overrides={})
        self.assertEqual(resolved["docker"], (True, "file"))

    def test_flag_wins_over_the_stored_value(self):
        resolved = cb.resolve_settings(stored={"docker": True}, overrides={"docker": False})
        self.assertEqual(resolved["docker"], (False, "flag"))

    def test_an_unset_flag_does_not_override(self):
        # --docker and --no-docker share one destination; absent means None,
        # which must not read as False.
        resolved = cb.resolve_settings(stored={"docker": True}, overrides={"docker": None})
        self.assertEqual(resolved["docker"], (True, "file"))

    def test_ignores_unknown_keys_in_the_file(self):
        resolved = cb.resolve_settings(stored={"dind": True}, overrides={})
        self.assertNotIn("dind", resolved)


class SettingsRoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(cb.load_settings(self.store / "absent.json"), {})

    def test_unreadable_json_reads_as_empty(self):
        # A hand-edited file with a stray comma must not stop a box from
        # starting; the defaults are safe ones.
        path = self.store / "broken.json"
        path.write_text("{not json")
        self.assertEqual(cb.load_settings(path), {})

    def test_saved_settings_are_read_back(self):
        path = self.store / "box.json"
        cb.save_settings(path, {"docker": True}, workspace="/home/user/git/repo")
        self.assertEqual(cb.load_settings(path)["docker"], True)

    def test_save_records_the_workspace_for_pruning(self):
        path = self.store / "box.json"
        cb.save_settings(path, {}, workspace="/home/user/git/repo")
        self.assertEqual(cb.load_settings(path)["path"], "/home/user/git/repo")

    def test_save_merges_into_what_is_already_there(self):
        path = self.store / "box.json"
        cb.save_settings(path, {"docker": True}, workspace="/w")
        cb.save_settings(path, {"force": True}, workspace="/w")
        stored = cb.load_settings(path)
        self.assertEqual((stored["docker"], stored["force"]), (True, True))

    def test_save_ignores_unset_overrides(self):
        path = self.store / "box.json"
        cb.save_settings(path, {"docker": True}, workspace="/w")
        cb.save_settings(path, {"docker": None}, workspace="/w")
        self.assertEqual(cb.load_settings(path)["docker"], True)


class DryRunTest(unittest.TestCase):
    """--dry-run prints what would happen. A run that still remembers --docker
    has changed something, which is exactly what it promised not to do."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        cb.DRY_RUN = True
        self.addCleanup(setattr, cb, "DRY_RUN", False)

    def test_settings_are_not_written(self):
        path = self.store / "box.json"
        with contextlib.redirect_stdout(io.StringIO()):
            cb.save_settings(path, {"docker": True}, workspace="/w")
        self.assertFalse(path.exists())


class PickSubcommandTest(unittest.TestCase):
    """`cb` forwards its line to claude, so the first token decides whether the
    line belongs to cb at all."""

    def test_no_arguments_means_up(self):
        self.assertEqual(cb.pick_subcommand([]), ("up", []))

    def test_a_leading_subcommand_is_taken(self):
        self.assertEqual(cb.pick_subcommand(["down", "--all"]), ("down", ["--all"]))

    def test_anything_else_is_up_with_claude_arguments(self):
        self.assertEqual(cb.pick_subcommand(["-c"]), ("up", ["-c"]))

    def test_a_subcommand_name_later_on_the_line_belongs_to_claude(self):
        # `cb -p down` asks claude about something called down; it is not
        # cb's teardown command.
        self.assertEqual(cb.pick_subcommand(["-p", "down"]), ("up", ["-p", "down"]))


class ExtractFlagsTest(unittest.TestCase):
    """cb owns a small reserved set and forwards everything else. The reserved
    flags are recognised wherever they appear, because the rest of the line
    belongs to claude and cannot be reordered around them."""

    def test_leaves_claude_arguments_alone(self):
        flags, rest = cb.extract_flags(["-c", "--model", "opus"])
        self.assertEqual(rest, ["-c", "--model", "opus"])

    def test_unset_toggles_are_none_not_false(self):
        # None means "not given" and leaves the stored setting alone; False
        # means --no-docker and overrides it.
        flags, _ = cb.extract_flags([])
        self.assertIsNone(flags["docker"])

    def test_docker_sets_the_toggle(self):
        flags, rest = cb.extract_flags(["--docker"])
        self.assertEqual((flags["docker"], rest), (True, []))

    def test_no_docker_clears_the_toggle(self):
        flags, _ = cb.extract_flags(["--no-docker"])
        self.assertIs(flags["docker"], False)

    def test_a_reserved_flag_is_taken_from_the_middle_of_the_line(self):
        flags, rest = cb.extract_flags(["-p", "--docker", "hello"])
        self.assertEqual((flags["docker"], rest), (True, ["-p", "hello"]))

    def test_force_sets_the_toggle(self):
        flags, _ = cb.extract_flags(["--force"])
        self.assertIs(flags["force"], True)

    def test_yes_defaults_to_false(self):
        flags, _ = cb.extract_flags([])
        self.assertIs(flags["yes"], False)

    def test_yes_is_recognised(self):
        flags, rest = cb.extract_flags(["-y"])
        self.assertEqual((flags["yes"], rest), (True, []))

    def test_double_dash_ends_cb_parsing(self):
        # The escape hatch for reaching claude's own --help, and for any flag
        # cb might later want to reserve.
        flags, rest = cb.extract_flags(["--", "--docker", "--help"])
        self.assertEqual(rest, ["--docker", "--help"])
        self.assertIsNone(flags["docker"])

    def test_double_dash_does_not_undo_earlier_flags(self):
        flags, rest = cb.extract_flags(["--docker", "--", "-c"])
        self.assertEqual((flags["docker"], rest), (True, ["-c"]))

    def test_no_attach_defaults_to_false(self):
        flags, _ = cb.extract_flags([])
        self.assertIs(flags["no_attach"], False)

    def test_no_attach_is_recognised(self):
        # `cb up --no-attach` brings the box up without running claude in it.
        flags, rest = cb.extract_flags(["up", "--no-attach"])
        self.assertEqual((flags["no_attach"], rest), (True, ["up"]))

    def test_help_is_cbs_own(self):
        flags, _ = cb.extract_flags(["--help"])
        self.assertIs(flags["help"], True)


class FeatureFlagsTest(unittest.TestCase):
    def test_unmentioned_features_are_none(self):
        overrides, _ = cb.extract_feature_flags([])
        self.assertIsNone(overrides["rust"])

    def test_with_enables(self):
        overrides, rest = cb.extract_feature_flags(["--with-go"])
        self.assertEqual((overrides["go"], rest), (True, []))

    def test_without_disables(self):
        overrides, _ = cb.extract_feature_flags(["--without-playwright"])
        self.assertIs(overrides["playwright"], False)

    def test_leaves_other_arguments_alone(self):
        _, rest = cb.extract_feature_flags(["--no-cache", "--without-go"])
        self.assertEqual(rest, ["--no-cache"])


class ResolveFeaturesTest(unittest.TestCase):
    """Features are a property of the one shared image. Everything is on by
    default, so a bare `docker build` in .config/claude-box still produces the
    intended image — the rule the Dockerfile header sets."""

    def test_everything_defaults_to_on(self):
        features = cb.resolve_features(stored={}, overrides={})
        self.assertEqual(set(features), set(cb.IMAGE_FEATURES))
        self.assertTrue(all(features.values()))

    def test_stored_answer_is_remembered(self):
        features = cb.resolve_features(stored={"go": False}, overrides={})
        self.assertIs(features["go"], False)

    def test_flag_beats_the_stored_answer(self):
        features = cb.resolve_features(stored={"go": False}, overrides={"go": True})
        self.assertIs(features["go"], True)

    def test_dropping_rust_drops_sqlx_with_it(self):
        # sqlx-cli is a cargo build; without a toolchain there is nothing to
        # build it with.
        features = cb.resolve_features(stored={}, overrides={"rust": False})
        self.assertIs(features["sqlx"], False)

    def test_sqlx_can_be_dropped_on_its_own(self):
        features = cb.resolve_features(stored={}, overrides={"sqlx": False})
        self.assertEqual((features["sqlx"], features["rust"]), (False, True))

    def test_asking_for_sqlx_without_rust_is_refused(self):
        # Silently re-enabling rust would hand back an image the flags said not
        # to build.
        with self.assertRaises(cb.UsageError):
            cb.resolve_features(stored={}, overrides={"rust": False, "sqlx": True})


class FeatureLabelTest(unittest.TestCase):
    """The image carries its own feature set, so `docker inspect` answers what
    an image has even when the state file is gone."""

    def test_round_trips(self):
        features = cb.resolve_features(stored={"go": False}, overrides={})
        self.assertEqual(cb.parse_feature_label(cb.feature_label(features)), features)

    def test_reads_the_written_form(self):
        parsed = cb.parse_feature_label("rust=1,go=0")
        self.assertEqual(parsed, {"rust": True, "go": False})

    def test_a_missing_label_is_empty(self):
        self.assertEqual(cb.parse_feature_label(""), {})
        self.assertEqual(cb.parse_feature_label(None), {})

    def test_ignores_unknown_and_malformed_entries(self):
        parsed = cb.parse_feature_label("rust=1,nonsense,zig=1")
        self.assertEqual(parsed, {"rust": True})


class FeatureBuildArgsTest(unittest.TestCase):
    def test_renders_one_arg_per_feature(self):
        args = cb.feature_build_args({"rust": True, "go": False})
        self.assertEqual(args, ["WITH_GO=0", "WITH_RUST=1"])


class ParseVersionTest(unittest.TestCase):
    """Each toolchain announces its newest release in a shape of its own. The
    fetch is out of scope; what is covered is reading the answer, and surviving
    one that does not arrive or does not look the way it should."""

    def test_reads_uv_from_pypi(self):
        self.assertEqual(cb.parse_uv_version({"info": {"version": "0.12.1"}}), "0.12.1")

    def test_reads_go_from_the_download_index(self):
        payload = [
            {"version": "go1.26.5", "stable": True},
            {"version": "go1.25.9", "stable": True},
        ]
        # The tag is golang:<version>-trixie, so the "go" prefix has to come off.
        self.assertEqual(cb.parse_go_version(payload), "1.26.5")

    def test_skips_an_unstable_go_release(self):
        payload = [
            {"version": "go1.27rc1", "stable": False},
            {"version": "go1.26.5", "stable": True},
        ]
        self.assertEqual(cb.parse_go_version(payload), "1.26.5")

    def test_reads_tofu_from_its_latest_release(self):
        # The tag is <version>-minimal, so the "v" has to come off.
        self.assertEqual(cb.parse_tofu_version({"tag_name": "v1.12.6"}), "1.12.6")

    def test_nothing_arrived(self):
        for parse in (cb.parse_uv_version, cb.parse_go_version, cb.parse_tofu_version):
            self.assertIsNone(parse(None))

    def test_something_unexpected_arrived(self):
        # A lookup that answers HTML, an error document, or a renamed field must
        # leave the pinned default in the Dockerfile standing.
        for parse, junk in (
            (cb.parse_uv_version, {"message": "Not Found"}),
            (cb.parse_go_version, []),
            (cb.parse_go_version, [{"stable": False}]),
            (cb.parse_tofu_version, {"tag_name": ""}),
        ):
            self.assertIsNone(parse(junk))


class BuildEnvTest(unittest.TestCase):
    """The Dockerfile cannot be built by the classic builder, and the failure it
    gets there lands at a COPY near the end — after the Rust toolchain, the
    sqlx-cli build and the Playwright layer."""

    def test_asks_for_buildkit(self):
        self.assertEqual(cb.build_env()["DOCKER_BUILDKIT"], "1")

    def test_overrides_an_explicit_refusal(self):
        # A DOCKER_BUILDKIT=0 exported for some other project would otherwise
        # buy a twenty-minute build that was never going to work.
        self.addCleanup(os.environ.pop, "DOCKER_BUILDKIT", None)
        os.environ["DOCKER_BUILDKIT"] = "0"
        self.assertEqual(cb.build_env()["DOCKER_BUILDKIT"], "1")

    def test_keeps_the_rest_of_the_environment(self):
        # docker needs PATH, HOME and DOCKER_HOST like any other command.
        self.addCleanup(os.environ.pop, "CB_TEST_MARKER", None)
        os.environ["CB_TEST_MARKER"] = "kept"
        self.assertEqual(cb.build_env()["CB_TEST_MARKER"], "kept")


class VersionLabelTest(unittest.TestCase):
    """The image records what it was built with, so `cb config` can answer "what
    uv is in the box" without running it — and still answer after the state file
    is gone."""

    def test_reads_the_written_form(self):
        parsed = cb.parse_version_label("claude=2.1.267,go=1.27.1,uv=0.12.12")
        self.assertEqual(parsed, {"claude": "2.1.267", "go": "1.27.1", "uv": "0.12.12"})

    def test_a_missing_label_is_empty(self):
        self.assertEqual(cb.parse_version_label(""), {})
        self.assertEqual(cb.parse_version_label(None), {})

    def test_ignores_unknown_and_empty_entries(self):
        # An image predating a toolchain leaves its ARG expanding to nothing.
        parsed = cb.parse_version_label("go=1.27.1,zig=0.14.0,tofu=,nonsense")
        self.assertEqual(parsed, {"go": "1.27.1"})


class VersionBuildArgsTest(unittest.TestCase):
    def test_renders_the_arg_each_toolchain_is_pinned_by(self):
        args = cb.version_build_args({"go": "1.26.5", "uv": "0.12.1"})
        self.assertEqual(args, ["GO_VERSION=1.26.5", "UV_VERSION=0.12.1"])

    def test_ignores_a_toolchain_it_knows_nothing_about(self):
        self.assertEqual(cb.version_build_args({"zig": "0.14.0"}), [])

    def test_renders_nothing_when_nothing_was_resolved(self):
        # No --build-arg means the Dockerfile's own pin applies.
        self.assertEqual(cb.version_build_args({}), [])


class StoredVersionsTest(unittest.TestCase):
    """What the last build settled on. Read back so `cb update-claude` rebuilds
    against the same toolchains and stays a one-layer update."""

    def test_reads_what_was_remembered(self):
        self.assertEqual(
            cb.stored_versions({"versions": {"go": "1.26.5"}}), {"go": "1.26.5"}
        )

    def test_a_file_without_versions_reads_as_empty(self):
        self.assertEqual(cb.stored_versions({"rust": True}), {})

    def test_a_hand_mangled_versions_key_reads_as_empty(self):
        self.assertEqual(cb.stored_versions({"versions": "1.26.5"}), {})

    def test_drops_an_unknown_toolchain(self):
        self.assertEqual(cb.stored_versions({"versions": {"zig": "0.14.0"}}), {})

    def test_drops_an_empty_value(self):
        self.assertEqual(cb.stored_versions({"versions": {"go": None}}), {})


class RefreshVersionsTest(unittest.TestCase):
    """A lookup that fails must not throw away the version the image already
    has — that would silently roll a toolchain back to the Dockerfile's pin."""

    def setUp(self):
        self.addCleanup(setattr, cb, "latest_versions", cb.latest_versions)

    def test_takes_what_upstream_answers(self):
        cb.latest_versions = lambda: {"go": "1.27.0"}
        self.assertEqual(cb.refresh_versions({"versions": {"go": "1.26.5"}})["go"], "1.27.0")

    def test_keeps_what_was_remembered_when_a_lookup_fails(self):
        cb.latest_versions = lambda: {}
        self.assertEqual(cb.refresh_versions({"versions": {"go": "1.26.5"}})["go"], "1.26.5")

    def test_keeps_the_others_when_only_one_lookup_answers(self):
        cb.latest_versions = lambda: {"uv": "0.13.0"}
        refreshed = cb.refresh_versions({"versions": {"go": "1.26.5", "uv": "0.12.1"}})
        self.assertEqual(refreshed, {"go": "1.26.5", "uv": "0.13.0"})


class UpdateClaudeTest(unittest.TestCase):
    """`cb update-claude` exists to redo one npm install. Resolving toolchains
    there would bump Go or uv behind the user's back and invalidate every layer
    below it — the opposite of what the command is for."""

    def setUp(self):
        self.built = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        state = Path(self.tmp.name) / "image.json"
        state.write_text('{"rust": true, "versions": {"go": "1.26.5"}}')

        def forbidden():
            raise AssertionError("update-claude must not ask upstream for versions")

        for name, value in (
            ("image_state_path", lambda: str(state)),
            ("latest_versions", forbidden),
            ("build_image", lambda features, versions, no_cache=False: self.built.append(versions)),
            ("box_for", lambda workspace: None),
            ("current_workspace", lambda: "/home/u/git/repo"),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def test_builds_against_the_versions_the_image_already_has(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cb.cmd_update_claude({"yes": False}, [])
        self.assertEqual(self.built, [{"go": "1.26.5"}])


class InRootsTest(unittest.TestCase):
    """A box bind-mounts the directory it starts in and hands it to an agent
    with permissions loosened, so the gate is what stops a stray cd from
    exposing $HOME."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "git"
        self.root.mkdir()

    def test_the_root_itself_is_allowed(self):
        self.assertTrue(cb.in_roots(str(self.root), [str(self.root)]))

    def test_a_directory_below_the_root_is_allowed(self):
        repo = self.root / "repo"
        repo.mkdir()
        self.assertTrue(cb.in_roots(str(repo), [str(self.root)]))

    def test_a_directory_outside_is_refused(self):
        other = self.base / "elsewhere"
        other.mkdir()
        self.assertFalse(cb.in_roots(str(other), [str(self.root)]))

    def test_a_sibling_sharing_the_prefix_is_refused(self):
        # A plain startswith would let ~/gitignored through as if it were
        # inside ~/git.
        sibling = self.base / "gitignored"
        sibling.mkdir()
        self.assertFalse(cb.in_roots(str(sibling), [str(self.root)]))

    def test_a_symlinked_root_still_counts(self):
        # cd through a symlinked ~/git and $PWD no longer names the root.
        link = self.base / "linked"
        link.symlink_to(self.root)
        self.assertTrue(cb.in_roots(str(link / "."), [str(self.root)]))

    def test_a_root_that_does_not_exist_never_matches(self):
        self.assertFalse(cb.in_roots(str(self.root), [str(self.base / "absent")]))

    def test_any_matching_root_is_enough(self):
        roots = [str(self.base / "absent"), str(self.root)]
        self.assertTrue(cb.in_roots(str(self.root), roots))


def flag_values(argv, flag):
    """Every value that follows `flag` in `argv`.

    `--label` and `--mount` appear several times in one command line, so asking
    for "the" value would hide exactly the case worth asserting on.
    """
    return [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == flag]


class WorkspaceFolderTest(unittest.TestCase):
    """The checkout is mounted at a path unique per repo: everything Claude
    keys by project — transcripts, memory, permissions, prompt history — is
    keyed by this path, so a fixed /workspace would make every box one
    project."""

    def test_is_the_slug_under_workspaces(self):
        self.assertEqual(cb.workspace_folder("/home/u/git/My_Repo"), "/workspaces/my-repo")

    def test_carries_no_hash(self):
        # It shows up in the prompt and in every path Claude prints, so it stays
        # readable; two repos with the same directory name share one identity.
        self.assertEqual(cb.workspace_folder("/home/u/tmp/repo"), "/workspaces/repo")


class HistoryVolumeTest(unittest.TestCase):
    def test_is_named_after_the_path_hash(self):
        self.assertEqual(cb.history_volume("/w"), "cb-history-" + cb.path_hash("/w"))

    def test_differs_between_checkouts_with_the_same_name(self):
        self.assertNotEqual(
            cb.history_volume("/home/u/git/repo"), cb.history_volume("/home/u/tmp/repo")
        )


class ContainerEnvTest(unittest.TestCase):
    """Baked in at creation time, so a later bare `cb` brings the box back up
    the way it was made."""

    def setUp(self):
        for name in cb.PASSTHROUGH_ENV:
            self.addCleanup(os.environ.pop, name, None)
            os.environ.pop(name, None)

    def test_spells_dind_the_way_the_shell_script_reads_it(self):
        # cb-dockerd tests `[ "$CB_DIND" = true ]`.
        self.assertEqual(cb.container_env(docker=True)["CB_DIND"], "true")

    def test_says_false_without_docker(self):
        self.assertEqual(cb.container_env(docker=False)["CB_DIND"], "false")

    def test_points_claude_at_the_shared_config(self):
        self.assertEqual(
            cb.container_env(docker=False)["CLAUDE_CONFIG_DIR"], cb.BOX_CLAUDE_DIR
        )

    def test_passes_the_hosts_terminal_through(self):
        os.environ["TERM_PROGRAM"] = "ghostty"
        self.assertEqual(cb.container_env(docker=False)["TERM_PROGRAM"], "ghostty")

    def test_omits_a_host_variable_that_is_not_set(self):
        # ${localEnv:} used to hand over an empty value, which reads as "set to
        # nothing" rather than "unset" to anything probing it.
        self.assertNotIn("TERM_PROGRAM", cb.container_env(docker=False))


class CreateArgvTest(unittest.TestCase):
    """What devcontainer.json used to say, now said in docker's own flags."""

    def setUp(self):
        self.workspace = "/home/u/git/repo"
        self.argv = cb.create_argv(self.workspace, docker=False)

    def test_runs_detached(self):
        self.assertEqual(self.argv[:3], ["docker", "run", "--detach"])

    def test_names_the_container_after_the_box(self):
        name = cb.container_name(self.workspace)
        self.assertEqual(flag_values(self.argv, "--name"), [name])

    def test_gives_the_box_its_name_as_a_hostname(self):
        # Otherwise the prompt inside the box shows a random hex id.
        self.assertEqual(
            flag_values(self.argv, "--hostname"), [cb.container_name(self.workspace)]
        )

    def test_marks_the_container_as_a_box(self):
        self.assertIn(cb.BOX_LABEL + "=1", flag_values(self.argv, "--label"))

    def test_labels_the_folder_it_was_started_from(self):
        # This is how every later cb invocation finds the box again.
        self.assertIn(
            "{}={}".format(cb.FOLDER_LABEL, self.workspace),
            flag_values(self.argv, "--label"),
        )

    def test_mounts_the_checkout_at_the_workspace_folder(self):
        self.assertIn(
            "type=bind,source={},target={}".format(
                self.workspace, cb.workspace_folder(self.workspace)
            ),
            flag_values(self.argv, "--mount"),
        )

    def test_mounts_the_hosts_claude_directory(self):
        self.assertIn(
            "type=bind,source={},target={}".format(cb.HOST_CLAUDE_DIR, cb.BOX_CLAUDE_DIR),
            flag_values(self.argv, "--mount"),
        )

    def test_mounts_the_shell_history_as_a_volume(self):
        self.assertIn(
            "type=volume,source={},target=/commandhistory".format(
                cb.history_volume(self.workspace)
            ),
            flag_values(self.argv, "--mount"),
        )

    def test_starts_in_the_workspace_folder(self):
        self.assertEqual(
            flag_values(self.argv, "--workdir"), [cb.workspace_folder(self.workspace)]
        )

    def test_renders_the_environment(self):
        self.assertIn("CB_DIND=false", flag_values(self.argv, "--env"))

    def test_stays_unprivileged_without_docker(self):
        self.assertNotIn("--privileged", self.argv)

    def test_is_privileged_with_docker(self):
        # dockerd inside the box cannot mount, write cgroups or program iptables
        # without it.
        self.assertIn("--privileged", cb.create_argv(self.workspace, docker=True))

    def test_refuses_a_path_docker_cannot_be_told_about(self):
        # docker reads a --mount value as CSV, so a comma in the path would split
        # the field and fail with something unrelated to the cause.
        with self.assertRaises(cb.UsageError):
            cb.create_argv("/home/u/git/a,b", docker=False)

    def test_ends_with_the_image_and_an_idle_command(self):
        # Nothing in the image stays in the foreground, so the container needs a
        # process that does; claude then arrives by `docker exec`.
        self.assertEqual(self.argv[-3:], [cb.CB_IMAGE, "sleep", "infinity"])


class ExecArgvTest(unittest.TestCase):
    def test_runs_the_command_in_the_named_box(self):
        argv = cb.exec_argv("cb-repo-1234abcd", ["claude", "-c"], tty=False)
        self.assertEqual(argv[-3:], ["cb-repo-1234abcd", "claude", "-c"])

    def test_allocates_a_tty_when_there_is_one(self):
        argv = cb.exec_argv("cb-box", ["zsh"], tty=True)
        self.assertIn("--tty", argv)

    def test_asks_for_no_tty_when_there_is_none(self):
        # `docker exec -t` fails outright with "the input device is not a TTY",
        # which is the normal case for a hook or a script.
        argv = cb.exec_argv("cb-box", ["zsh"], tty=False)
        self.assertNotIn("--tty", argv)
        self.assertIn("--interactive", argv)

    def test_can_drop_stdin_entirely(self):
        argv = cb.exec_argv("cb-box", ["true"], tty=False, interactive=False)
        self.assertNotIn("--interactive", argv)

    def test_runs_as_the_user_it_is_given(self):
        argv = cb.exec_argv("cb-box", ["true"], tty=False, user="root")
        self.assertEqual(flag_values(argv, "--user"), ["root"])

    def test_leaves_the_user_to_the_image_by_default(self):
        self.assertEqual(flag_values(cb.exec_argv("cb-box", ["true"], tty=False), "--user"), [])

    def test_forwards_the_terminal_type(self):
        # docker exec otherwise hands the command a bare TERM=xterm, which costs
        # tmux and vim inside the box their colours.
        self.addCleanup(os.environ.pop, "TERM", None)
        os.environ["TERM"] = "xterm-ghostty"
        argv = cb.exec_argv("cb-box", ["zsh"], tty=True)
        self.assertIn("TERM=xterm-ghostty", flag_values(argv, "--env"))

    def test_omits_the_terminal_type_when_unset(self):
        self.addCleanup(os.environ.pop, "TERM", None)
        os.environ.pop("TERM", None)
        argv = cb.exec_argv("cb-box", ["zsh"], tty=True)
        self.assertEqual(flag_values(argv, "--env"), [])

    def test_omits_the_terminal_type_without_a_tty(self):
        # Nothing that is not drawing on a terminal has an opinion about TERM.
        self.addCleanup(os.environ.pop, "TERM", None)
        os.environ["TERM"] = "xterm-ghostty"
        argv = cb.exec_argv("cb-box", ["true"], tty=False)
        self.assertEqual(flag_values(argv, "--env"), [])


class PostStartArgvTest(unittest.TestCase):
    """What devcontainer.json's postStartCommand did, on every start."""

    def test_runs_cb_dockerd_as_root(self):
        argv = cb.post_start_argv("cb-box")
        self.assertEqual(flag_values(argv, "--user"), ["root"])
        self.assertEqual(argv[-1], cb.CB_DOCKERD)


class ParsePsRowsTest(unittest.TestCase):
    """Boxes made by the devcontainer CLI carry its label and no cb label, so
    one listing has to read both."""

    def test_reads_cbs_own_folder_label(self):
        rows = cb.parse_ps_rows("cb-a\tUp 2 hours\t/home/u/git/a\t\n")
        self.assertEqual(rows, [("cb-a", "Up 2 hours", "/home/u/git/a")])

    def test_falls_back_to_the_devcontainer_label(self):
        rows = cb.parse_ps_rows("vsc-x\tExited (0)\t\t/home/u/git/x\n")
        self.assertEqual(rows[0][2], "/home/u/git/x")

    def test_says_nothing_rather_than_blank_when_neither_is_set(self):
        rows = cb.parse_ps_rows("other\tUp\t\t\n")
        self.assertEqual(rows[0][2], "-")

    def test_skips_blank_lines(self):
        self.assertEqual(cb.parse_ps_rows("\n\n"), [])

    def test_reads_nothing_from_nothing(self):
        self.assertEqual(cb.parse_ps_rows(""), [])


class FormatTableTest(unittest.TestCase):
    def test_writes_a_header(self):
        lines = cb.format_table([]).splitlines()
        self.assertEqual(lines[0].split(), ["NAME", "STATUS", "FOLDER"])

    def test_keeps_the_header_when_there_is_nothing_to_list(self):
        self.assertEqual(len(cb.format_table([]).splitlines()), 1)

    def test_pads_to_the_widest_cell(self):
        table = cb.format_table([("short", "Up", "/a"), ("much-longer", "Up", "/b")])
        first, second = table.splitlines()[1:]
        self.assertEqual(first.index("Up"), second.index("Up"))


class StartBoxTest(unittest.TestCase):
    """The create / start / post-start decision the devcontainer CLI used to
    make, asserted as the sequence of docker commands it issues.

    No daemon is needed for that: the question is which command runs, not what
    it does. run() and box_for() are the seam — the commands are recorded rather
    than executed, and everything that builds them is the real code.
    """

    def setUp(self):
        self.commands = []
        self.box = None

        def record(argv, quiet=False, check=True):
            self.commands.append(list(argv))
            return 0

        for name, value in (
            ("run", record),
            ("docker_remove", lambda names: self.commands.append(["docker", "rm", "-f"] + names)),
            ("ensure_claude_dir", lambda: None),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def verbs(self):
        """The docker subcommand of each command issued, in order."""
        return [argv[1] for argv in self.commands]

    def test_creates_a_box_that_does_not_exist_yet(self):
        name = cb.start_box("/home/u/git/repo", docker=False, box=None)
        self.assertEqual(self.verbs(), ["run", "exec"])
        self.assertEqual(name, cb.container_name("/home/u/git/repo"))

    def test_starts_a_box_that_already_exists(self):
        box = cb.container_name("/home/u/git/repo")
        cb.start_box("/home/u/git/repo", docker=False, box=box)
        self.assertEqual(self.verbs(), ["start", "exec"])

    def test_never_creates_a_second_container_for_one_checkout(self):
        box = cb.container_name("/home/u/git/repo")
        cb.start_box("/home/u/git/repo", docker=False, box=box)
        self.assertNotIn("run", self.verbs())

    def test_replaces_the_container_when_asked_to_recreate(self):
        box = cb.container_name("/home/u/git/repo")
        cb.start_box("/home/u/git/repo", docker=False, box=box, recreate=True)
        self.assertEqual(self.verbs(), ["rm", "run", "exec"])

    def test_adopts_a_box_made_by_the_devcontainer_version_of_cb(self):
        # Its name is the CLI's, not container_name()'s. Creating alongside it
        # would collide on the name cb would pick; starting it is the migration.
        name = cb.start_box("/home/u/git/repo", docker=False, box="vsc-repo-9f1c3a")
        self.assertEqual(name, "vsc-repo-9f1c3a")
        self.assertEqual(self.commands[0], ["docker", "start", "vsc-repo-9f1c3a"])

    def test_runs_cb_dockerd_against_the_box_it_started(self):
        cb.start_box("/home/u/git/repo", docker=True, box="vsc-repo-9f1c3a")
        self.assertEqual(self.commands[-1][-2:], ["vsc-repo-9f1c3a", cb.CB_DOCKERD])


class LegacyFiltersTest(unittest.TestCase):
    """A box made by the devcontainer version of cb has to stay reachable, but
    VS Code stamps devcontainer.local_folder with the same value for a repo's
    own .devcontainer/ — and adopting that container would exec claude in
    someone else's box, or `cb recreate` would remove it."""

    def test_asks_for_cbs_own_config(self):
        self.assertIn("label=" + cb.LEGACY_CONFIG_LABEL + "=" + cb.LEGACY_CONFIG,
                      cb.legacy_filters())

    def test_narrows_to_one_folder_when_given_one(self):
        filters = cb.legacy_filters("/home/u/git/repo")
        # Two --filter terms in one query are an AND, which is what excludes a
        # foreign devcontainer for the same folder.
        self.assertIn("label={}=/home/u/git/repo".format(cb.DC_FOLDER_LABEL), filters)
        self.assertIn("label=" + cb.LEGACY_CONFIG_LABEL + "=" + cb.LEGACY_CONFIG, filters)

    def test_leaves_the_folder_open_without_one(self):
        self.assertNotIn(cb.DC_FOLDER_LABEL, " ".join(cb.legacy_filters()))


class ScopeTest(unittest.TestCase):
    """The three filterset lists are the whole migration contract: which
    containers cb calls its own, and which it merely knows about."""

    def terms(self, filtersets):
        return " ".join(term for filters in filtersets for term in filters)

    def test_a_cb_box_is_either_generation(self):
        terms = self.terms(cb.BOX_SCOPE)
        self.assertIn("label={}".format(cb.BOX_LABEL), terms)
        self.assertIn("label={}={}".format(cb.LEGACY_CONFIG_LABEL, cb.LEGACY_CONFIG), terms)

    def test_a_cb_box_is_never_just_any_devcontainer(self):
        # `cb down --all` must not reach VS Code's containers without asking.
        self.assertNotIn("label=" + cb.DC_FOLDER_LABEL, self.terms(cb.BOX_SCOPE))

    def test_any_widens_to_every_devcontainer(self):
        self.assertIn("label=" + cb.DC_FOLDER_LABEL, self.terms(cb.ANY_SCOPE))

    def test_a_box_for_one_folder_is_looked_up_under_both_generations(self):
        terms = self.terms(cb.box_filters("/home/u/git/repo"))
        self.assertIn("label={}=/home/u/git/repo".format(cb.FOLDER_LABEL), terms)
        self.assertIn("label={}=/home/u/git/repo".format(cb.DC_FOLDER_LABEL), terms)
        self.assertIn("label={}={}".format(cb.LEGACY_CONFIG_LABEL, cb.LEGACY_CONFIG), terms)


class MergeRowsTest(unittest.TestCase):
    """`--any` is the union of two label queries, and a container carrying both
    labels is answered by both. Listing it twice reads as two boxes; removing it
    twice is an error."""

    def test_keeps_one_row_per_container(self):
        rows = cb.merge_rows([[("cb-a", "Up", "/a")], [("cb-a", "Up", "/a")]])
        self.assertEqual(rows, [("cb-a", "Up", "/a")])

    def test_keeps_the_order_of_the_first_answer(self):
        rows = cb.merge_rows([[("b", "Up", "/b")], [("a", "Up", "/a")]])
        self.assertEqual([row[0] for row in rows], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
