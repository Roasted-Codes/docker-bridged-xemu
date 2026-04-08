"""
Halo 2 v1.5 XBE Linker Map Symbol Index
========================================

Parsed from: halo v1.5.xbe.orig.map
Module:      halo2ship.exe
Base:        0x000118E0
Entry point: 0x002C89DE (section .text)

Addresses in this file are FLAT VIRTUAL ADDRESSES as they appear in the
linker map. These can be used directly with XBDM getmem2 reads (for
addresses in committed VA ranges — see XBDM_ACCESSIBLE below).

Section layout:
    .text   (CODE)  0x371D2C bytes   Sections 0001-0017
    .rdata  (DATA)  0x0520CC bytes   Section 0018
    .data   (DATA)  0x106178 bytes   Section 0019
    DOLBY           0x007180 bytes   Section 001A
    BINK*           Various          Sections 0006-0015
    D3D     (CODE)  0x013464 bytes   Section 0016
    XPP     (CODE)  0x008E5C bytes   Section 0017
    XONLINE (CODE)  0x02C9B4 bytes   Section 0004
    XNET    (CODE)  0x013418 bytes   Section 0005

NOTE: All addresses assume XBE is loaded at its default base. The map file
uses format "section:VA" where VA is the flat virtual address.
"""

# =============================================================================
# SECTION VA RANGES (approximate, from symbol boundaries)
# =============================================================================

SECTIONS = {
    ".text":   {"start": 0x00012078, "end": 0x003A3600, "size": 0x371D2C, "type": "CODE"},
    ".rdata":  {"start": 0x0041B610, "end": 0x0046D2EC, "size": 0x0520CC, "type": "DATA"},
    ".data":   {"start": 0x0046DDD0, "end": 0x00573850, "size": 0x106178, "type": "DATA"},
    "DSOUND":  {"size": 0x00D724, "type": "CODE"},
    "WMADEC":  {"size": 0x01927C, "type": "CODE"},
    "XONLINE": {"size": 0x02C9B4, "type": "CODE"},
    "XNET":    {"size": 0x013418, "type": "CODE"},
    "D3D":     {"size": 0x013464, "type": "CODE"},
    "XPP":     {"size": 0x008E5C, "type": "CODE"},
}

MODULE_BASE = 0x000118E0
ENTRY_POINT = 0x002C89DE  # start() function

# .data section (runtime globals live here — XBDM-accessible)
DATA_SECTION_START = 0x0046D6E0  # from modsections
DATA_SECTION_SIZE  = 0x00106178  # ~1.02 MB


# =============================================================================
# KNOWN XBDM-ACCESSIBLE ADDRESSES (cross-ref with CLAUDE.md)
# =============================================================================

XBDM_ACCESSIBLE = {
    # Primary data source (POPULATED on docker-bridged-xemu)
    0x56B900: "PGCR_DISPLAY_BASE",     # 0x90 header + 16 players + 8 teams
    0x56B984: "PGCR_GAMETYPE",         # int32 in PGCR header (+0x84)
    0x56B990: "PGCR_PLAYER_0",         # First player = base + 0x90
    0x56CAD0: "PGCR_TEAM_0",           # First team = player_0 + 16 * 0x114

    # Fallback data source (EMPTY on docker-bridged-xemu)
    0x55CAF0: "PCR_BASE",              # Post-completion results
    0x55DC30: "PCR_TEAM_0",            # Team data after PCR players

    # Other known addresses
    0x50224C: "GAMETYPE_XBOX7887",     # Reads as zero on docker-bridged-xemu
    0x23975C: "PGCR_CLEAR_BREAKPOINT", # Code addr: fires at game end
}


# =============================================================================
# GAME ENGINE — MULTIPLAYER STATE MACHINE
# =============================================================================
# Source: .rdata debug strings (section 0018)
# These reveal the game's internal state names and transitions.

GAME_STATES = {
    # Network session lifecycle (0x0045C760 - 0x0045C7B8)
    0x0045C7B8: "PreGame",
    0x0045C7AC: "StartMatch",
    0x0045C7A0: "StartGame",
    0x0045C794: "InMatch",
    0x0045C78C: "InGame",
    0x0045C780: "PostGame",
    0x0045C76C: "Matchmaking",
    0x0045C760: "PostMatch",
    0x0045C778: "Joining",
}

