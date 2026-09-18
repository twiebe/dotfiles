-- Mason builds some packages with a language toolchain (go install, npm
-- install, pip ...). A machine without that toolchain logs an install failure
-- for each of them on every start. The toolchain a package needs is encoded in
-- its registry purl (`pkg:golang/...`, `pkg:npm/...`), so filter on that and
-- keep ensure_installed and the LSP server list to what this machine can build.

-- purl type -> executables Mason's installer for that type spawns. A type that
-- is missing here (github, generic, openvsx) is a plain download and needs no
-- toolchain. The pypi candidates mirror Mason's own lookup order.
local toolchain = {
  cargo = { "cargo" },
  composer = { "composer" },
  gem = { "gem" },
  golang = { "go" },
  luarocks = { "luarocks" },
  npm = { "npm" },
  nuget = { "dotnet" },
  opam = { "opam" },
  pypi = { "python3", "python" },
}

local function has_any(bins)
  for _, bin in ipairs(bins) do
    if vim.fn.executable(bin) == 1 then
      return true
    end
  end
  return false
end

-- Whether Mason could build `name` on this machine. An unknown package passes
-- through so Mason reports it itself. That also covers the registry not being
-- on disk yet, which is the case while nvim-lspconfig's opts run on a fresh
-- install: that first start still logs the server failures once.
local function installable(name)
  local mr = require("mason-registry")
  if not mr.has_package(name) then
    return true
  end
  local purl = mr.get_package(name).spec.source.id
  local bins = toolchain[purl:match("^pkg:([^/]+)/")]
  return bins == nil or has_any(bins)
end

return {
  {
    "mason-org/mason.nvim",
    -- LazyVim's config with the filter inside the refresh callback. Filtering
    -- from an `opts` hook would run too early: mason-registry knows no package
    -- before mason.setup() has registered the registries and refresh() has put
    -- them on disk.
    config = function(_, opts)
      require("mason").setup(opts)
      local mr = require("mason-registry")
      mr:on("package:install:success", function()
        vim.defer_fn(function()
          -- trigger FileType event to possibly load this newly installed LSP server
          require("lazy.core.handler.event").trigger({
            event = "FileType",
            buf = vim.api.nvim_get_current_buf(),
          })
        end, 100)
      end)

      mr.refresh(function()
        for _, tool in ipairs(opts.ensure_installed) do
          if installable(tool) then
            local p = mr.get_package(tool)
            if not p:is_installed() then
              p:install()
            end
          end
        end
      end)
    end,
  },
  {
    "neovim/nvim-lspconfig",
    opts = function(_, opts)
      -- LazyVim puts every server with `mason ~= false` into mason-lspconfig's
      -- ensure_installed; `enabled = false` takes it out of that and out of
      -- vim.lsp.enable(). A server that cannot be built cannot run either, so
      -- disabling it is the honest state.
      local to_package = require("mason-lspconfig.mappings").get_mason_map().lspconfig_to_package
      for server, sopts in pairs(opts.servers) do
        if type(sopts) == "table" and sopts.mason ~= false and sopts.enabled ~= false then
          local pkg = to_package[server]
          if pkg and not installable(pkg) then
            sopts.enabled = false
          end
        end
      end
    end,
  },
}
