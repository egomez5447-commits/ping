# EGG RUSH - an egg-hatching pet tycoon for Fortnite Creative (UEFN / Verse).
#
# Loop: run on the treadmill for Steps -> spend Steps/money on upgrades -> Reach unlocks zones
#       -> grab an egg in a zone (press the egg button) -> carry it home -> place it on your plot
#       -> it hatches into a pet -> your best 7 pets pay money every second -> Rebirth for a multiplier.
#
# Everything is wired up through @editable fields on ONE device (egg_rush_game). See SETUP.md.

using { /Fortnite.com/Devices }
using { /Fortnite.com/Characters }
using { /Fortnite.com/UI }
using { /Verse.org/Simulation }
using { /Verse.org/Random }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /UnrealEngine.com/Temporary/SpatialMath }
using { /UnrealEngine.com/Temporary/UI }

Msg<localizes>(S:string):message = "{S}"

# ---------------------------------------------------------------- static data
# 4 zones x 6 pets. Pet id = ZoneIndex * 6 + RarityTier.
ZoneNames<public>:[]string = array{"Meadow", "Forest", "Desert", "Volcano"}
RarityNames<public>:[]string = array{"Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythical"}
PetNames<public>:[][]string = array{
    array{"Chicken", "Pig", "Sheep", "Cow", "Horse", "Unicorn"},
    array{"Rabbit", "Fox", "Deer", "Wolf", "Bear", "Dire Wolf"},
    array{"Lizard", "Camel", "Scorpion", "Cobra", "Sphinx", "Sand Dragon"},
    array{"Imp", "Lava Slug", "Fire Fox", "Magma Golem", "Phoenix", "Inferno Drake"}}
RarityIncome<public>:[]int = array{1, 3, 10, 40, 200, 1000}     # $/s at zone multiplier 1
ZoneIncomeMult<public>:[]int = array{1, 10, 120, 1500}
RarityWeights<public>:[]int = array{600, 250, 100, 40, 9, 1}    # out of 1000
TotalPets<public>:int = 24
MaxActivePets<public>:int = 7
MaxOwnedPets<public>:int = 60

# Reach upgrades (the three "Buy Reach" rows in the video) - cost in money.
ReachGain<public>:[]int = array{5, 25, 100}
ReachCost<public>:[]int = array{75, 2325, 78640000}

# Cost of buying an egg for each zone straight from the shop.
ShopEggCost<public>:[]int = array{250, 5000, 100000, 2500000}

ZoneOf(PetId:int):int = if (Z := Quotient[PetId, 6]) then Z else 0
TierOf(PetId:int):int = if (T := Mod[PetId, 6]) then T else 0
PetName(PetId:int):string = if (N := PetNames[ZoneOf(PetId)][TierOf(PetId)]) then N else "Pet"
RarityName(PetId:int):string = if (N := RarityNames[TierOf(PetId)]) then N else "Common"
PetIncome(PetId:int):int =
    if (Z := ZoneIncomeMult[ZoneOf(PetId)], R := RarityIncome[TierOf(PetId)]):
        Z * R
    else:
        1

Pad2(F:int):string = if (F < 10) then "0{F}" else "{F}"

# 1234567 -> "1.23M"
Abbrev(N:int):string =
    if (N >= 1000000000, W := Quotient[N, 1000000000], F := Quotient[Mod[N, 1000000000], 10000000]):
        "{W}.{Pad2(F)}B"
    else if (N >= 1000000, W := Quotient[N, 1000000], F := Quotient[Mod[N, 1000000], 10000]):
        "{W}.{Pad2(F)}M"
    else if (N >= 1000, W := Quotient[N, 1000], F := Quotient[Mod[N, 1000], 10]):
        "{W}.{Pad2(F)}K"
    else:
        "{N}"

RollPet(ZoneIdx:int):int =
    Zone := Max(0, Min(ZoneIdx, 3))
    Roll := GetRandomInt(0, 999)
    var Acc:int = 0
    var Tier:int = 0
    var Found:logic = false
    for (I -> W : RarityWeights):
        set Acc += W
        if (not Found?, Roll < Acc):
            set Found = true
            set Tier = I
    Zone * 6 + Tier

# Keeps the pet list sorted best -> worst so the first 7 are the "active" ones.
InsertSorted(Pets:[]int, Id:int):[]int =
    var Result:[]int = array{}
    var Placed:logic = false
    for (P : Pets):
        if (not Placed?, PetIncome(Id) > PetIncome(P)):
            set Result += array{Id}
            set Placed = true
        set Result += array{P}
    if (not Placed?):
        set Result += array{Id}
    Result