# Game engine subsystem debug assertions (0x0045D850 - 0x0045D950)
GAME_ENGINE_SUBSYSTEMS = {
    0x0045D950: "GameEngineStatborg",       # aGameEngineStat — stats tracking
    0x0045D92C: "StatborgCreation",         # aStatborgCreati
    0x0045D900: "StatborgUpdate",           # aStatborgUpdate
    0x0045D8E8: "PlayerUpdateExists",       # aPlayerUpdateEx
    0x0045D8D4: "TeamUpdateExists",         # aTeamUpdateExis
    0x0045D850: "GameEnginePlayer",         # aGameEnginePlay
    0x0045D82C: "PlayerCreation",           # aPlayerCreation
    0x0045D800: "PlayerUpdateRelease",      # aPlayerUpdateRe
}


# =============================================================================
# GAME ENGINE — GAMETYPE ENGINES
# =============================================================================
# Debug assertion strings that name each gametype engine's update/global funcs.
# These confirm the engine architecture for each gametype.

GAMETYPE_ENGINE_STRINGS = {
    # Slayer (0x0045D1CC)
    0x0045D1CC: "SlayerUpdateSRelease",     # aSlayerUpdateSR
    0x0045D1FC: "SlayerEngineGlobal",       # aSlayerEngineGl

    # CTF (0x0045D304)
    0x0045D304: "CtfUpdateSRelease",        # aCtfUpdateSRele
    0x0045D330: "CtfEngineGlobal",          # aCtfEngineGloba
    0x0045D2A0: "FlagWeaponFlag",           # flag object strings
    0x0045D2B4: "FlagArmingTime",
    0x0045D2C8: "FlagResetTimer",
    0x0045D2DC: "FlagSwapTimer",
    0x0045D2EC: "DefensiveTeamExists",      # aDefensiveTeamE

    # Oddball (0x0045D3B4)
    0x0045D3B4: "OddballUpdateSRelease",    # aOddballUpdateS
    0x0045D3E4: "OddballEngineGlobal",      # aOddballEngineG

    # King of the Hill (0x0045D494)
    0x0045D494: "KingUpdateSRelease",       # aKingUpdateSRel
    0x0045D4C0: "KingEngineGlobal",         # aKingEngineGlob
    0x0045D46C: "PlayersInHillExists",      # aPlayersInHillE
    0x0045D484: "HillIdExists",             # aHillIdExists

    # Territories (0x0045D580)
    0x0045D580: "TerritoriesUpdate",        # aTerritoriesUpd
    0x0045D5B4: "TerritoriesEngineGlobal",  # aTerritoriesEng
    0x0045D544: "TerritoryPlayer",          # aTerritoryPlaye
    0x0045D55C: "TerritoryControl",         # aTerritoryContr

    # Juggernaut (0x0045D658)
    0x0045D658: "JuggernautUpdate",         # aJuggernautUpda
    0x0045D68C: "JuggernautEngineGlobal",   # aJuggernautEngi
    0x0045D63C: "JuggernautBitvector",      # aJuggernautBitv
}


# =============================================================================
# GAME ENGINE — GLOBAL STATE FIELDS
# =============================================================================
# From assertion strings: fields in the game engine's global state struct.

GAME_ENGINE_GLOBALS = {
    0x0045ECE4: "GameEngineGlobal",         # aGameEngineGlob (the struct itself)
    0x0045ECD4: "CurrentState",             # aCurrentState
    0x0045ECC4: "GameFinished",             # aGameFinished
    0x0045ECB4: "CurrentRound",             # aCurrentRound
    0x0045ECA4: "RoundTimer",              # aRoundTimer
    0x0045EC90: "TeamMappingExists",        # aTeamMappingExi
    0x0045EC78: "CurrentStateExists",       # aCurrentStateEx
    0x0045EC60: "GameFinishedExists",       # aGameFinishedEx
    0x0045EC48: "CurrentRoundExists",       # aCurrentRoundEx
    0x0045EC34: "RoundTimerExists",         # aRoundTimerExis
}


# =============================================================================
# MULTIPLAYER SCORING — STAT FIELD NAMES
# =============================================================================
# These strings name individual stat fields, confirming the pcr_stat_player
# struct layout used in halo2_structs.py.

