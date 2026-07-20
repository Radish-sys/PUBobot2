__all__ = ['last_game', 'stats', 'top', 'rank', 'leaderboard', 'linksteam', 'kd']

from time import time
from math import ceil
from nextcord import Member, Embed, Colour

from core.utils import get, find, seconds_to_str, get_nick, discord_table
from core.database import db

import bot


async def last_game(ctx, queue: str = None, player: Member = None, match_id: int = None):
	lg = None

	if match_id:
		lg = await db.select_one(
			['*'], "qc_matches", where=dict(channel_id=ctx.qc.id, match_id=match_id), order_by="match_id", limit=1
		)

	elif queue:
		if queue := find(lambda q: q.name.lower() == queue.lower(), ctx.qc.queues):
			lg = await db.select_one(
				['*'], "qc_matches", where=dict(channel_id=ctx.qc.id, queue_id=queue.id), order_by="match_id", limit=1
			)

	elif player and (member := await ctx.get_member(player)) is not None:
		if match := await db.select_one(
			['match_id'], "qc_player_matches", where=dict(channel_id=ctx.qc.id, user_id=member.id),
			order_by="match_id", limit=1
		):
			lg = await db.select_one(
				['*'], "qc_matches", where=dict(channel_id=ctx.qc.id, match_id=match['match_id'])
			)

	else:
		lg = await db.select_one(
			['*'], "qc_matches", where=dict(channel_id=ctx.qc.id), order_by="match_id", limit=1
		)

	if not lg:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Nothing found"))

	players = await db.select(
		['user_id', 'nick', 'team'], "qc_player_matches",
		where=dict(match_id=lg['match_id'])
	)
	embed = Embed(colour=Colour(0x50e3c2))
	embed.add_field(name=lg['queue_name'], value=seconds_to_str(int(time()) - lg['at']) + " ago")
	if len(team := [p['nick'] for p in players if p['team'] == 0]):
		embed.add_field(name=lg['alpha_name'], value="`" + ", ".join(team) + "`")
	if len(team := [p['nick'] for p in players if p['team'] == 1]):
		embed.add_field(name=lg['beta_name'], value="`" + ", ".join(team) + "`")
	if len(team := [p['nick'] for p in players if p['team'] is None]):
		embed.add_field(name=ctx.qc.gt("Players"), value="`" + ", ".join(team) + "`")
	if lg['ranked']:
		if lg['winner'] is None:
			winner = ctx.qc.gt('Draw')
		else:
			winner = [lg['alpha_name'], lg['beta_name']][lg['winner']]
		embed.add_field(name=ctx.qc.gt("Winner"), value=winner)
	await ctx.reply(embed=embed)


async def stats(ctx, player: Member = None):
	if player:
		if (member := await ctx.get_member(player)) is not None:
			data = await bot.stats.user_stats(ctx.qc.id, member.id)
			target = get_nick(member)
		else:
			raise bot.Exc.NotFoundError(ctx.qc.gt("Specified user not found."))
	else:
		data = await bot.stats.qc_stats(ctx.qc.id)
		target = f"#{ctx.channel.name}"

	embed = Embed(
		title=ctx.qc.gt("Stats for __{target}__").format(target=target),
		colour=Colour(0x50e3c2),
		description=ctx.qc.gt("**Total matches: {count}**").format(count=data['total'])
	)
	for q in data['queues']:
		embed.add_field(name=q['queue_name'], value=str(q['count']), inline=True)

	await ctx.reply(embed=embed)


async def top(ctx, period=None):
	if period in ["day", ctx.qc.gt("day")]:
		time_gap = int(time()) - (60 * 60 * 24)
	elif period in ["week", ctx.qc.gt("week")]:
		time_gap = int(time()) - (60 * 60 * 24 * 7)
	elif period in ["month", ctx.qc.gt("month")]:
		time_gap = int(time()) - (60 * 60 * 24 * 30)
	elif period in ["year", ctx.qc.gt("year")]:
		time_gap = int(time()) - (60 * 60 * 24 * 365)
	else:
		time_gap = None

	data = await bot.stats.top(ctx.qc.id, time_gap=time_gap)
	embed = Embed(
		title=ctx.qc.gt("Top 10 players for __{target}__").format(target=f"#{ctx.channel.name}"),
		colour=Colour(0x50e3c2),
		description=ctx.qc.gt("**Total matches: {count}**").format(count=data['total'])
	)
	for p in data['players']:
		embed.add_field(name=p['nick'], value=str(p['count']), inline=True)
	await ctx.reply(embed=embed)



STEAMID64_RE = __import__('re').compile(r"(7656119\d{10})")
VANITY_RE = __import__('re').compile(r"steamcommunity\.com/id/([A-Za-z0-9_-]+)")
STEAM_API_KEY = ""  # https://steamcommunity.com/dev/apikey ; empty = vanity resolution disabled

