-- nvim-treesitter compiles parsers through tree-sitter-cli, which drives the
-- compiler with Rust's cc crate. That crate adds `-Wall` unless CFLAGS is set,
-- and gcc 13 with `-Wall` needs 5 GB for the gitcommit parser instead of 0.5 GB.
-- On a small machine that is an OOM kill on every start, since the parser
-- stays missing and LazyVim retries it.
--
-- CFLAGS is set only while parser builds run. Set globally it would leak into
-- `:terminal` and change every ./configure started from there.
local running, owned = 0, false

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

return {
  "nvim-treesitter/nvim-treesitter",
  opts = function()
    -- `require("nvim-treesitter").install` and the :TSInstall/:TSUpdate
    -- commands all resolve these two at call time, so wrapping them here
    -- covers LazyVim's ensure_installed, the update hook and manual installs.
    local install = require("nvim-treesitter.install")
    install.install = with_cflags(install.install)
    install.update = with_cflags(install.update)
  end,
}