STAT_FIELD_STRINGS = {
    # Core damage stats (0x00460184 - 0x004601BC)
    0x004603B8: "Kills",
    0x004603A8: "Deaths",
    0x004603B0: "Assists",
    0x00460390: "Suicides",
    0x0046039C: "Betrayals",
    0x0046036C: "SecondsAlive",
    0x0046037C: "MostKillsInARow",          # aMostKillsInARo (Best Spree)

    # Per-gametype stats
    0x00460184: "DamageKills",
    0x00460174: "DamageDeaths",
    0x00460160: "DamageBetrayals",          # aDamageBetrayal
    0x00460150: "DamageSuicides",
    0x0046013C: "DamageShotsFired",         # aDamageShotsFir
    0x00460128: "DamageShotsHit",
    0x00460114: "DamageHeadshots",          # aDamageHeadshot

    # Player-vs-player matrix
    0x004600FC: "PlayerVsPlayer",           # aPlayerVsPlayer (killed array[16])
    0x004600E4: "PlayerVsPlayer_display",   # aPlayerVsPlayer_0

    # Lifetime/aggregate stats
    0x00460414: "GamesPlayed",
    0x00460408: "GamesQuit",
    0x004603F4: "GamesDisconnected",        # aGamesDisconnec
    0x004603E4: "GamesCompleted",
    0x004603D8: "GamesWon",
    0x004603CC: "GamesTied",
    0x004603C0: "RoundsWon",
}


# =============================================================================
# MULTIPLAYER SCORING — GAMETYPE-SPECIFIC STAT NAMES
# =============================================================================
# These map directly to the value0/value1 union in pcr_stat_player (0x10C/0x110).

GAMETYPE_STAT_STRINGS = {
    # CTF — flag stats
    0x0046035C: "CtfFlagScores",
    0x0046034C: "CtfFlagGrabs",
    0x00460334: "CtfFlagCarrierKills",      # aCtfFlagCarrier_0
    0x00460320: "CtfFlagReturns",

    # CTF — bomb stats (Assault uses CTF engine)
    0x00460310: "CtfBombScores",
    0x00460300: "CtfBombPlants",
    0x004602E8: "CtfBombCarrierKills",      # aCtfBombCarrier_0
    0x004602D8: "CtfBombGrabs",
    0x004602C4: "CtfBombReturns",

    # Oddball
    0x004602AC: "OddballTimeWithBall",      # aOddballTimeWit
    0x0046029C: "OddballUnused",
    0x00460280: "OddballKillsAsCarrier",    # aOddballKillsAs
    0x00460264: "OddballBallCarrierKills",  # aOddballBallCar

    # King of the Hill
    0x00460250: "KingTimeOnHill",
    0x00460238: "KingTotalControlTime",     # aKingTotalContr
    0x0046022C: "KingUnused",

    # Juggernaut
    0x00460210: "JuggernautKillsAsJuggernaut",  # aJuggernautKill_0
    0x004601F0: "JuggernautKills",              # aJuggernautKill
    0x004601D0: "JuggernautTotalControlTime",   # aJuggernautTota
    0x004601BC: "JuggernautUnused",

    # Territories
    0x004601A8: "TerritoriesTaken",         # aTerritoriesTak
    0x00460194: "TerritoriesLost",          # aTerritoriesLos
}


# =============================================================================
# MEDAL NAMES (debug strings)
# =============================================================================
# Medal debug assertion strings. These confirm the medal bitmask layout
# documented in halo2_structs.py.

MEDAL_STRINGS = {
    # Multi-kills (bits 0-5)
    0x004600CC: "MedalMultipleKill_double",     # aMedealMultiple
    0x004600B4: "MedalMultipleKill_triple",     # aMedealMultiple_4
    0x0046009C: "MedalMultipleKill_overkill",   # aMedealMultiple_3
    0x00460084: "MedalMultipleKill_killtacular", # aMedealMultiple_2
    0x0046006C: "MedalMultipleKill_killtrocity", # aMedealMultiple_1
    0x0046004C: "MedalMultipleKill_killimanjaro", # aMedealMultiple_0  (Killimanjaro)

    # Style kills (bits 6-12)
    0x00460038: "MedalSniperKill",
    0x00460020: "MedalCollisionKill",       # Splatter
    0x0046000C: "MedalBashKill",            # Beat Down
    0x0045FFF8: "MedalStealthKill",         # Assassination
    0x0045FFE0: "MedalKilledVehicle",       # Vehicle Destroy
    0x0045FFC8: "MedalBoardedVehicle",      # Carjack / Hijack
    0x0045FFB0: "MedalGrenadeStick",        # Stick

    # Sprees (bits 13-17)
    0x0045FF98: "Medal5KillsInARow",        # Killing Spree
    0x0045FF7C: "Medal10KillsInARow",       # Killing Frenzy
    0x0045FF60: "Medal15KillsInARow",       # Running Riot
    0x0045FF44: "Medal20KillsInARow",       # Rampage
    0x0045FF28: "Medal25KillsInARow",       # Untouchable

    # CTF medals (bits 18-20)
    0x0045FF18: "CtfFlagGrab",
    0x0045FF00: "CtfFlagCarrierKill",
    0x0045FEEC: "CtfFlagReturned",

    # Assault medals (bits 21-23)
    0x0045FED8: "CtfBombPlanted",           # note: "Ctf" prefix in engine, but it's Assault
    0x0045FEC0: "CtfBombCarrierKill",
    0x0045FEAC: "CtfBombDefused",
}


