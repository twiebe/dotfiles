-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here
vim.opt.clipboard = ""

-- Auto-pairing is off: typing an opening bracket or quote never inserts the
-- closing one. Closing characters are always typed by hand. Toggle per session
-- with <leader>up.
vim.g.minipairs_disable = true
vim.keymap.set({ "n", "x" }, "y", '"+y')
vim.keymap.set({ "n", "x" }, "Y", '"+Y')

-- Root detection: always use the current working directory. LazyVim's default
-- spec walks up from each buffer looking for lsp roots and .git / lua markers,
-- so pickers and the explorer silently jump between roots as you switch
-- buffers. Pinning it to cwd keeps <leader>ff, <leader>/ and the explorer on
-- one directory until it is changed explicitly (for example <leader>fp).
vim.g.root_spec = { "cwd" }
