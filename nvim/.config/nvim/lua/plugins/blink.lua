-- Filetypes where completion should stay out of the way while writing prose.
local prose = {
  -- A scratch buffer (dashboard "New File", `nvim` with no argument) has no
  -- filetype at all. Treat that as prose too: without a filetype there is no
  -- LSP and no syntax context, so snippets and buffer words are only noise.
  [""] = true,
  markdown = true,
  text = true,
  gitcommit = true,
  plaintex = true,
  typst = true,
}

local function not_prose()
  return not prose[vim.bo.filetype]
end

return {
  "saghen/blink.cmp",
  opts = {
    sources = {
      -- Prose: no word completion from the buffer and no snippets popping up
      -- mid-sentence. Paths still complete for links, LSP if a server attaches.
      per_filetype = {
        [""] = { "lsp", "path" },
        markdown = { "lsp", "path" },
        text = { "lsp", "path" },
        gitcommit = { "lsp", "path" },
        plaintex = { "lsp", "path" },
        typst = { "lsp", "path" },
      },
      providers = {
        -- per_filetype alone does not stop these: blink defaults both `lsp` and
        -- `path` to `fallbacks = { "buffer" }`, so buffer words still show up
        -- whenever those return nothing, which is the normal case in prose.
        -- Disabling the providers themselves is what actually silences them.
        buffer = { enabled = not_prose },
        snippets = { enabled = not_prose },
      },
    },
  },
}