# ------------------------------------------------------------- editable data
zone_config<public> := class<concrete>:
    @editable Name : string = "Meadow"
    @editable RequiredReach : int = 50
    # Button at home that sends you to this zone.
    @editable EnterButton : button_device = button_device{}
    # Prop marking where you land in the zone.
    @editable LandingPoint : creative_prop = creative_prop{}
    # Button in the zone that sends you back home.
    @editable ReturnButton : button_device = button_device{}
    # One button per egg spot. Pressing one picks up an egg; it comes back after a delay.
    @editable EggButtons : []button_device = array{}

plot_config<public> := class<concrete>:
    @editable HomePoint : creative_prop = creative_prop{}
    @editable PlaceEggButton : button_device = button_device{}

# ------------------------------------------------------------------ per player
player_hud<public> := class:
    MoneyText : text_block
    StepsText : text_block
    ReachText : text_block
    IncomeText : text_block
    PetsText : text_block
    IndexText : text_block
    RebirthText : text_block
    CarryText : text_block
    HintText : text_block
    ToastText : text_block

player_state<public> := class:
    Hud : player_hud
    var Money : int = 0
    var Steps : int = 0
    var Reach : int = 50
    var TreadLevel : int = 1
    var Rebirths : int = 0
    var Carrying : ?int = false
    var Hatching : logic = false
    var Pets : []int = array{}
    var Discovered : [int]logic = map{}
    var PlotIdx : ?int = false

MakeHud(Player:player):player_hud =
    Hud := player_hud:
        MoneyText := text_block{DefaultText := Msg("$0")}
        StepsText := text_block{DefaultText := Msg("Steps 0")}
        ReachText := text_block{DefaultText := Msg("Reach 50")}
        IncomeText := text_block{DefaultText := Msg("+$0/s")}
        PetsText := text_block{DefaultText := Msg("Pets 0/7")}
        IndexText := text_block{DefaultText := Msg("Index 0/{TotalPets}")}
        RebirthText := text_block{DefaultText := Msg("Rebirth 0")}
        CarryText := text_block{DefaultText := Msg("")}
        HintText := text_block{DefaultText := Msg("Use the treadmill to earn Steps!")}
        ToastText := text_block{DefaultText := Msg("")}
    Panel := stack_box:
        Orientation := orientation.Vertical
        Slots := array:
            stack_box_slot{Widget := Hud.MoneyText}
            stack_box_slot{Widget := Hud.StepsText}
            stack_box_slot{Widget := Hud.ReachText}
            stack_box_slot{Widget := Hud.IncomeText}
            stack_box_slot{Widget := Hud.PetsText}
            stack_box_slot{Widget := Hud.IndexText}
            stack_box_slot{Widget := Hud.RebirthText}
            stack_box_slot{Widget := Hud.CarryText}
    Root := canvas:
        Slots := array:
            canvas_slot:
                Anchors := anchors{Minimum := vector2{X := 0.0, Y := 0.35}, Maximum := vector2{X := 0.0, Y := 0.35}}
                Offsets := margin{Left := 16.0}
                Alignment := vector2{X := 0.0, Y := 0.0}
                SizeToContent := true
                Widget := Panel
            canvas_slot:
                Anchors := anchors{Minimum := vector2{X := 0.5, Y := 0.06}, Maximum := vector2{X := 0.5, Y := 0.06}}
                Alignment := vector2{X := 0.5, Y := 0.0}
                SizeToContent := true
                Widget := Hud.HintText
            canvas_slot:
                Anchors := anchors{Minimum := vector2{X := 0.5, Y := 0.3}, Maximum := vector2{X := 0.5, Y := 0.3}}
                Alignment := vector2{X := 0.5, Y := 0.5}
                SizeToContent := true
                Widget := Hud.ToastText
    if (UI := GetPlayerUI[Player]):
        UI.AddWidget(Root)
    Hud

