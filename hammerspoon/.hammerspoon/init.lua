function setDisplayResolution()
  -- hs.task.new("/opt/homebrew/bin/displayplacer", nil, {"id:C13ABD25-946F-4274-94B4-599AD4D7002D mode:111"})
  -- hs.task.new("/opt/homebrew/bin/displayplacer", nil, {"id:EB76FF6B-7A22-453F-BDB2-F42DAF5D0A0A mode:35 degree:270"})
  hs.task.new("/opt/homebrew/bin/displayplacer", nil, {"id:E25C731D-8F86-4677-8141-6EE499B49CF4 res:2560x1440 hz:144 color_depth:8 enabled:true scaling:on origin:(0,0) degree:0", "id:37D8832A-2D66-02CA-B9F7-8F30A301B230 res:1512x982 hz:120 color_depth:8 enabled:true scaling:on origin:(-1512,787) degree:0", "id:0A9A88B1-2DFE-4B4A-B914-A622CE11C99B res:1152x2048 hz:60 color_depth:8 enabled:true scaling:on origin:(2560,-367) degree:270"})
end

screenWatcher = hs.screen.watcher.new(function()
  hs.timer.doAfter(30, setDisplayResolution)
end)
screenWatcher:start()

setDisplayResolution()