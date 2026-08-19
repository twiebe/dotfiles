-- displayplacer lives in the system-wide or in the per-user homebrew prefix,
-- depending on the machine.
local displayplacerPaths = {
	"/opt/homebrew/bin/displayplacer",
	os.getenv("HOME") .. "/.Homebrew/bin/displayplacer",
}

local function displayplacerPath()
	for _, path in ipairs(displayplacerPaths) do
		if hs.fs.attributes(path, "mode") == "file" then
			return path
		end
	end
	return nil
end

local builtinPattern = "Built%-in"
local builtinArgs = "res:1512x982 hz:120 color_depth:8 enabled:true scaling:on origin:(-1512,787) degree:0"

-- Known external displays, matched against hs.screen:name(). Persistent screen
-- ids are not stable: they differ between machines and change when the display
-- moves to another port, so the ids are resolved at runtime instead.
local externals = {
	{ match = "PL3271Q", args = "res:2560x1440 hz:144 color_depth:8 enabled:true scaling:on origin:(0,0) degree:0" },
}

local function argsForScreen(screen)
	local name = screen:name() or ""
	if name:match(builtinPattern) then
		return builtinArgs, "builtin"
	end
	for _, external in ipairs(externals) do
		if name:match(external.match) then
			return external.args, "external"
		end
	end
	return nil, "unknown"
end

function setDisplayResolution()
	local args = {}
	local counts = { builtin = 0, external = 0, unknown = 0 }

	for _, screen in ipairs(hs.screen.allScreens()) do
		local spec, kind = argsForScreen(screen)
		counts[kind] = counts[kind] + 1
		if spec then
			table.insert(args, "id:" .. screen:getUUID() .. " " .. spec)
		end
	end

	-- Only act on a setup of exactly one known external plus the built-in
	-- screen. displayplacer leaves unlisted screens where they are, so placing
	-- only some of the screens would overlap origins.
	if counts.builtin ~= 1 or counts.external ~= 1 or counts.unknown > 0 then
		return
	end

	local binary = displayplacerPath()
	if not binary then
		hs.printf("setDisplayResolution: displayplacer not found")
		return
	end

	hs.task.new(binary, nil, args):start()
end

screenWatcher = hs.screen.watcher.new(function()
	hs.timer.doAfter(30, setDisplayResolution)
end)
screenWatcher:start()

setDisplayResolution()