# ------------------------------------------------------------------ the device
egg_rush_game<public> := class(creative_device):

    @editable Zones : []zone_config = array{}
    @editable Plots : []plot_config = array{}

    # Treadmill: stand in this volume to earn Steps. Steps buy treadmill levels.
    @editable TreadmillVolume : volume_device = volume_device{}
    @editable TreadmillUpgradeButton : button_device = button_device{}

    # Three buttons, in order: +5 Reach, +25 Reach, +100 Reach.
    @editable ReachButtons : []button_device = array{}
    # One button per zone (same order as Zones): buys an egg from that zone.
    @editable ShopEggButtons : []button_device = array{}
    @editable RebirthButton : button_device = button_device{}

    # Fallback teleport target (lobby / spawn).
    @editable LobbyPoint : creative_prop = creative_prop{}

    @editable HatchSeconds : int = 3
    @editable EggRespawnSeconds : float = 15.0
    @editable TreadmillTickSeconds : float = 0.5

    var States : [player]player_state = map{}
    var PlotOwners : [int]player = map{}

    # ---------------------------------------------------------------- startup
    OnBegin<override>()<suspends>:void =
        Playspace := GetPlayspace()
        Playspace.PlayerAddedEvent().Subscribe(OnPlayerAdded)
        Playspace.PlayerRemovedEvent().Subscribe(OnPlayerRemoved)
        for (P : Playspace.GetPlayers()):
            AddPlayer(P)

        TreadmillUpgradeButton.SetInteractionText(Msg("Upgrade Treadmill (Steps)"))
        TreadmillUpgradeButton.InteractedWithEvent.Subscribe(OnUpgradeTreadmill)
        RebirthButton.SetInteractionText(Msg("Rebirth"))
        RebirthButton.InteractedWithEvent.Subscribe(OnRebirth)

        for (RI := 0..ReachButtons.Length - 1, Btn := ReachButtons[RI], Gain := ReachGain[RI], Cost := ReachCost[RI]):
            Btn.SetInteractionText(Msg("Reach +{Gain}  (${Abbrev(Cost)})"))
            OnReach(Agent:agent):void = HandleReach(RI, Agent)
            Btn.InteractedWithEvent.Subscribe(OnReach)

        for (ZI := 0..ShopEggButtons.Length - 1, Btn := ShopEggButtons[ZI]):
            ZName := if (N := ZoneNames[ZI]) then N else "Zone"
            if (Cost := ShopEggCost[ZI]):
                Btn.SetInteractionText(Msg("Buy {ZName} Egg  (${Abbrev(Cost)})"))
            OnShop(Agent:agent):void = HandleShop(ZI, Agent)
            Btn.InteractedWithEvent.Subscribe(OnShop)

        for (PI := 0..Plots.Length - 1, Plot := Plots[PI]):
            Plot.PlaceEggButton.SetInteractionText(Msg("Place Egg"))
            OnPlace(Agent:agent):void = HandlePlace(PI, Agent)
            Plot.PlaceEggButton.InteractedWithEvent.Subscribe(OnPlace)

        for (ZI := 0..Zones.Length - 1, Zone := Zones[ZI]):
            Zone.EnterButton.SetInteractionText(Msg("Go to {Zone.Name} (Reach {Zone.RequiredReach})"))
            OnEnter(Agent:agent):void = HandleEnterZone(ZI, Agent)
            Zone.EnterButton.InteractedWithEvent.Subscribe(OnEnter)
            Zone.ReturnButton.SetInteractionText(Msg("Return Home"))
            OnReturn(Agent:agent):void = HandleReturn(Agent)
            Zone.ReturnButton.InteractedWithEvent.Subscribe(OnReturn)
            for (Egg : Zone.EggButtons):
                Egg.SetInteractionText(Msg("Grab Egg"))
                OnEgg(Agent:agent):void = HandleEgg(ZI, Egg, Agent)
                Egg.InteractedWithEvent.Subscribe(OnEgg)

        spawn{IncomeLoop()}
        spawn{TreadmillLoop()}

    # ---------------------------------------------------------------- players
    OnPlayerAdded(Player:player):void = AddPlayer(Player)

    AddPlayer(Player:player):void =
        if (not States[Player]):
            State := player_state{Hud := MakeHud(Player)}
            set States[Player] = State
            set State.PlotIdx = AssignPlot(Player)
            RefreshHud(State)
            spawn{WelcomeHome(Player, State)}

    WelcomeHome(Player:player, State:player_state)<suspends>:void =
        Sleep(1.5)
        TeleportHome(Player, State)

    OnPlayerRemoved(Player:player):void =
        var Kept:[player]player_state = map{}
        for (P -> S : States, P <> Player):
            set Kept[P] = S
        set States = Kept
        var KeptPlots:[int]player = map{}
        for (I -> P : PlotOwners, P <> Player):
            set KeptPlots[I] = P
        set PlotOwners = KeptPlots

    AssignPlot(Player:player):?int =
        for (I := 0..Plots.Length - 1):
            if (not PlotOwners[I]):
                set PlotOwners[I] = Player
                return option{I}
        false

    TeleportHome(Player:player, State:player_state):void =
        if (Char := Player.GetFortCharacter[]):
            var Target:transform = LobbyPoint.GetTransform()
            if (I := State.PlotIdx?, Plot := Plots[I]):
                set Target = Plot.HomePoint.GetTransform()
            if (Char.TeleportTo[Target.Translation, Target.Rotation]):
                Print("Egg Rush: player sent home")

    # ------------------------------------------------------------------ HUD
    ComputeIncome(State:player_state):int =
        var Sum:int = 0
        for (I -> P : State.Pets, I < MaxActivePets):
            set Sum += PetIncome(P)
        if (M := Quotient[Sum * (100 + 50 * State.Rebirths), 100]):
            M
        else:
            Sum

    RefreshHud(State:player_state):void =
        H := State.Hud
        H.MoneyText.SetText(Msg("$ {Abbrev(State.Money)}"))
        H.StepsText.SetText(Msg("Steps {Abbrev(State.Steps)}  (treadmill lv {State.TreadLevel})"))
        H.ReachText.SetText(Msg("Reach {State.Reach}"))
        H.IncomeText.SetText(Msg("+$ {Abbrev(ComputeIncome(State))}/s"))
        H.PetsText.SetText(Msg("Pets {Min(State.Pets.Length, MaxActivePets)}/{MaxActivePets} active  ({State.Pets.Length} owned)"))
        H.IndexText.SetText(Msg("Index {State.Discovered.Length}/{TotalPets}"))
        H.RebirthText.SetText(Msg("Rebirth {State.Rebirths}  (+{50 * State.Rebirths}% money)  needs {RebirthReach(State.Rebirths)} Reach"))
        if (Egg := State.Carrying?):
            H.CarryText.SetText(Msg("Carrying: {PetName(Egg)} Egg  (${Abbrev(PetIncome(Egg))}/s)"))
        else:
            H.CarryText.SetText(Msg(""))

    ShowHint(State:player_state, Text:string):void =
        State.Hud.HintText.SetText(Msg(Text))

    ShowToast(State:player_state, Text:string):void =
        State.Hud.ToastText.SetText(Msg(Text))
        spawn{ClearToast(State, Text)}

    ClearToast(State:player_state, Text:string)<suspends>:void =
        Sleep(3.0)
        State.Hud.ToastText.SetText(Msg(""))

    # ------------------------------------------------------------------ loops
    IncomeLoop()<suspends>:void =
        loop:
            Sleep(1.0)
            for (Player -> State : States):
                set State.Money += ComputeIncome(State)
                RefreshHud(State)

    TreadmillLoop()<suspends>:void =
        loop:
            Sleep(TreadmillTickSeconds)
            for (Agent : TreadmillVolume.GetAgentsInVolume()):
                if (Player := player[Agent], State := States[Player]):
                    set State.Steps += 2 * State.TreadLevel
                    RefreshHud(State)

    # --------------------------------------------------------------- handlers
    TreadCost(State:player_state):int = 100 * State.TreadLevel * State.TreadLevel

    OnUpgradeTreadmill(Agent:agent):void =
        if (Player := player[Agent], State := States[Player]):
            Cost := TreadCost(State)
            if (State.Steps >= Cost):
                set State.Steps -= Cost
                set State.TreadLevel += 1
                ShowToast(State, "Treadmill level {State.TreadLevel}!  +{2 * State.TreadLevel} Steps per tick")
            else:
                ShowHint(State, "Need {Abbrev(Cost)} Steps to upgrade the treadmill")
            RefreshHud(State)

    HandleReach(Index:int, Agent:agent):void =
        if (Player := player[Agent], State := States[Player], Cost := ReachCost[Index], Gain := ReachGain[Index]):
            if (State.Money >= Cost):
                set State.Money -= Cost
                set State.Reach += Gain
                ShowToast(State, "Reach is now {State.Reach}")
            else:
                ShowHint(State, "Need $ {Abbrev(Cost)} for +{Gain} Reach")
            RefreshHud(State)

    HandleEnterZone(ZI:int, Agent:agent):void =
        if (Player := player[Agent], State := States[Player], Zone := Zones[ZI]):
            if (State.Reach < Zone.RequiredReach):
                ShowHint(State, "{Zone.Name} needs {Zone.RequiredReach} Reach (you have {State.Reach})")
            else if (Char := Player.GetFortCharacter[]):
                Land := Zone.LandingPoint.GetTransform()
                if (Char.TeleportTo[Land.Translation, Land.Rotation]):
                    ShowHint(State, "Grab an egg!")

    HandleReturn(Agent:agent):void =
        if (Player := player[Agent], State := States[Player]):
            TeleportHome(Player, State)
            if (State.Carrying?):
                ShowHint(State, "Place your egg on your plot!")
            else:
                ShowHint(State, "Get more eggs!")

    HandleEgg(ZI:int, Egg:button_device, Agent:agent):void =
        if (Player := player[Agent], State := States[Player], Zone := Zones[ZI]):
            if (State.Reach < Zone.RequiredReach):
                ShowHint(State, "{Zone.Name} needs {Zone.RequiredReach} Reach")
            else if (State.Carrying?):
                ShowHint(State, "You're already carrying an egg - take it home!")
            else:
                PetId := RollPet(ZI)
                set State.Carrying = option{PetId}
                Egg.Disable()
                spawn{RespawnEgg(Egg)}
                ShowHint(State, "Got a {PetName(PetId)} Egg! Return home and place it.")
                RefreshHud(State)

    RespawnEgg(Egg:button_device)<suspends>:void =
        Sleep(EggRespawnSeconds)
        Egg.Enable()

    HandleShop(ZI:int, Agent:agent):void =
        if (Player := player[Agent], State := States[Player], Zone := Zones[ZI], Cost := ShopEggCost[ZI]):
            if (State.Reach < Zone.RequiredReach):
                ShowHint(State, "{Zone.Name} eggs need {Zone.RequiredReach} Reach")
            else if (State.Carrying?):
                ShowHint(State, "You're already carrying an egg - place it first!")
            else if (State.Money < Cost):
                ShowHint(State, "Need $ {Abbrev(Cost)}")
            else:
                set State.Money -= Cost
                PetId := RollPet(ZI)
                set State.Carrying = option{PetId}
                ShowHint(State, "Bought a {PetName(PetId)} Egg! Place it on your plot.")
                RefreshHud(State)

    HandlePlace(PlotIndex:int, Agent:agent):void =
        if (Player := player[Agent], State := States[Player]):
            if (Mine := State.PlotIdx?, Mine = PlotIndex):
                if (State.Hatching?):
                    ShowHint(State, "Your egg is still hatching...")
                else if (PetId := State.Carrying?):
                    set State.Hatching = true
                    set State.Carrying = false
                    RefreshHud(State)
                    spawn{HatchEgg(State, PetId)}
                else:
                    ShowHint(State, "Grab an egg from a zone first!")
            else:
                ShowHint(State, "That isn't your plot!")

    HatchEgg(State:player_state, PetId:int)<suspends>:void =
        var T:int = HatchSeconds
        loop:
            if (T <= 0):
                break
            ShowHint(State, "Egg hatching... {T}")
            Sleep(1.0)
            set T -= 1
        set State.Pets = InsertSorted(State.Pets, PetId)
        if (State.Pets.Length > MaxOwnedPets, Last := State.Pets.RemoveElement[State.Pets.Length - 1]):
            set State.Pets = Last
        set State.Discovered[PetId] = true
        set State.Hatching = false
        ShowToast(State, "{PetName(PetId)}!  {RarityName(PetId)}  +${Abbrev(PetIncome(PetId))}/s")
        ShowHint(State, "Get more eggs!")
        RefreshHud(State)

    RebirthReach(Rebirths:int):int = 150 + 100 * Rebirths

    OnRebirth(Agent:agent):void =
        if (Player := player[Agent], State := States[Player]):
            Need := RebirthReach(State.Rebirths)
            if (State.Reach >= Need):
                set State.Rebirths += 1
                set State.Reach = 50
                set State.Steps = 0
                set State.TreadLevel = 1
                ShowToast(State, "REBIRTH {State.Rebirths}!  Money now {100 + 50 * State.Rebirths}%")
                TeleportHome(Player, State)
            else:
                ShowHint(State, "Rebirth needs {Need} Reach (you have {State.Reach})")
            RefreshHud(State)
