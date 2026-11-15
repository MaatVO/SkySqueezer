# Releases and self-update

![From a push on main to a new version: CI builds the executables for Linux, macOS and Windows with checksums and
publishes a release; at start-up the app looks for a newer release in the background and asks before it downloads
it, verifies its SHA-256 and swaps the executable, which is used from the next start](diagrams/release-update.svg)

## The standalone executable

[packaging/build.sh](../packaging/build.sh) builds `dist/sks-dl`, one file with Python and every dependency
inside, for the platform it runs on (PyInstaller does not cross-compile):

1. `uv sync --dev`;
2. writes the version into `src/skysqueezer/_version.py`: the release number in CI, `<pyproject version>+local`
   on a developer's machine;
3. builds `packaging/agent.zip`, the code bundle the app uploads to servers (see [Remote use](remote.md));
4. runs PyInstaller with the hooks in `packaging/hooks/` (ecCodes, NiceGUI) and the extra data files.

Data files that are not Python (`gui/search_select.js`, `agent.zip`) have to be added in `build.sh`. The logo is a
Python module (`gui/logo.py`), so it travels everywhere the code goes without that.

## CI and release numbers

[.github/workflows/build.yml](../.github/workflows/build.yml) runs on every push to `main`:

- the version is `<major>.<minor>` from `pyproject.toml` plus the CI run number (for example `0.2.57`);
- the executable is built on Linux, macOS and Windows, each with a `.sha256` file next to it;
- a GitHub release is created with the executables, the checksums, and release notes listing the commits since
  the previous release ([packaging/release_notes.py](../packaging/release_notes.py)).

## Self-update

[update.py](../src/skysqueezer/update.py), on every start of the packaged app:

1. asks GitHub for the latest release, in the background, so start-up is never delayed;
2. if it is newer than this build, a pop-up in the app asks first
   ([gui/connect.py](../src/skysqueezer/gui/connect.py)): **Download update**, **Not now** (asked again next start)
   or **Skip this version** (remembered in `update.json` in the config folder; a later release is offered again).
   It links to the release page;
3. only on a yes, downloads the executable for this platform and checks it against the release's `.sha256`; a
   mismatch changes nothing;
4. swaps it in place of the running executable, which carries on. The new version runs from the next start (the
   UI says so). Download jobs, here and on servers, are not affected.

Anything that goes wrong (offline, no permission to write next to the executable, unknown platform) is shown in
the pop-up, with **Try again**, and nothing changes. Leftovers of an interrupted update are cleaned at the next start.

Only the packaged executable updates itself:

- running from source or a `uv tool install` never does;
- a local build (`+local`) never replaces itself at start-up, so you can try your changes;
- `--no-update` or `SKS_DL_NO_UPDATE=1` turns it off; `sks-dl update` checks on demand.