async def _resolve_vanity(name):
	""" Resolve a Steam vanity name to a SteamID64 via the Steam Web API. Returns None on any failure. """
	if not STEAM_API_KEY:
		return None
	try:
		import aiohttp
		url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
		async with aiohttp.ClientSession() as s:
			async with s.get(url, params=dict(key=STEAM_API_KEY, vanityurl=name), timeout=aiohttp.ClientTimeout(total=5)) as r:
				data = await r.json()
		resp = data.get("response", {})
		return resp.get("steamid") if resp.get("success") == 1 else None
	except Exception:
		return None


def _extract_steamid64(text):
	""" Accepts a raw SteamID64 or a steamcommunity.com/profiles/ URL. """
	if not text:
		return None
	m = STEAMID64_RE.search(text)
	return m.group(1) if m else None


async def linksteam(ctx, args: str = None):
	if not args:
		link = await db.select_one(['steamid'], "steam_links", where=dict(user_id=ctx.author.id))
		if link:
			await ctx.reply(f"Your linked SteamID64: `{link['steamid']}`")
		else:
			await ctx.reply(
				"No Steam account linked. Use `!linksteam <SteamID64 or profile URL>`.\n"
				"Find yours at <https://steamcommunity.com/my/> -> the number in the URL, "
				"or <https://steamid.io/>."
			)
		return

	steamid = _extract_steamid64(args)
	if not steamid:
		m = VANITY_RE.search(args)
		vanity = m.group(1) if m else args.strip().strip("/").split("/")[-1]
		if vanity and __import__('re').fullmatch(r"[A-Za-z0-9_-]{2,32}", vanity):
			steamid = await _resolve_vanity(vanity)
	if not steamid:
		raise bot.Exc.SyntaxError(
			"Could not resolve that to a SteamID64. Paste the 17-digit ID (starts with 7656119), "
			"your steamcommunity.com/profiles/... URL, or your custom /id/ URL."
		)

	taken = await db.select_one(['user_id'], "steam_links", where=dict(steamid=steamid))
	if taken and taken['user_id'] != ctx.author.id:
		raise bot.Exc.PermissionError(
			"That Steam account is already linked to another Discord user. "
			"If this is an error, contact an admin."
		)

	await db.execute(
		"INSERT INTO steam_links (user_id, steamid) VALUES (%s, %s) "
		"ON DUPLICATE KEY UPDATE steamid = VALUES(steamid)",
		(ctx.author.id, steamid)
	)
	await ctx.success(f"Linked to SteamID64 `{steamid}`. Your in-game stats will now appear on !rank.")



async def kd(ctx, player: Member = None):
	""" Combat stats readout for yourself or another player. """
	target = ctx.author if not player else await ctx.get_member(player)
	if target is None:
		raise bot.Exc.NotFoundError("Specified user not found.")
	link = await db.select_one(['steamid'], "steam_links", where=dict(user_id=target.id))
	if not link:
		if target.id == ctx.author.id:
			await ctx.reply("No Steam account linked. Use `/linksteam` first.")
		else:
			await ctx.reply(f"{get_nick(target)} has no Steam account linked.")
		return
	row = await db.fetchone(
		"SELECT COUNT(*) rounds, COALESCE(SUM(kills),0) k, COALESCE(SUM(deaths),0) d, "
		"COALESCE(SUM(assists),0) a, COALESCE(SUM(headshots),0) hs, "
		"COALESCE(SUM(obj_captured),0) obj, COALESCE(SUM(score),0) sc "
		"FROM spl_round_stats WHERE steamid=%s AND team IN (0,1)",
		(link['steamid'],)
	)
	if not row or not row['rounds']:
		await ctx.reply("No in-game rounds recorded yet.")
		return
	ratio = round(row['k'] / max(row['d'], 1), 2)
	hs_pct = round(100 * row['hs'] / max(row['k'], 1))
	embed = Embed(title=f"__{get_nick(target)}__ — combat stats", colour=Colour(0xE67E22))
	embed.add_field(name="Rounds", value=str(row['rounds']))
	embed.add_field(name="K / D / A", value=f"{row['k']} / {row['d']} / {row['a']}")
	embed.add_field(name="K/D", value=str(ratio))
	embed.add_field(name="Headshots", value=f"{row['hs']} ({hs_pct}%)")
	embed.add_field(name="Objectives", value=str(row['obj']))
	embed.add_field(name="Score", value=f"{row['sc']:,}")
	if hasattr(target, 'display_avatar'):
		embed.set_thumbnail(url=target.display_avatar.url)
	await ctx.reply(embed=embed)


