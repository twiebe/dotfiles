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
  keys = {
    -- Resume the last search, not the last picker. Snacks records resume state
    -- for every picker it closes, and the LSP pickers behind gd and gr count:
    -- they auto-confirm a single result and close themselves, so a goto
    -- definition silently becomes the most recent picker. Plain
    -- Snacks.picker.resume() then replays that cached definition list instead
    -- of the grep. Skipping the lsp_* sources and the file explorer keeps
    -- <leader>sR on the last grep or file search.
    {
      "<leader>sR",
      function()
        local skip = { "^lsp_", "^explorer$" }
        local include = {}
        for source in pairs(require("snacks.picker.resume").state) do
          local wanted = true
          for _, pattern in ipairs(skip) do
            if source:find(pattern) then
              wanted = false
              break
            end
          end
          if wanted then
            include[#include + 1] = source
          end
        end
        if #include == 0 then
          return Snacks.notify.warn("No search picker to resume")
        end
        Snacks.picker.resume({ include = include })
      end,
      desc = "Resume (last search)",
    },
  },
}