# =============================================================================
# GAMETYPE VARIANT NAMES (UI strings)
# =============================================================================
# String table entries for game variant display names.

GAMETYPE_NAMES = {
    # Base gametypes (0x00463224 - 0x004631FC)
    0x00463224: "Slayer",
    0x0046320C: "Oddball",
    0x00463204: "CTF",                      # (inferred, aCtf)
    0x004631FC: "Assault",
    0x00462FB8: "Juggernaut",               # aJuggernaut_0 (localized?)
    0x004630F0: "KingOfTheHill",
    0x00462EB8: "CaptureTheFlag",           # aCaptureTheFlag (full name)
    0x0046316C: "Slayer",                   # aSlayer_0 (localized?)
}

# Named game variants (predefined multiplayer modes)
GAME_VARIANTS = {
    0x0046293C: "SlayerDuel",
    0x00462920: "RumbleSlayer",
    0x00462908: "TeamSlayer",
    0x004628CC: "TeamRockets",
    0x00462814: "MultiFlagCTF",
    0x004627FC: "ClassicCTF",
    0x004627E4: "ShotgunCTF",
    0x004627CC: "1FlagCTF",
    0x004627AC: "1FlagCTFFast",             # a1FlagCtfFast
    0x00462794: "MultiBomb",
    0x00462784: "Assault",                  # aAssault_0
    0x00462768: "RapidAssault",
    0x0046274C: "MajorAssault",
    0x00462730: "MinorAssault",
    0x00462718: "CrazyKing",
    0x004626F8: "TeamCrazyKing",
    0x004626E8: "Oddball",                  # aOddball_0
    0x004626D4: "Teamball",
    0x00462558: "Juggernaut",
}


# =============================================================================
# WEAPON NAMES (UI strings)
# =============================================================================

WEAPON_NAMES = {
    0x004644B4: "BattleRifle",              # aBattleRifle
    0x0046448C: "Bomb",                     # aBomb
    0x00464474: "BruteShot",
    0x00464464: "Carbine",
    0x00464458: "Flag",
    0x00464440: "FlakCannon",               # Brute Shot alt?
    0x00464424: "Flamethrower",
    0x00464410: "FuelRod",
    0x00464400: "Magnum",
    0x004643F0: "Needler",
    0x004643E0: "Oddball",                  # aOddball_1 — oddball as "weapon"
    0x004643C4: "PlasmaPistol",
    0x004643A8: "PlasmaRifle",
    0x0046438C: "PlasmaSword",              # Energy Sword
    0x0046436C: "RocketLauncher",
    0x0046435C: "Shotgun",
    0x00464354: "SMG",                      # aSmg
    0x00464338: "SilencedSMG",              # aSilencedSmg
    0x00464328: "Sniper",                   # Sniper Rifle
    0x00464310: "BeamRifle",
    0x004642F4: "Disintegrator",            # Sentinel Beam?
    0x004642C8: "SentinelBeamWeapon",       # aSentinelBeamWe
    0x00464298: "SentinelNeedler",          # aSentinelNeedle
    0x00464268: "SentinelGrenade",          # aSentinelGrenad
    0x00464238: "SentinelCharge",           # aSentinelCharge
    0x00464210: "BrutePlasmaRifle",         # aBrutePlasmaRif
}


# =============================================================================
# NETWORK PROTOCOL — MESSAGE TYPES
# =============================================================================
# Network message names from debug strings. These are the session/lobby
# protocol messages used by Halo 2's peer-to-peer networking.

