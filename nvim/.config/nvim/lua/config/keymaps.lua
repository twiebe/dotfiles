-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- Window switching with <leader> + left/right, mirroring <C-w> h/l. LazyVim
-- already proxies <leader>w to <C-w>; these drop the w. Note <C-arrow> stays
-- bound to resizing splits, not moving between them.
vim.keymap.set("n", "<leader><Left>", "<C-w>h", { desc = "Go to left window" })
vim.keymap.set("n", "<leader><Right>", "<C-w>l", { desc = "Go to right window" })

-- Buffer switching with <leader> + up/down. This claims the vertical arrows, so
-- windows above and below are reached with <leader>wk and <leader>wj instead.
vim.keymap.set("n", "<leader><Up>", "<cmd>bnext<cr>", { desc = "Next buffer" })
vim.keymap.set("n", "<leader><Down>", "<cmd>bprevious<cr>", { desc = "Prev buffer" })
