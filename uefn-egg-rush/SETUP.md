# Egg Rush - UEFN / Verse setup

`egg_rush.verse` is a Fortnite Creative version of the egg-hatching pet tycoon from the video.
**It has not been compiled.** UEFN isn't available where this was written, so expect to fix a
line or two of Verse API drift when you first build (Verse > Build Verse Code shows the errors).

## What the video showed, and what this implements

| In the video | In this kit |
|---|---|
| Treadmill, "+2/step", Steps counter | `TreadmillVolume`: standing in it earns Steps every tick; `TreadmillUpgradeButton` spends Steps to raise treadmill level |
| Reach upgrades (50 -> 55 / 75 / 150 for $75 / $2,325 / $78.64M) | `ReachButtons` (3 buttons: +5, +25, +100 Reach, same prices) |
| Zones (Meadow...) you travel to | `Zones[]`: enter button, landing prop, return button, egg buttons. Reach gates each zone |
| "Grab the egg!" (E to pick up), "Return" | Egg buttons pick up an egg (the pet is rolled then, so the HUD shows "Chicken Egg $1/s"); the zone's return button teleports home |
| "Place your egg!" on a plot/belt, egg hatches in ~3s | `Plots[]`: each player is assigned a plot; `PlaceEggButton` starts a 3s hatch |
| Hatch popup "CHICKEN - Common - $1/s" | Toast in the middle of the screen |
| Pets earn $/s, "0/7 Active" | Best 7 pets pay every second; up to 60 owned |
| Index "1/81" | Counter of discovered pets (24 pets in the kit) |
| Shop with eggs | `ShopEggButtons[]`: buy a zone's egg with money |
| Rebirth (Reach 150 -> resets Speed/Reach, 1x -> 1.5x money) | `RebirthButton` |

## Not in the kit (guesses and extras)

- **Swinging home, the RUN! timer and "Safe Zone"**: I couldn't tell exactly how these work from a screen recording. Travel is teleport-based here.
- **Trails, daily rewards, gifts, friend boost, Robux prices, Sell All**: not implemented. Trails would be a per-player speed multiplier, so start with a `movement_modulator_device`.
- **Saving progress**: state lives in memory. To keep it between sessions, move the fields of `player_state` into a `<persistable>` class kept in a `weak_map(player, ...)`.
- **A full Index screen**: only the counter exists. Build a scrolling panel from `player_state.Discovered`.
- Pet numbers (4 zones x 6 rarities, income and prices) are my own placeholders. Tune the tables at the top of the file.

## Setting it up in UEFN

1. Create a **Verse device**: Verse menu > Verse Explorer > right-click your project > *Add new Verse file to project*, name it `egg_rush`, and paste in `egg_rush.verse`. Click **Build Verse Code**.
2. Drag **egg_rush_game** from the Content Browser into the level. Put player spawn pads near your plot(s).
3. Build the world with props and any devices you like. You need these placed devices:
   - **Volume device** for the treadmill floor -> `TreadmillVolume`
   - **Button devices** -> treadmill upgrade, 3 Reach buttons, 1 shop button per zone, rebirth, 1 "place egg" button per plot, and per zone: enter, return and several egg buttons
   - **Creative props** used only as teleport markers -> `LobbyPoint`, each plot's `HomePoint`, each zone's `LandingPoint` (any prop works; set it invisible or hide it inside scenery)
4. Select the `egg_rush_game` device and fill in its Details panel:
   - `Zones`: add up to **4** entries (the pet tables have 4 zones). Order matters: 0 Meadow, 1 Forest, 2 Desert, 3 Volcano. Set `RequiredReach` (suggested 50 / 100 / 250 / 600) and assign the buttons and landing prop.
   - `Plots`: one entry per player slot (the island holds as many players as it has plots).
   - `ShopEggButtons`: same order as the zones.
5. On every button device, set **Interaction Time** to about 0.3s and turn on *Interact Text*, since Verse only overwrites the text. Set egg buttons to *Enabled at game start*.
6. In **Island Settings**, set the max players to match your plots, then **Launch Session** to test.

## If the build complains

The likeliest spots, since the Verse UI and device APIs change often:
- `volume_device.GetAgentsInVolume()` -> if missing, subscribe to `AgentEntersEvent` / `AgentExitsEvent` and keep your own list.
- `text_block` / `canvas` / `stack_box` slot fields in `MakeHud` -> compare with a working sample in the Epic docs ("Creating In-Game UI with Verse").
- `fort_character.TeleportTo[...]` -> if the signature differs, use a `teleporter_device` per marker and call `Teleport(agent)`.