NETWORK_MESSAGES = {
    # Connection management
    0x0045CD50: "ConnectRequest",
    0x0045CD44: "ConnectRefuse",            # Identifier
    0x0045CD34: "ConnectEstablished",       # aConnectEstabli
    0x0045CD20: "ConnectClosed",
    0x0045CD08: "Ping",
    0x0045CD00: "Pong",
    0x0045CCEC: "BroadcastSearch",          # aBroadcastSearc
    0x0045CCDC: "BroadcastReply",

    # Host migration
    0x0045CDF8: "HostHandoff",
    0x0045CDE8: "PeerHandoff",
    0x0045CDD8: "HostTransition",           # aHostTransition
    0x0045CDC4: "HostReestablish",          # aHostReestablis
    0x0045CDB4: "HostDecline",
    0x0045CDA0: "PeerReestablish",          # aPeerReestablis
    0x0045CD90: "PeerEstablish",
    0x0045CD84: "ElectionRefuse",           # aElectionRefuse
    0x0045CD74: "Election",

    # Session management
    0x0045CE18: "SessionDisband",
    0x0045CE08: "SessionBoot",
    0x0045CE3C: "LeaveSession",
    0x0045CE28: "LeaveAcknowledge",         # aLeaveAcknowled
    0x0045CE64: "JoinRequest",
    0x0045CE58: "JoinAbort",
    0x0045CE4C: "JoinRefuse",

    # Player management
    0x0045CEA8: "PlayerAdd",
    0x0045CE98: "PlayerRefuse",
    0x0045CE88: "PlayerRemove",
    0x0045CE74: "PlayerProperties",         # aPlayerProperti
    0x0045CEB4: "BootMachine",
    0x0045CEC4: "DelegateLeader",           # aDelegateLeader
    0x0045CED8: "PeerProperties",
    0x0045CEE8: "MembershipUpdate",         # aMembershipUpda

    # Game coordination
    0x0045CF48: "PlayerAcknowledge",        # aPlayerAcknowle
    0x0045CEFC: "ModeAcknowledge",          # aModeAcknowledg
    0x0045CF34: "CountdownTimer",
    0x0045CF24: "ParametersRequest",        # aParametersRequ
    0x0045CF10: "ParametersUpdate",         # (inferred)
    0x0045CF5C: "ViewEstablishment",        # aViewEstablishm
    0x0045CF70: "SynchronousGame",          # aSynchronousGam
    0x0045CF88: "SynchronousJoin",          # aSynchronousJoi
    0x0045CF9C: "SynchronousAction",        # aSynchronousAct
    0x0045CFB0: "SynchronousUpdate",        # aSynchronousUpd
    0x0045CFC4: "GameResults",

    # Time sync
    0x0045CD60: "TimeSynchronization",      # aTimeSynchroniz
}


# =============================================================================
# GAME ENGINE — ENTITY REPLICATION FIELDS
# =============================================================================
# Debug assertion strings for networked entity state. These reveal the
# internal structure of replicated game objects.

REPLICATION_FIELDS = {
    # Player entity
    0x0045E0F8: "Team",                     # aTeam
    0x0045E0E0: "ParentVehicleExists",      # aParentVehicleE
    0x0045E0A4: "DesiredWeaponState",       # aDesiredWeaponS
    0x0045E090: "WeaponTypeExists",         # aWeaponTypeExis
    0x0045E07C: "WeaponStateExists",        # aWeaponStateExi
    0x0045E064: "GrenadeCountsExists",      # aGrenadeCountsE
    0x0045E050: "ActiveCamoExists",         # aActiveCamoExis

    # Weapon entity
    0x0045E8D4: "WeaponAmmoExists",         # aWeaponAmmoExis
    0x0045E8C8: "WeaponFire",
    0x0045E898: "WeaponReload",
    0x0045E86C: "WeaponDrop",
    0x0045E83C: "WeaponPutAway",
    0x0045E808: "WeaponPickup",
    0x0045E7D8: "WeaponEffect",

    # Multiplayer-specific
    0x0045E8E8: "MultiplayerTeam",          # aMultiplayerTea
    0x0045E900: "MultiplayerStatborg",      # aMultiplayerSta — stats system!
    0x0045E91C: "WeaponCreation",

    # Vehicle entity
    0x0045E368: "Vehicle",
    0x0045E344: "VehicleCreation",          # aVehicleCreatio
    0x0045DE84: "VehicleFlipRelease",       # aVehicleFlipRel
    0x0045DE54: "VehicleTrickRelease",      # aVehicleTrickRe
    0x0045D740: "VehicleEntrance",          # aVehicleEntranc

    # Game engine requests
    0x0045EBC0: "GameEngineRequest_0",      # aGameEngineRequ_0
    0x0045EBE0: "GameEngineRequest",
    0x0045EC08: "Territories",
    0x0045EC14: "GameEngine",
    0x0045EC20: "GameEngineEvent",          # aGameEngineEven
}


