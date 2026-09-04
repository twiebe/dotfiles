"""Unit tests for the pure half of cb.

Everything that shells out to docker or devcontainer is out of scope; what is
covered here is the logic that decides *what* those commands get called with,
which is the part that used to fail silently in the zsh version.

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


if __name__ == "__main__":
    unittest.main()
