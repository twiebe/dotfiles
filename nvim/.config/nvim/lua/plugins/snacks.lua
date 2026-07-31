return {
  "folke/snacks.nvim",
  opts = {
    picker = {
      sources = {
        explorer = {
          hidden = true, -- .dotfiles
          ignored = true, -- optional: auch gitignored
        },
      },
    },
  },
}
