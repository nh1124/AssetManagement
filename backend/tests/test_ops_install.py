"""ops/install.sh records the checkout it runs from as AM_REPO_DIR (synthetic HOME and repositories only)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "ops"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "init.defaultBranch=main"]


@pytest.fixture
def world(tmp_path):
    """A throwaway deployment checkout (git repo with ops/ and docker-compose.yml), HOME and command doubles."""
    repo = tmp_path / "clone"
    shutil.copytree(OPS, repo / "ops")
    (repo / "docker-compose.yml").write_text("services: {}\n")
    subprocess.run([*GIT, "init", "-q", str(repo)], check=True)
    subprocess.run([*GIT, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run([*GIT, "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("systemctl", "docker"):
        stub = stubs / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    return {"repo": repo, "home": home, "stubs": stubs, "tmp": tmp_path}


def install(world, checkout=None, *args):
    checkout = checkout or world["repo"]
    env = {**os.environ, "HOME": str(world["home"]), "PATH": f"{world['stubs']}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(checkout / "ops/install.sh"), *args], env=env, capture_output=True, text=True, check=True)


def configured(world):
    config = world["home"] / ".config/am-ops/config.env"
    env = {"HOME": str(world["home"]), "PATH": os.environ["PATH"]}
    value = subprocess.run(["bash", "-c", f'. "{config}"; printf %s "$AM_REPO_DIR"'], env=env,
                           capture_output=True, text=True, check=True).stdout
    return value, config.read_text()


def test_new_install_records_the_checkout(world):
    result = install(world)
    value, text = configured(world)
    assert value == str(world["repo"].resolve())
    assert text.count("AM_REPO_DIR=") == 1  # the sample's default line is replaced, not duplicated
    assert "recorded AM_REPO_DIR=" in result.stdout
    assert (world["home"] / ".local/bin/am-admin").is_symlink()


def test_running_again_changes_nothing(world):
    install(world)
    _, before = configured(world)
    result = install(world)
    _, after = configured(world)
    assert after == before
    assert "recorded" not in result.stdout


def test_existing_other_checkout_is_kept_unless_asked(world):
    other = world["tmp"] / "deployed"
    other.mkdir()
    config_dir = world["home"] / ".config/am-ops"
    config_dir.mkdir(parents=True)
    (config_dir / "config.env").write_text(f'AM_REPO_DIR="{other}"\nAM_BACKUP_ROOT="$HOME/backups"\n')
    result = install(world)
    value, text = configured(world)
    assert value == str(other)
    assert "--set-repo-dir" in result.stderr
    install(world, None, "--set-repo-dir")
    value, text = configured(world)
    assert value == str(world["repo"].resolve())
    assert 'AM_BACKUP_ROOT="$HOME/backups"' in text  # other settings survive
    assert text.count("AM_REPO_DIR=") == 1


def test_missing_setting_in_an_old_config_is_added(world):
    config_dir = world["home"] / ".config/am-ops"
    config_dir.mkdir(parents=True)
    (config_dir / "config.env").write_text('AM_BACKUP_ROOT="$HOME/backups"\n')
    install(world)
    value, _ = configured(world)
    assert value == str(world["repo"].resolve())


def test_a_linked_worktree_does_not_take_over(world):
    install(world)
    worktree = world["tmp"] / "feature"
    subprocess.run([*GIT, "-C", str(world["repo"]), "worktree", "add", "-q", str(worktree), "-b", "feature"], check=True)
    result = install(world, worktree)
    value, _ = configured(world)
    assert value == str(world["repo"].resolve())
    assert "linked git worktree" in result.stderr


def test_path_with_spaces_round_trips(world):
    spaced = world["tmp"] / "my clone"
    shutil.copytree(world["repo"], spaced, symlinks=True)
    install(world, spaced)
    value, _ = configured(world)
    assert value == str(spaced.resolve())
