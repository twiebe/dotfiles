return {
  {
    "folke/flash.nvim",
    keys = {
      -- Give `s` back to builtin substitute (delete char, enter INSERT).
      { "s", mode = { "n", "x", "o" }, false },
      -- Flash jump moves to `gs`. Note: mini.surround owns the `gs` prefix
      -- (gsa/gsd/gsr), so this fires only after 'timeoutlen'.
      {
        "gs",
        mode = { "n", "x", "o" },
        function()
          require("flash").jump()
        end,
        desc = "Flash",
      },
    },
  },
}