async def rank(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	data = await ctx.qc.get_lb()
	# Figure out leaderboard placement
	if p := find(lambda i: i['user_id'] == target.id, data):
		place = data.index(p) + 1
	else:
		data = await db.select(
			['user_id', 'rating', 'deviation', 'channel_id', 'wins', 'losses', 'draws', 'is_hidden', 'streak'],
			"qc_players",
			where={'channel_id': ctx.qc.rating.channel_id}
		)
		p = find(lambda i: i['user_id'] == target.id, data)
		place = "?"

	if p:
		embed = Embed(title=f"__{get_nick(target)}__", colour=Colour(0x7289DA))
		embed.add_field(name="№", value=f"**{place}**", inline=True)
		embed.add_field(name=ctx.qc.gt("Matches"), value=f"**{(p['wins'] + p['losses'] + p['draws'])}**", inline=True)
		if p['rating']:
			embed.add_field(name=ctx.qc.gt("Rank"), value=f"**{ctx.qc.rating_rank(p['rating'])['rank']}**", inline=True)
			embed.add_field(name=ctx.qc.gt("Rating"), value=f"**{p['rating']}**±{p['deviation']}")
		else:
			embed.add_field(name=ctx.qc.gt("Rank"), value="**〈?〉**", inline=True)
			embed.add_field(name=ctx.qc.gt("Rating"), value="**?**")
		embed.add_field(
			name="W/L/D/S",
			value="**{wins}**/**{losses}**/**{draws}**/**{streak}**".format(**p),
			inline=True
		)
		embed.add_field(name=ctx.qc.gt("Winrate"), value="**{}%**\n\u200b".format(
			int(p['wins'] * 100 / (p['wins'] + p['losses'] or 1))
		), inline=True)
		if target.display_avatar:
			embed.set_thumbnail(url=target.display_avatar.url)

		changes = await db.select(
			('at', 'rating_change', 'match_id', 'reason'),
			'qc_rating_history', where=dict(user_id=target.id, channel_id=ctx.qc.rating.channel_id),
			order_by='id', limit=5
		)
		if len(changes):
			embed.add_field(
				name=ctx.qc.gt("Last changes:"),
				value="\n".join(("\u200b \u200b **{change}** \u200b | {ago} ago | {reason}{match_id}".format(
					ago=seconds_to_str(int(time() - c['at'])),
					reason=c['reason'],
					match_id=f"(__{c['match_id']}__)" if c['match_id'] else "",
					change=("+" if c['rating_change'] >= 0 else "") + str(c['rating_change'])
				) for c in changes))
			)
		await ctx.reply(embed=embed)

	else:
		raise bot.Exc.ValueError(ctx.qc.gt("No rating data found."))


async def leaderboard(ctx, page: int = 1):
	page = (page or 1) - 1

	data = await ctx.qc.get_lb()
	pages = ceil(len(await ctx.qc.get_lb())/10)
	data = data[page * 10:(page + 1) * 10]
	if not len(data):
		raise bot.Exc.NotFoundError(ctx.qc.gt("Leaderboard is empty."))

	if ctx.qc.cfg.emoji_ranks:  # display as embed message
		embed = Embed(title=f"Leaderboard - page {page+1} of {pages}", colour=Colour(0x7289DA))
		embed.add_field(
			name="Nickname",
			value="\n".join((
				f'**{(page*10)+n+1}** ' + data[n]['nick'].strip()[:14]
				for n in range(len(data))
			)),
			inline=True
		)
		embed.add_field(
			name="W / L / D",
			value="\n".join((
				f"**{row['wins']}** / **{row['losses']}** / **{row['draws']}** (" +
				str(int(row['wins'] * 100 / ((row['wins'] + row['losses']) or 1))) + "%)"
				for row in data
			)),
			inline=True
		)
		embed.add_field(
			name="Rating",
			value="\n".join((
				ctx.qc.rating_rank(row['rating'])['rank'] + f" **{row['rating']}**"
				for row in data
			)),
			inline=True
		)
		await ctx.reply(embed=embed)
		return

	# display as md table
	await ctx.reply(
		discord_table(
			["№", "Rating〈Ξ〉", "Nickname", "Matches", "W/L/D"],
			[[
				(page * 10) + (n + 1),
				str(data[n]['rating']) + ctx.qc.rating_rank(data[n]['rating'])['rank'],
				data[n]['nick'].strip(),
				int(data[n]['wins'] + data[n]['losses'] + data[n]['draws']),
				"{0}/{1}/{2} ({3}%)".format(
					data[n]['wins'],
					data[n]['losses'],
					data[n]['draws'],
					int(data[n]['wins'] * 100 / ((data[n]['wins'] + data[n]['losses']) or 1))
				)
			] for n in range(len(data))]
		)
	)