return {
  "saghen/blink.cmp",
  opts = {
    sources = {
      -- Prose: no word completion from the buffer and no snippets popping up
      -- mid-sentence. Paths still complete for links, LSP if a server attaches.
      per_filetype = {
        markdown = { "lsp", "path" },
        text = { "lsp", "path" },
        gitcommit = { "lsp", "path" },
      },
    },
  },
}
