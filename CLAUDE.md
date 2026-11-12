# Q-nwn-manager

## Working directory hygiene

- Do **not** delete `.swamp/` audit directories that appear after running
  shell commands with `cwd` inside this repo (a side effect of the swamp
  CLI harness). Leave them in place - just make sure they aren't
  accidentally `git add`ed/committed (check `git status` before staging).
