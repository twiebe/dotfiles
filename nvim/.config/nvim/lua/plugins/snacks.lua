return {
  "folke/snacks.nvim",
  opts = {
    -- Smooth scrolling only. Other snacks animations (indent guides, dim,
    -- notifier) keep animating.
    scroll = { enabled = false },
    picker = {
      sources = {
        explorer = { hidden = true, ignored = true },
        files = { hidden = true, ignored = true },
        smart = { hidden = true, ignored = true },
        grep = { hidden = true, ignored = true },
      },
    },
  },
}