# =============================================================================
# XBOX LIVE / ONLINE STATS API
# =============================================================================
# XOnline stat read/write functions — how the game reports stats to Xbox Live.

XONLINE_STATS_FUNCS = {
    0x003AA9A0: "XOnlineStatWrite",
    0x003AA9AB: "XOnlineStatRead",
    0x003AA9B6: "XOnlineStatReadGetResult",
    0x003B5707: "XOnlineStatWriteGetResult",    # (CXo wrapper)
    0x003C4806: "WriteStatPostParameter",
    0x003C483C: "WriteStatPostParameterStat",
    0x003C48F7: "CXo::XOnlineStatReadGetResult",
    0x003C4B87: "CXo::StatsBuildInternalUnit",
    0x003C4C1A: "CXo::StatsValidateWriteStatsAndGetSize",
    0x003C534C: "CXo::StatsContinue",
    0x003C5454: "CXo::StatsClose",
    0x003C5647: "CXo::XOnlineStatWrite",
    0x003C5821: "CXo::XOnlineStatRead",
    0x003B7123: "CXo::StatsContinueUpload",
}


# =============================================================================
# XBOX LIVE / MATCHMAKING
# =============================================================================

MATCHMAKING_FUNCS = {
    0x003AA788: "XOnlineMatchSessionCreate",
    0x003AA797: "XOnlineMatchSessionUpdate",
    0x003AA7C7: "XOnlineMatchSessionGetInfo",
    0x003AA7D2: "XOnlineMatchSessionDelete",
    0x003AA7F0: "XOnlineMatchSessionFindFromID",
    0x003AA81D: "XOnlineMatchSearchGetResults",
    0x003AA828: "XOnlineMatchSearchParse",
    0x003AA833: "XOnlineMatchSearchResultsLen",
    0x003BD605: "CXo::MatchContinue",
    0x003BD737: "CXo::MatchClose",
}


# =============================================================================
# HUD / UI ELEMENTS
# =============================================================================

UI_ELEMENTS = {
    0x00465C08: "PcrList",                  # aPcrList — POST-GAME CARNAGE REPORT UI!
    0x004653C4: "PauseGameList",
    0x00465638: "MpPauseGameList",          # aMpPauseGameLis
    0x004666B8: "MatchmakingList",          # aMatchmakingLis
    0x00466878: "NetworkSquadList",         # aNetworkSquadLi
    0x00466498: "GamertagList",
    0x00466374: "PlayerProfileList",        # aPlayerProfileL
    0x00467A10: "RecentPlayersList",        # aRecentPlayersL
    0x00467EC0: "MpChangeTeamsList",        # aMpChangeTeamsL
    0x00467F30: "MpPlayerSettings",         # aMpPlayerSettin
    0x00468320: "VariantEditing",           # aVariantEditing
    0x004684E8: "PlayerProfileEdit",        # aPlayerProfileE

    # HUD scoreboard
    0x00463FF4: "HudScoreboardTeam",        # aHudScoreboardT
    0x00464028: "HudScoreboardVariant",     # aHudScoreboardV
    0x00464060: "HudScoreboardOther",       # aHudScoreboardO
    0x004640A4: "HudScoreboardPlayer",      # aHudScoreboardP

    # Game setup strings
    0x00464868: "Mapname",                  # aMapname
    0x00464854: "Gametype",                 # aGametype
    0x00464844: "Variant",
    0x004647BC: "TeamsEnabled",
    0x004647A4: "VehicleSet",
    0x0046478C: "WeaponSet",

    # Player slots
    0x004646B8: "Player0Gamertag",          # aPlayer0Gamerta
    0x00464694: "Player1Gamertag",
    0x00464670: "Player2Gamertag",
    0x0046464C: "Player3Gamertag",
    0x00464760: "Player0Profile",           # aPlayer0Profile
    0x00464734: "Player1Profile",
    0x00464708: "Player2Profile",
    0x004646DC: "Player3Profile",
}


# =============================================================================
# ONLINE STATS — FIELD NAMES REPORTED TO XBOX LIVE
# =============================================================================
# String references at 0x0045D0C0 "online_stats: XOnline..." suggest
# these are the field names uploaded to Xbox Live leaderboards.

