-- How parsers get onto this machine.
--
-- Preferred: prebuilt. `nvim-parsers` installs the tarball baked by
-- .github/workflows/nvim-parsers.yml and leaves a stamp file with the
-- nvim-treesitter commit it was built from. With that stamp present nothing
-- here compiles: no ensure_installed at start, no TSUpdate after a plugin
-- update. A stamp that no longer matches lazy-lock.json gets a warning.
--
-- Fallback: compile, with one fix. nvim-treesitter compiles through
-- tree-sitter-cli, which drives the compiler with Rust's cc crate. That crate
-- adds `-Wall` unless CFLAGS is set, and gcc 13 with `-Wall` needs 5 GB for
-- the gitcommit parser instead of 0.5 GB. On a small machine that is an OOM
-- kill on every start, since the parser stays missing and LazyVim retries it.
-- CFLAGS is set only while parser builds run. Set globally it would leak into
-- `:terminal` and change every ./configure started from there.

local stamp = vim.fn.stdpath("data") .. "/site/.nvim-parsers"
local baked = vim.uv.fs_stat(stamp) ~= nil

local function baked_commit()
  return vim.trim(vim.fn.readfile(stamp)[1] or "")
end

local function lock_commit()
  local lock = vim.fn.stdpath("config") .. "/lazy-lock.json"
  local ok, entries = pcall(vim.json.decode, table.concat(vim.fn.readfile(lock), "\n"))
  return ok and entries["nvim-treesitter"] and entries["nvim-treesitter"].commit or nil
end

local running, owned, wrapped = 0, false, false

local function with_cflags(build)
  return function(...)
    if running == 0 and vim.env.CFLAGS == nil then
      vim.env.CFLAGS = "-O2"
      owned = true
    end
    running = running + 1
    local task = build(...)
    task:await(function()
      running = running - 1
      if running == 0 and owned then
        vim.env.CFLAGS = nil
        owned = false
      end
    end)
    return task
  end
end

local function wrap_builds()
  -- Only once the plugin is loading: requiring one of its modules earlier
  -- would make lazy.nvim load it, config and all, as a side effect of merely
  -- evaluating these opts.
  if wrapped or not require("lazy.core.config").plugins["nvim-treesitter"]._.loaded then
    return
  end
  -- `require("nvim-treesitter").install` and the :TSInstall/:TSUpdate
  -- commands all resolve these two at call time, so wrapping them covers
  -- LazyVim's ensure_installed, the update hook and manual installs.
  local install = require("nvim-treesitter.install")
  install.install = with_cflags(install.install)
  install.update = with_cflags(install.update)
  wrapped = true
end

local spec = {
  "nvim-treesitter/nvim-treesitter",
  opts = function(_, opts)
    if baked then
      opts.ensure_installed = {}
      local want, have = lock_commit(), baked_commit()
      if want ~= have then
        vim.schedule(function()
          vim.notify(
            ("prebuilt parsers are from %s, lazy-lock.json wants %s: run `nvim-parsers`"):format(
              have:sub(1, 7),
              (want or "?"):sub(1, 7)
            ),
            vim.log.levels.WARN,
            { title = "nvim-parsers" }
          )
        end)
      end
    end
    wrap_builds()
  end,
}

if baked then
  spec.build = false
end

return spec
