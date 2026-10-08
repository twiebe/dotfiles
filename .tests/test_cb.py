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

The leading dot keeps the directory from reading as one more stow package next
to claude-box/ and nvim/ at the top level of the repo.
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

    def test_no_arguments_means_run(self):
        self.assertEqual(cb.pick_subcommand([]), ("run", []))

    def test_a_leading_subcommand_is_taken(self):
        self.assertEqual(cb.pick_subcommand(["ls", "."]), ("ls", ["."]))

    def test_anything_else_is_up_with_claude_arguments(self):
        self.assertEqual(cb.pick_subcommand(["-c"]), ("run", ["-c"]))

    def test_a_subcommand_name_later_on_the_line_belongs_to_claude(self):
        # `cb -p down` asks claude about something called down; it is not
        # a subcommand.
        self.assertEqual(cb.pick_subcommand(["-p", "down"]), ("run", ["-p", "down"]))


class LeadingFlagsTest(unittest.TestCase):
    """`cb --docker shell` is a shell with docker, not claude asked about
    "shell": cb's own flags may come before the subcommand."""

    def test_subcommand_after_a_toggle(self):
        self.assertEqual(cb.pick_subcommand(["--docker", "shell"]), ("shell", ["--docker"]))

    def test_subcommand_after_a_value_flag(self):
        self.assertEqual(
            cb.pick_subcommand(["-v", "/x", "shell"]), ("shell", ["-v", "/x"])
        )

    def test_the_value_of_a_value_flag_is_not_a_subcommand(self):
        # A directory called ls is a mount source, not the ls command.
        self.assertEqual(cb.pick_subcommand(["-v", "ls"]), ("run", ["-v", "ls"]))

    def test_a_claude_flag_still_ends_the_search(self):
        self.assertEqual(cb.pick_subcommand(["-c", "shell"]), ("run", ["-c", "shell"]))

    def test_removed_word_after_a_flag_is_refused(self):
        def started(flags, command):
            raise AssertionError("started a box for " + repr(command))

        self.addCleanup(setattr, cb, "start", cb.start)
        cb.start = started
        with self.assertRaises(cb.UsageError):
            cb.main(["--docker", "down"])

    def test_dry_run_before_exec(self):
        self.addCleanup(setattr, cb, "DRY_RUN", False)
        for name, value in (
            ("running_boxes", lambda: [("cb-a-1-abcd", "now", "/w")]),
            ("current_workspace", lambda: "/w"),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cb.main(["--dry-run", "exec", "ls", "--dry-run"])
        line = out.getvalue().strip()
        self.assertTrue(line.startswith("+ docker exec"), line)
        self.assertTrue(line.endswith("cb-a-1-abcd ls --dry-run"), line)


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

    def test_help_is_cbs_own(self):
        flags, _ = cb.extract_flags(["--help"])
        self.assertIs(flags["help"], True)

    def test_volumes_default_to_empty(self):
        flags, _ = cb.extract_flags([])
        self.assertEqual(flags["volumes"], [])

    def test_volume_takes_the_next_argument(self):
        flags, rest = cb.extract_flags(["-v", "../lib", "-c"])
        self.assertEqual((flags["volumes"], rest), (["../lib"], ["-c"]))

    def test_volume_long_form_and_repetition(self):
        flags, _ = cb.extract_flags(["--volume", "/a", "-v", "/b:ro"])
        self.assertEqual(flags["volumes"], ["/a", "/b:ro"])

    def test_volume_without_a_value_is_refused(self):
        # `cb -v` meaning claude's --version must not start a box.
        with self.assertRaises(cb.UsageError):
            cb.extract_flags(["-v"])

    def test_v_after_double_dash_is_claudes(self):
        flags, rest = cb.extract_flags(["--", "-v"])
        self.assertEqual((flags["volumes"], rest), ([], ["-v"]))


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
        self.assertEqual(cb.parse_github_release({"tag_name": "v1.12.6"}), "1.12.6")

    def test_reads_kubectl_from_its_latest_release(self):
        # The Dockerfile adds the "v" back for registry.k8s.io/kubectl, so the
        # stored version stays comparable with the other toolchains.
        self.assertEqual(cb.parse_github_release({"tag_name": "v1.37.1"}), "1.37.1")
        self.assertIn("kubectl", cb.TOOLCHAINS)

    def test_nothing_arrived(self):
        for parse in (cb.parse_uv_version, cb.parse_go_version, cb.parse_github_release):
            self.assertIsNone(parse(None))

    def test_something_unexpected_arrived(self):
        # A lookup that answers HTML, an error document, or a renamed field must
        # leave the pinned default in the Dockerfile standing.
        for parse, junk in (
            (cb.parse_uv_version, {"message": "Not Found"}),
            (cb.parse_go_version, []),
            (cb.parse_go_version, [{"stable": False}]),
            (cb.parse_github_release, {"tag_name": ""}),
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


class ResolvePathTest(unittest.TestCase):
    def test_joins_a_relative_path_onto_the_base(self):
        self.assertEqual(cb.resolve_path("../data", "/home/u/git/repo"), "/home/u/git/data")

    def test_keeps_an_absolute_path(self):
        self.assertEqual(cb.resolve_path("/srv/x/", "/home/u/git/repo"), "/srv/x")

    def test_expands_the_home_directory(self):
        self.assertEqual(
            cb.resolve_path("~/data", "/w"), os.path.join(os.path.expanduser("~"), "data")
        )


class ParseMountTest(unittest.TestCase):
    """SRC[:DST][:ro|rw], with DST defaulting to the way the workspace itself is
    placed: /workspaces/<slug of the basename>."""

    WS = "/home/u/git/repo"

    def test_source_only_lands_next_to_the_workspace(self):
        self.assertEqual(
            cb.parse_mount("/home/u/git/My_Lib", self.WS),
            ("/home/u/git/My_Lib", "/workspaces/my-lib", False),
        )

    def test_relative_source_is_resolved_against_the_workspace(self):
        self.assertEqual(cb.parse_mount("../lib", self.WS)[0], "/home/u/git/lib")

    def test_explicit_target(self):
        self.assertEqual(
            cb.parse_mount("/data:/mnt/data", self.WS), ("/data", "/mnt/data", False)
        )

    def test_read_only_without_target(self):
        self.assertEqual(
            cb.parse_mount("/data:ro", self.WS), ("/data", "/workspaces/data", True)
        )

    def test_read_only_with_target(self):
        self.assertEqual(
            cb.parse_mount("/data:/mnt/d:ro", self.WS), ("/data", "/mnt/d", True)
        )

    def test_rw_is_accepted_and_is_the_default(self):
        self.assertEqual(cb.parse_mount("/data:rw", self.WS)[2], False)

    def test_refuses_a_relative_target(self):
        with self.assertRaises(cb.UsageError):
            cb.parse_mount("/data:mnt", self.WS)

    def test_refuses_an_empty_target(self):
        with self.assertRaises(cb.UsageError):
            cb.parse_mount("/data:", self.WS)

    def test_refuses_an_empty_source(self):
        with self.assertRaises(cb.UsageError):
            cb.parse_mount(":/mnt", self.WS)

    def test_refuses_too_many_parts(self):
        with self.assertRaises(cb.UsageError):
            cb.parse_mount("/a:/b:/c", self.WS)

    def test_refuses_a_comma(self):
        # docker reads --mount as CSV.
        with self.assertRaises(cb.UsageError):
            cb.parse_mount("/a,b", self.WS)

    def test_round_trips_through_format(self):
        mount = ("/data", "/mnt/d", True)
        self.assertEqual(cb.parse_mount(cb.format_mount(mount), "/"), mount)


class MountValueTest(unittest.TestCase):
    def test_bind(self):
        self.assertEqual(
            cb.mount_value(("/a", "/b", False)), "type=bind,source=/a,target=/b"
        )

    def test_read_only(self):
        self.assertEqual(
            cb.mount_value(("/a", "/b", True)), "type=bind,source=/a,target=/b,readonly"
        )


class MergeMountsTest(unittest.TestCase):
    def test_keeps_both_lists(self):
        merged = cb.merge_mounts([("/a", "/x", False)], [("/b", "/y", False)])
        self.assertEqual(merged, [("/a", "/x", False), ("/b", "/y", False)])

    def test_a_run_mount_replaces_a_persistent_one_on_the_same_target(self):
        merged = cb.merge_mounts([("/a", "/x", False)], [("/a", "/x", True)])
        self.assertEqual(merged, [("/a", "/x", True)])

    def test_two_run_mounts_on_one_target_are_refused(self):
        with self.assertRaises(cb.UsageError):
            cb.merge_mounts([], [("/a", "/x", False), ("/b", "/x", False)])


class CheckTargetsTest(unittest.TestCase):
    WS = "/home/u/git/repo"

    def check(self, target):
        cb.check_targets([("/src", target, False)], cb.fixed_targets(self.WS))

    def test_accepts_a_sibling_of_the_workspace(self):
        self.check("/workspaces/other")

    def test_refuses_the_workspace_folder(self):
        with self.assertRaises(cb.UsageError):
            self.check("/workspaces/repo")

    def test_refuses_a_path_inside_a_fixed_target(self):
        with self.assertRaises(cb.UsageError):
            self.check("/home/node/.claude/skills")

    def test_refuses_a_path_above_a_fixed_target(self):
        # Mounting over /home/node would hide ~/.claude and the browser cache.
        with self.assertRaises(cb.UsageError):
            self.check("/home/node")

    def test_a_shared_prefix_is_not_nesting(self):
        self.check("/commandhistory-extra")


class RequireSourcesTest(unittest.TestCase):
    def test_accepts_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            cb.require_sources([(tmp, "/x", False)])

    def test_refuses_a_missing_source(self):
        with self.assertRaises(cb.CbError):
            cb.require_sources([("/does/not/exist", "/x", False)])


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

    def test_keeps_playwright_from_deleting_other_boxes_browsers(self):
        self.assertEqual(
            cb.container_env(docker=False)["PLAYWRIGHT_SKIP_BROWSER_GC"], "1"
        )

    def test_passes_the_hosts_terminal_through(self):
        os.environ["TERM_PROGRAM"] = "ghostty"
        self.assertEqual(cb.container_env(docker=False)["TERM_PROGRAM"], "ghostty")

    def test_omits_a_host_variable_that_is_not_set(self):
        # ${localEnv:} used to hand over an empty value, which reads as "set to
        # nothing" rather than "unset" to anything probing it.
        self.assertNotIn("TERM_PROGRAM", cb.container_env(docker=False))


class RunArgvTest(unittest.TestCase):
    """One box per run: docker run --rm, the command in the foreground."""

    def setUp(self):
        self.workspace = "/home/u/git/repo"
        self.argv = cb.run_argv(
            self.workspace, docker=False, mounts=[], command=["claude", "-c"],
            tty=False, suffix="abcd",
        )

    def test_removes_the_container_when_the_command_ends(self):
        self.assertEqual(self.argv[:4], ["docker", "run", "--rm", "--init"])

    def test_keeps_stdin_open(self):
        self.assertIn("--interactive", self.argv)

    def test_names_the_container_after_the_box_plus_a_suffix(self):
        self.assertEqual(
            flag_values(self.argv, "--name"), [cb.container_name(self.workspace) + "-abcd"]
        )

    def test_two_runs_get_two_names(self):
        a = cb.run_argv(self.workspace, False, [], ["zsh"], tty=False)
        b = cb.run_argv(self.workspace, False, [], ["zsh"], tty=False)
        self.assertNotEqual(flag_values(a, "--name"), flag_values(b, "--name"))

    def test_hostname_has_no_suffix(self):
        # The prompt stays the same from run to run.
        self.assertEqual(
            flag_values(self.argv, "--hostname"), [cb.container_name(self.workspace)]
        )

    def test_labels(self):
        labels = flag_values(self.argv, "--label")
        self.assertIn("{}={}".format(cb.BOX_LABEL, cb.BOX_GENERATION), labels)
        self.assertIn("{}={}".format(cb.FOLDER_LABEL, self.workspace), labels)

    def test_mounts_checkout_claude_dir_history_and_browsers(self):
        mounts = flag_values(self.argv, "--mount")
        self.assertIn(
            "type=bind,source={},target={}".format(
                self.workspace, cb.workspace_folder(self.workspace)
            ),
            mounts,
        )
        self.assertIn(
            "type=bind,source={},target={}".format(cb.HOST_CLAUDE_DIR, cb.BOX_CLAUDE_DIR),
            mounts,
        )
        self.assertIn(
            "type=volume,source={},target=/commandhistory".format(
                cb.history_volume(self.workspace)
            ),
            mounts,
        )
        self.assertIn(
            "type=volume,source=cb-playwright,target=/home/node/.cache/ms-playwright",
            mounts,
        )

    def test_adds_extra_mounts(self):
        argv = cb.run_argv(
            self.workspace, False, [("/data", "/mnt/d", True)], ["zsh"], tty=False
        )
        self.assertIn(
            "type=bind,source=/data,target=/mnt/d,readonly", flag_values(argv, "--mount")
        )

    def test_starts_in_the_workspace_folder(self):
        self.assertEqual(
            flag_values(self.argv, "--workdir"), [cb.workspace_folder(self.workspace)]
        )

    def test_renders_the_environment(self):
        self.assertIn("CB_DIND=false", flag_values(self.argv, "--env"))

    def test_privileged_only_with_docker(self):
        self.assertNotIn("--privileged", self.argv)
        self.assertIn(
            "--privileged", cb.run_argv(self.workspace, True, [], ["zsh"], tty=False)
        )

    def test_tty_and_term_when_there_is_a_terminal(self):
        self.addCleanup(os.environ.pop, "TERM", None)
        os.environ["TERM"] = "xterm-ghostty"
        argv = cb.run_argv(self.workspace, False, [], ["zsh"], tty=True)
        self.assertIn("--tty", argv)
        self.assertIn("TERM=xterm-ghostty", flag_values(argv, "--env"))

    def test_no_tty_without_a_terminal(self):
        self.assertNotIn("--tty", self.argv)

    def test_refuses_a_workspace_path_with_a_comma(self):
        with self.assertRaises(cb.UsageError):
            cb.run_argv("/home/u/git/a,b", False, [], ["zsh"], tty=False)

    def test_ends_with_the_image_the_entrypoint_and_the_command(self):
        self.assertEqual(self.argv[-4:], [cb.CB_IMAGE, cb.CB_ENTRY, "claude", "-c"])


class CmdRunTest(unittest.TestCase):
    """The run path end to end, with the side effects recorded."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "repo")
        os.mkdir(self.workspace)
        self.replaced = []
        settings = os.path.join(self.tmp.name, "settings.json")
        for name, value in (
            ("current_workspace", lambda: self.workspace),
            ("settings_path", lambda path: settings),
            ("roots", lambda: [self.tmp.name]),
            ("ensure_image", lambda: None),
            ("check_docker_feature", lambda docker: None),
            ("ensure_claude_dir", lambda: None),
            ("ensure_history_volume", lambda workspace: None),
            ("replace_process", self.replaced.append),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def flags(self, **overrides):
        flags, _ = cb.extract_flags([])
        flags.update(overrides)
        return flags

    def test_run_starts_claude_with_its_arguments(self):
        cb.cmd_run(self.flags(), ["--continue"])
        self.assertEqual(self.replaced[0][-2:], ["claude", "--continue"])

    def test_shell_starts_zsh(self):
        cb.cmd_shell(self.flags(), [])
        self.assertEqual(self.replaced[0][-1], "zsh")

    def test_shell_rejects_arguments(self):
        with self.assertRaises(cb.UsageError):
            cb.cmd_shell(self.flags(), ["ls"])

    def test_per_run_mount_is_added(self):
        cb.cmd_run(self.flags(volumes=[self.tmp.name + ":/mnt/t"]), [])
        self.assertIn(
            "type=bind,source={},target=/mnt/t".format(self.tmp.name),
            flag_values(self.replaced[0], "--mount"),
        )

    def test_missing_mount_source_stops_before_docker(self):
        with self.assertRaises(cb.CbError):
            cb.cmd_run(self.flags(volumes=["/does/not/exist"]), [])
        self.assertEqual(self.replaced, [])

    def test_gate_applies_on_every_run(self):
        cb.roots = lambda: ["/nowhere"]
        with self.assertRaises(cb.UsageError):
            cb.cmd_run(self.flags(), [])


class RemovedSubcommandTest(unittest.TestCase):
    """Habit types `cb down`. That must not become a claude prompt."""

    def test_removed_words_are_refused_with_a_pointer(self):
        for word in ("up", "down", "recreate"):
            with self.assertRaises(cb.UsageError):
                cb.main([word])

    def test_double_dash_still_reaches_claude(self):
        name, rest = cb.pick_subcommand(["--", "down"])
        self.assertEqual(name, "run")


class MountCommandTest(unittest.TestCase):
    """Remembered mounts round-trip through the per-workspace settings file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "repo")
        self.lib = os.path.join(self.tmp.name, "lib")
        os.mkdir(self.workspace)
        os.mkdir(self.lib)
        self.settings = os.path.join(self.tmp.name, "settings.json")
        for name, value in (
            ("current_workspace", lambda: self.workspace),
            ("settings_path", lambda path: self.settings),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def mount(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cb.cmd_mount({"yes": False}, list(args))
        return out.getvalue()

    def stored(self):
        return cb.stored_mounts(cb.load_settings(self.settings))

    def test_add_stores_the_resolved_spec(self):
        self.mount("add", "../lib:ro")
        self.assertEqual(self.stored(), [(self.lib, "/workspaces/lib", True)])

    def test_ls_lists_them(self):
        self.mount("add", "../lib")
        self.assertIn("/workspaces/lib", self.mount("ls"))

    def test_rm_by_source(self):
        self.mount("add", "../lib")
        self.mount("rm", "../lib")
        self.assertEqual(self.stored(), [])

    def test_rm_by_target(self):
        self.mount("add", "../lib")
        self.mount("rm", "/workspaces/lib")
        self.assertEqual(self.stored(), [])

    def test_rm_unknown_is_an_error(self):
        with self.assertRaises(cb.CbError):
            self.mount("rm", "/nothing")

    def test_add_refuses_a_missing_source_and_stores_nothing(self):
        with self.assertRaises(cb.CbError):
            self.mount("add", "../nope")
        self.assertEqual(self.stored(), [])

    def test_add_refuses_a_taken_target(self):
        self.mount("add", "../lib")
        with self.assertRaises(cb.UsageError):
            self.mount("add", self.tmp.name + ":/workspaces/lib")

    def test_add_refuses_a_fixed_target(self):
        with self.assertRaises(cb.UsageError):
            self.mount("add", "../lib:/home/node/.claude")

    def test_add_keeps_other_settings(self):
        cb.save_settings(self.settings, {"docker": True}, self.workspace)
        self.mount("add", "../lib")
        self.assertIs(cb.load_settings(self.settings)["docker"], True)

    def test_unknown_action(self):
        with self.assertRaises(cb.UsageError):
            self.mount("purge")

    def test_config_refuses_to_set_mounts(self):
        with self.assertRaises(cb.UsageError):
            cb.set_setting("mounts", "true")


class VolumePruneTest(unittest.TestCase):
    """Which docker commands `cb volume prune` issues, recorded rather than run."""

    def setUp(self):
        self.commands = []
        self.volumes = {"cb-playwright"}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dangling = (
            "cb-history-aaaa\t/gone/checkout\n"
            "cb-history-bbbb\t{}\n"
            "cb-history-cccc\t\n"
            "not-cb-history-dddd\t/gone\n"
        ).format(self.tmp.name)

        def record(argv, quiet=False, check=True):
            self.commands.append(list(argv))
            return 0

        def fake_capture(argv):
            if argv[:3] == ["docker", "volume", "inspect"]:
                return "[]" if argv[3] in self.volumes else None
            if argv[:3] == ["docker", "volume", "ls"]:
                return self.dangling
            raise AssertionError(argv)

        for name, value in (("run", record), ("capture", fake_capture)):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def prune(self, target):
        with contextlib.redirect_stdout(io.StringIO()):
            return cb.cmd_volume({"yes": True}, ["prune", target])

    def test_playwright_empties_the_volume_instead_of_removing_it(self):
        # Every box has it mounted, so docker would refuse the removal.
        self.prune("playwright")
        self.assertEqual(self.commands, [cb.empty_volume_argv("cb-playwright")])

    def test_playwright_leaves_the_history_alone(self):
        self.prune("playwright")
        self.assertFalse(any(argv[:3] == ["docker", "volume", "rm"] for argv in self.commands))

    def test_all_removes_history_of_gone_checkouts_only(self):
        self.prune("all")
        self.assertIn(["docker", "volume", "rm", "cb-history-aaaa"], self.commands)

    def test_all_keeps_history_of_an_existing_checkout(self):
        # Every history volume is dangling between runs now.
        self.prune("all")
        removed = [a for a in self.commands if a[:3] == ["docker", "volume", "rm"]]
        self.assertFalse(any("cb-history-bbbb" in argv for argv in removed))

    def test_all_keeps_unlabelled_history(self):
        self.prune("all")
        removed = [a for a in self.commands if a[:3] == ["docker", "volume", "rm"]]
        self.assertFalse(any("cb-history-cccc" in argv for argv in removed))

    def test_all_says_what_it_skipped(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cb.cmd_volume({"yes": True}, ["prune", "all"])
        self.assertIn("skipped (no label): cb-history-cccc", out.getvalue())

    def test_does_nothing_when_there_is_nothing(self):
        self.volumes = set()
        self.dangling = ""
        self.prune("all")
        self.assertEqual(self.commands, [])

    def test_refuses_an_unknown_target(self):
        with self.assertRaises(cb.UsageError):
            cb.cmd_volume({"yes": True}, ["prune", "history"])

    def test_refuses_without_a_target(self):
        with self.assertRaises(cb.UsageError):
            cb.cmd_volume({"yes": True}, ["prune"])

    def test_asks_before_touching_anything(self):
        # No terminal to answer on, which confirm() takes as a no.
        self.addCleanup(setattr, cb.sys, "stdin", cb.sys.stdin)
        cb.sys.stdin = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(cb.CbError):
            cb.cmd_volume({"yes": False}, ["prune", "all"])
        self.assertEqual(self.commands, [])


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


class EnsureImageTest(unittest.TestCase):
    """An image from before cb-entry would fail every run with a bare docker
    "no such file" after cb has already exec'd away, so it counts as missing."""

    def setUp(self):
        self.built = []
        self.label = "1"
        self.exists = True
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        state = Path(self.tmp.name) / "image.json"
        state.write_text('{"rust": false, "versions": {"go": "1.26.5"}}')
        for name, value in (
            ("image_state_path", lambda: str(state)),
            ("image_exists", lambda: self.exists),
            ("image_label", lambda name: self.label if name == cb.ENTRY_LABEL else None),
            ("latest_versions", lambda: {"go": "9.9.9"}),
            ("build_image", lambda features, versions, no_cache=False: self.built.append(versions)),
        ):
            self.addCleanup(setattr, cb, name, getattr(cb, name))
            setattr(cb, name, value)

    def ensure(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cb.ensure_image()

    def test_a_current_image_is_left_alone(self):
        self.ensure()
        self.assertEqual(self.built, [])

    def test_an_image_without_cb_entry_is_rebuilt_at_its_own_versions(self):
        # Like update-claude: only the layers from cb-entry down change.
        self.label = None
        self.ensure()
        self.assertEqual(self.built, [{"go": "1.26.5"}])

    def test_a_missing_image_is_built_at_the_newest_versions(self):
        self.exists = False
        self.label = None
        self.ensure()
        self.assertEqual(self.built, [{"go": "9.9.9"}])


class RunningBoxesTest(unittest.TestCase):
    """Boxes from the long-lived lifecycle carry cb.box=1 and idle forever. They
    must not be what `cb exec` picks or `cb ls` lists."""

    def test_asks_only_for_this_generation(self):
        asked = []

        def fake_capture(argv):
            asked.append(argv)
            return ""

        self.addCleanup(setattr, cb, "capture", cb.capture)
        cb.capture = fake_capture
        cb.running_boxes()
        self.assertIn(
            "label={}={}".format(cb.BOX_LABEL, cb.BOX_GENERATION), asked[0]
        )
        self.assertNotEqual(cb.BOX_GENERATION, "1")


class ParsePsRowsTest(unittest.TestCase):
    def test_reads_name_started_and_folder(self):
        rows = cb.parse_ps_rows("cb-a-1-abcd\t5 minutes ago\t/home/u/git/a\n")
        self.assertEqual(rows, [("cb-a-1-abcd", "5 minutes ago", "/home/u/git/a")])

    def test_says_nothing_rather_than_blank_without_a_folder(self):
        self.assertEqual(cb.parse_ps_rows("x\tnow\t\n")[0][2], "-")

    def test_skips_blank_lines(self):
        self.assertEqual(cb.parse_ps_rows("\n\n"), [])


class PickBoxTest(unittest.TestCase):
    """Which running box `cb exec` goes into."""

    ROWS = [
        ("cb-a-11111111-abcd", "1m", "/home/u/git/a"),
        ("cb-a-11111111-ef01", "2m", "/home/u/git/a"),
        ("cb-b-22222222-1234", "3m", "/home/u/git/b"),
        ("cb-c-33333333-abcd", "4m", "/home/u/git/c"),
    ]

    def test_the_only_box_of_the_workspace(self):
        self.assertEqual(cb.pick_box(self.ROWS, "/home/u/git/b", None), "cb-b-22222222-1234")

    def test_no_box_for_the_workspace(self):
        with self.assertRaises(cb.CbError):
            cb.pick_box(self.ROWS, "/home/u/git/z", None)

    def test_several_boxes_name_them(self):
        with self.assertRaises(cb.CbError) as caught:
            cb.pick_box(self.ROWS, "/home/u/git/a", None)
        self.assertIn("cb-a-11111111-ef01", str(caught.exception))

    def test_by_full_name(self):
        self.assertEqual(
            cb.pick_box(self.ROWS, "/x", "cb-a-11111111-ef01"), "cb-a-11111111-ef01"
        )

    def test_by_suffix(self):
        self.assertEqual(cb.pick_box(self.ROWS, "/x", "ef01"), "cb-a-11111111-ef01")

    def test_ambiguous_suffix_is_refused(self):
        with self.assertRaises(cb.CbError):
            cb.pick_box(self.ROWS, "/x", "abcd")

    def test_unknown_name(self):
        with self.assertRaises(cb.CbError):
            cb.pick_box(self.ROWS, "/x", "9999")


class SplitExecArgsTest(unittest.TestCase):
    def test_plain_command(self):
        self.assertEqual(cb.split_exec_args(["ls", "-n"]), (None, ["ls", "-n"]))

    def test_leading_name(self):
        self.assertEqual(cb.split_exec_args(["-n", "abcd", "zsh"]), ("abcd", ["zsh"]))

    def test_needs_a_command(self):
        with self.assertRaises(cb.UsageError):
            cb.split_exec_args(["-n", "abcd"])

    def test_needs_a_name_after_n(self):
        with self.assertRaises(cb.UsageError):
            cb.split_exec_args(["-n"])


class LsTargetTest(unittest.TestCase):
    def test_no_argument_lists_everything(self):
        self.assertIsNone(cb.ls_folder([], "/home/u/git/a"))

    def test_dot_is_the_workspace(self):
        self.assertEqual(cb.ls_folder(["."], "/home/u/git/a"), "/home/u/git/a")

    def test_relative_is_logical(self):
        self.assertEqual(cb.ls_folder(["../b"], "/home/u/git/a"), "/home/u/git/b")

    def test_more_than_one_is_refused(self):
        with self.assertRaises(cb.UsageError):
            cb.ls_folder([".", ".."], "/home/u/git/a")


class FormatTableTest(unittest.TestCase):
    def test_writes_a_header(self):
        lines = cb.format_table([]).splitlines()
        self.assertEqual(lines[0].split(), ["NAME", "STARTED", "FOLDER"])

    def test_keeps_the_header_when_there_is_nothing_to_list(self):
        self.assertEqual(len(cb.format_table([]).splitlines()), 1)

    def test_pads_to_the_widest_cell(self):
        table = cb.format_table([("short", "Up", "/a"), ("much-longer", "Up", "/b")])
        first, second = table.splitlines()[1:]
        self.assertEqual(first.index("Up"), second.index("Up"))


if __name__ == "__main__":
    unittest.main()