ONLINE_STAT_LABELS = {
    0x0045D0C0: "OnlineStats_XOnline",      # aOnlineStatsXon — stats upload context
    0x0045D1CC: "SlayerUpdateSRelease",     # Slayer engine stats upload
    0x0045D304: "CtfUpdateSRelease",        # CTF engine stats upload
    0x0045D3B4: "OddballUpdateSRelease",    # Oddball engine stats upload
    0x0045D494: "KingUpdateSRelease",       # KOTH engine stats upload
    0x0045D658: "JuggernautUpdate",         # Juggernaut engine stats upload
    0x0045D580: "TerritoriesUpdate",        # Territories engine stats upload
}


# =============================================================================
# PLAYER STATE — SPAWN, RESPAWN, SCORING
# =============================================================================

PLAYER_SCORING = {
    0x0045D800: "PlayerUpdateRelease",       # aPlayerUpdateRe
    0x0045D7E8: "RespawnTimerExists",        # aRespawnTimerEx
    0x0045D7D0: "SpeedMultiplier",           # aSpeedMultiplie
    0x0045D7B8: "WaypointAction",            # aWaypointAction
    0x0045D79C: "BlockingTeleporter",        # aBlockingTelepo
    0x0045D78C: "NetdebugExists",            # aNetdebugExists
    0x0045D774: "LivesRemainingExists",      # aLivesRemaining
    0x0045D75C: "LastBetrayerExists",        # aLastBetrayerEx
    0x0045D728: "ActiveInGameExists",        # aActiveInGameEx
    0x0045D714: "SittingOutExists",          # aSittingOutExis

    # Scoring context (game engine scoring rules)
    0x004608DC: "CauseTeamOpponent",         # aCauseTeamOppon
    0x00460914: "CauseTeamScore",
    0x00460938: "EffectTeam",
    0x00460954: "CauseTeam",
    0x0046096C: "EffectPlayer",
    0x0046098C: "CausePlayer",
    0x00460874: "ScoreToWin",                # aScoreToWin
    0x00460890: "LocalTeamScore",            # aLocalTeamScore
    0x004608B4: "LocalPlayerScore",          # aLocalPlayerSco
    0x00460850: "LocalSpawnTimer",           # aLocalSpawnTime
}


# =============================================================================
# MAP / LEVEL LOADING
# =============================================================================

MAP_LOADING = {
    0x0045F0E8: "Map",                       # aMap
    0x0045F0DC: "DMaps",                     # aDMaps
    0x0045F0C0: "DMapsFonts",                # aDMapsFonts
    0x0046078C: "DMapsSMap",                 # aDMapsSMap
    0x0046079C: "SMap",                      # aSMap
    0x004607D0: "MultiplayerLevel",          # aMultiplayerLev
    0x004607EC: "LevelHandles",              # aLevelHandles
    0x00463A84: "MapLoadPercent",            # aMapLoadPercent
    0x004607B8: "PatchV3Lvl",               # aPatchV3Lvl (title update)
}


# =============================================================================
# DIFFICULTY / CAMPAIGN (less relevant but included for completeness)
# =============================================================================

DIFFICULTY_STRINGS = {
    0x0045F3FC: "Easy",
    0x0045F3F4: "Normal",
    0x0045F3EC: "Heroic",
    0x0045F3E0: "Legendary",
}

CAMERA_MODES = {
    0x0045F6C4: "Players",                   # aPlayers (player camera)
    0x0045F6DC: "Camera",
    0x0045F6E4: "FirstPerson",
    0x0045F6F4: "Editor",
    0x0045F6FC: "Flying",
    0x0045F704: "Orbiting",
    0x0045F710: "Following",
}


# =============================================================================
# XBOX SDK / SYSTEM FUNCTIONS (useful for breakpoints / hooking)
# =============================================================================

