# -*- coding: utf-8 -*-
"""SPL fork: auto-travel a game server to the voted map when a match starts.

Server selection: ordered preference list + claims ledger. A server is free
iff no *live* bot match has claimed it (claims self-expire when the match
leaves bot.active_matches — report/abort/timeout/any path). No player-count
probing: connection counts can't distinguish AFKs from games, so we don't ask.

Fire-and-forget by design — any failure logs and never touches the match
lifecycle (an exception escaping into think() gets the match silently
dropped by the on_think handler).
"""
import asyncio
import struct

from core.console import log

ENABLED = True

# Ordered by preference: first free server in this list wins.
SERVERS = [
	{"name": "VA2", "host": "178.156.147.105","port": 27105, "password": "spl6969420"},
	{"name": "VA1", "host": "178.156.153.38", "port": 27015, "password": "spl6969420"},
]

# server name -> match id that claimed it. Claims are only meaningful while
# that match is still in bot.active_matches; stale entries are ignored and
# overwritten. Cleared on restart (worst case: one redundant skip).
_claims = {}

# Pug map display name -> scenario, verified against the server's own
# `scenarios` RCON output (2026-07-07). Two marked entries are best-guess.
SCENARIOS = {
	"Farmhouse West":    "Scenario_Farmhouse_Firefight_West",
	"Precinct East":     "Scenario_Precinct_Firefight_East",
	"Tell West":         "Scenario_Tell_Firefight_West",
	"Tell East":         "Scenario_Tell_Firefight_East",
	"Refinery":          "Scenario_Refinery_Firefight_West",
	"Summit East":       "Scenario_Summit_Firefight_East",
	"Hideout West":      "Scenario_Hideout_Firefight_West",
	"Tideway":           "Scenario_Tideway_Firefight_West",
	"Outskirts West":    "Scenario_Outskirts_Firefight_West",
	"Ministry":          "Scenario_Ministry_Firefight_A",
	"Last Light":        "Scenario_LastLight_Firefight",
	"Gap East":          "Scenario_Gap_Firefight",          # GUESS: no _East on server
	"Hillside West":     "Scenario_Hillside_Firefight_West",
	"Forest East":       "Scenario_Forest_Firefight_East",
	"Power Plant South": "Scenario_PowerPlant_Firefight_West",  # GUESS: only East/West exist
	"Hold":              "Scenario_Hold_Firefight",
}


def _pack(pid, ptype, body):
	payload = struct.pack("<ii", pid, ptype) + body.encode() + b"\x00\x00"
	return struct.pack("<i", len(payload)) + payload


async def _rcon(host, port, password, command, timeout=10):
	""" Minimal async Source-RCON: auth, run one command, close. """
	reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
	try:
		async def read_packet():
			size = struct.unpack("<i", await asyncio.wait_for(reader.readexactly(4), timeout))[0]
			data = await asyncio.wait_for(reader.readexactly(size), timeout)
			pid, ptype = struct.unpack("<ii", data[:8])
			return pid, ptype, data[8:-2]

		writer.write(_pack(1, 3, password))
		await writer.drain()
		pid, ptype, _ = await read_packet()
		if ptype != 2:  # some servers send an empty RESPONSE_VALUE before the auth reply
			pid, ptype, _ = await read_packet()
		if pid == -1:
			raise ConnectionError("RCON auth failed")

		writer.write(_pack(2, 2, command))
		await writer.drain()
		try:
			_, _, body = await read_packet()
			return body.decode(errors="replace")
		except (asyncio.TimeoutError, asyncio.IncompleteReadError):
			return ""  # travel drops the connection mid-reply; normal
	finally:
		writer.close()


def _claim_is_live(match_id):
	import bot
	return any(m.id == match_id for m in bot.active_matches)


def _pick_server(match):
	""" First server in preference order not claimed by a live match. """
	for srv in SERVERS:
		claimed_by = _claims.get(srv["name"])
		if claimed_by is not None and claimed_by != match.id and _claim_is_live(claimed_by):
			continue
		return srv
	return None


async def _travel(match):
	map_name = match.maps[0]
	scenario = SCENARIOS.get(map_name)
	if scenario is None:
		log.info(f"spl_travel: no scenario mapping for {map_name!r}, skipping")
		return
	srv = _pick_server(match)
	if srv is None:
		log.info(f"spl_travel: all servers claimed by live matches, skipping (match {match.id})")
		return
	_claims[srv["name"]] = match.id
	try:
		await _rcon(srv["host"], srv["port"], srv["password"], f"travelscenario {scenario}")
		log.info(f"spl_travel: {srv['name']} -> {scenario} (match {match.id})")
	except Exception as e:
		log.error(f"spl_travel: failed to travel {srv['name']} for match {match.id}: {type(e).__name__}: {e}")


def travel_for_match(match):
	""" Entry point called from Match.start_waiting_report(). Never raises. """
	try:
		if not ENABLED or not match.maps:
			return
		asyncio.get_event_loop().create_task(_travel(match))
	except Exception as e:
		log.error(f"spl_travel: scheduling failed: {e}")