SYSTEM_FUNCS = {
    # Memory
    0x0032CF16: "malloc",
    0x0032ED91: "free",
    0x0032E2E9: "realloc",
    0x00332383: "calloc",
    0x002DB49D: "XPhysicalAllocEx",
    0x002DB4CA: "XPhysicalProtect",

    # Threading
    0x002DC0B6: "CreateThread",
    0x002DC124: "GetCurrentThreadId",
    0x002E0478: "WaitForSingleObject",
    0x002E048A: "WaitForMultipleObjects",
    0x002E04A4: "Sleep",

    # File I/O
    0x002DC640: "CreateFileA",
    0x002DC131: "ReadFile",
    0x002DC21E: "WriteFile",
    0x002E0B69: "GetFileAttributesA",

    # Save games
    0x0033AED2: "XCreateSaveGame",
    0x0033B135: "XDeleteSaveGame",
    0x0033B205: "XFindFirstSaveGame",

    # Network
    0x003AA854: "XOnlineNotificationSetState",
    0x003AA8C5: "XOnlineFriendsRevokeGameInvite",
    0x003AA907: "XOnlineFriendsGetAcceptedGameInvite",

    # Misc
    0x0033B465: "XGetGameRegion",
    0x002DA6E2: "XLaunchNewImageA",
    0x0033A47A: "XGetAutoLogonFlag",
    0x0033A3F0: "XGetVideoStandard",
    0x0033A419: "XGetVideoFlags",
    0x003765AD: "XNetGetEthernetLinkStatus",     # (approx)
}


# =============================================================================
# VOICE CHAT ENGINE
# =============================================================================
# XHV (Xbox High-level Voice) engine. Large subsystem for voice comms.
# Included here for completeness; not directly relevant to stats reading.

XHV_ENGINE = {
    0x0033D135: "XHVEngineCreate",
    0x0033CFA4: "CXHVEngine::DoWork",
    0x0033CF78: "CXHVEngine::DoWork_alt",
    0x0033D047: "CXHVEngine::InitEngine",
    0x0033D1A5: "CXHVEngine::Release",
}


# =============================================================================
# UTILITY: Address lookups
# =============================================================================

def _build_all_symbols():
    """Merge all symbol dicts into a flat addr->name mapping."""
    result = {}
    for d in [
        XBDM_ACCESSIBLE, GAME_STATES, GAME_ENGINE_SUBSYSTEMS,
        GAMETYPE_ENGINE_STRINGS, GAME_ENGINE_GLOBALS, STAT_FIELD_STRINGS,
        GAMETYPE_STAT_STRINGS, MEDAL_STRINGS, GAMETYPE_NAMES, GAME_VARIANTS,
        WEAPON_NAMES, NETWORK_MESSAGES, REPLICATION_FIELDS,
        XONLINE_STATS_FUNCS, MATCHMAKING_FUNCS, UI_ELEMENTS,
        ONLINE_STAT_LABELS, PLAYER_SCORING, MAP_LOADING,
        DIFFICULTY_STRINGS, CAMERA_MODES, SYSTEM_FUNCS, XHV_ENGINE,
    ]:
        result.update(d)
    return result


ALL_SYMBOLS = _build_all_symbols()


def lookup(addr):
    """Look up a symbol name by virtual address."""
    return ALL_SYMBOLS.get(addr)


def find(pattern):
    """Find symbols whose name contains the given substring (case-insensitive)."""
    pattern = pattern.lower()
    return {addr: name for addr, name in ALL_SYMBOLS.items()
            if pattern in name.lower()}


def nearest(addr):
    """Find the nearest symbol at or before the given address."""
    candidates = [(a, n) for a, n in ALL_SYMBOLS.items() if a <= addr]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[0])
    return best[0], best[1], addr - best[0]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        query = sys.argv[1]
        if query.startswith("0x"):
            addr = int(query, 16)
            result = nearest(addr)
            if result:
                sym_addr, name, offset = result
                if offset == 0:
                    print(f"0x{addr:08X} = {name}")
                else:
                    print(f"0x{addr:08X} = {name} + 0x{offset:X}")
            else:
                print(f"0x{addr:08X}: no symbol found")
        else:
            matches = find(query)
            for addr, name in sorted(matches.items()):
                print(f"  0x{addr:08X}  {name}")
            print(f"\n{len(matches)} matches for '{query}'")
    else:
        print(f"Halo 2 v1.5 XBE Symbol Index — {len(ALL_SYMBOLS)} symbols")
        print(f"Usage: python {sys.argv[0]} <0xADDRESS | search_term>")
        print(f"\nExamples:")
        print(f"  python {sys.argv[0]} 0x56B900    # lookup PGCR Display base")
        print(f"  python {sys.argv[0]} 0x23975C    # lookup breakpoint addr")
        print(f"  python {sys.argv[0]} medal       # find medal-related symbols")
        print(f"  python {sys.argv[0]} slayer      # find slayer-related symbols")
        print(f"  python {sys.argv[0]} score       # find scoring symbols")
