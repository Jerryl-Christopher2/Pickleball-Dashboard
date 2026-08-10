# """
# Pickleball Doubles Ranking App (CSV edition)
# ---------------------------------------------
# A Streamlit app for manually entering doubles pickleball players and match
# scores, tracking records, ranking players with an Elo-style rating, and
# generating fair, skill-balanced matchups for a day of open play.

# Run with:
#     streamlit run app.py

# All data is stored locally in plain CSV files next to this script:
#     players.csv  -> id, name, rating, wins, losses, active, is_guest
#     matches.csv  -> id, date, team1_p1, team1_p2, team2_p1, team2_p2,
#                     score1, score2, winning_team, rating_change
#     session.csv  -> id, checked_in, games_today, sitouts_today, date
#                     (today's rotation tracking — who's here, and how many
#                     games/sit-outs they've had today)

# Because it's plain CSV, you can open/edit/backup the files directly in
# Excel, VS Code, etc.
# """

# import itertools
# import os
# import random
# from datetime import date

# import pandas as pd
# import streamlit as st

# PLAYERS_CSV = "players.csv"
# MATCHES_CSV = "matches.csv"
# SESSION_CSV = "session.csv"

# PLAYERS_COLUMNS = ["id", "name", "rating", "wins", "losses", "active", "is_guest"]
# MATCHES_COLUMNS = [
#     "id", "date", "team1_p1", "team1_p2", "team2_p1", "team2_p2",
#     "score1", "score2", "winning_team", "rating_change",
# ]
# SESSION_COLUMNS = ["id", "checked_in", "games_today", "sitouts_today", "date"]

# K_FACTOR = 32
# STARTING_RATING = 1000
# GUEST_NAME = "Guest"

# # Matchmaking tuning knobs:
# # If a court's rating spread (max - min of its 4 players) is above this,
# # the algorithm looks for a better-fitting bench player to swap in.
# RATING_SPREAD_THRESHOLD = 200
# # A bench player is only "eligible" to be swapped in for fairness reasons if
# # their priority-to-play score is within this many points of the outlier
# # they'd replace. Keeps skill-based swaps from being too unfair to the
# # person being benched.
# FAIRNESS_TOLERANCE = 1.5

# # A player whose average partner is rated more than this many points above
# # their own rating gets flagged — their rating may be partly propped up by
# # consistently strong teammates rather than their own play.
# PARTNER_BOOST_THRESHOLD = 100

# # ----------------------------------------------------------------------------
# # CSV storage helpers — players & matches
# # ----------------------------------------------------------------------------

# def _parse_bool_column(series, default):
#     """Robustly parse a CSV column of True/False (or missing) into real bools."""
#     mapped = series.astype(str).str.strip().str.lower().map({"true": True, "false": False})
#     return mapped.fillna(default)


# def init_csvs():
#     if not os.path.exists(PLAYERS_CSV):
#         pd.DataFrame(columns=PLAYERS_COLUMNS).to_csv(PLAYERS_CSV, index=False)
#     if not os.path.exists(MATCHES_CSV):
#         pd.DataFrame(columns=MATCHES_COLUMNS).to_csv(MATCHES_CSV, index=False)
#     if not os.path.exists(SESSION_CSV):
#         pd.DataFrame(columns=SESSION_COLUMNS).to_csv(SESSION_CSV, index=False)


# def load_players():
#     """Load players.csv, self-healing older files that predate the
#     active/is_guest columns, and enforcing the "Guest is always 1000,
#     never ranked" rule on every load.
#     """
#     df = pd.read_csv(PLAYERS_CSV)
#     for col in PLAYERS_COLUMNS:
#         if col not in df.columns:
#             df[col] = pd.Series(dtype="object")

#     if df.empty:
#         return df

#     df["id"] = pd.to_numeric(df["id"], errors="coerce").astype(int)
#     df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(STARTING_RATING)
#     df["wins"] = pd.to_numeric(df["wins"], errors="coerce").fillna(0).astype(int)
#     df["losses"] = pd.to_numeric(df["losses"], errors="coerce").fillna(0).astype(int)
#     df["active"] = _parse_bool_column(df["active"], default=True)
#     df["is_guest"] = _parse_bool_column(df["is_guest"], default=False)

#     # Auto-migrate: if an older file already has a player literally named
#     # "Guest" (any case) but no is_guest flag yet, treat it as the guest.
#     df.loc[df["name"].astype(str).str.strip().str.lower() == "guest", "is_guest"] = True

#     # A guest is never individually ranked: always 1000, no win/loss record,
#     # regardless of what happened to have been written to disk.
#     guest_mask = df["is_guest"]
#     df.loc[guest_mask, "rating"] = STARTING_RATING
#     df.loc[guest_mask, "wins"] = 0
#     df.loc[guest_mask, "losses"] = 0

#     return df


# def save_players(df):
#     df.to_csv(PLAYERS_CSV, index=False)


# def ensure_guest_exists():
#     """Guarantee a global Guest player always exists, auto-creating one if
#     needed. Called at startup so it's always available without any manual
#     setup — a permanent 1000-rated slot for filling in a court."""
#     df = load_players()
#     if df.empty or not df["is_guest"].any():
#         new_row = {
#             "id": next_id(df),
#             "name": GUEST_NAME,
#             "rating": STARTING_RATING,
#             "wins": 0,
#             "losses": 0,
#             "active": True,
#             "is_guest": True,
#         }
#         df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
#         save_players(df)


# def add_guest_slot():
#     """Add an additional guest (Guest 2, Guest 3, ...) for days when more
#     than one fill-in player is needed at once."""
#     df = load_players()
#     n = 1
#     existing_names = set(df["name"].str.lower()) if not df.empty else set()
#     name = GUEST_NAME
#     while name.lower() in existing_names:
#         n += 1
#         name = f"{GUEST_NAME} {n}"
#     new_row = {
#         "id": next_id(df),
#         "name": name,
#         "rating": STARTING_RATING,
#         "wins": 0,
#         "losses": 0,
#         "active": True,
#         "is_guest": True,
#     }
#     df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
#     save_players(df)
#     return name


# def load_matches():
#     df = pd.read_csv(MATCHES_CSV)
#     for col in MATCHES_COLUMNS:
#         if col not in df.columns:
#             df[col] = pd.Series(dtype="object")
#     return df


# def save_matches(df):
#     df.to_csv(MATCHES_CSV, index=False)


# def next_id(df):
#     if df.empty:
#         return 1
#     return int(df["id"].max()) + 1


# def get_player_map(players_df):
#     """Maps id -> name for ALL players, including inactive ones, so past
#     matches involving a since-removed player still display correctly."""
#     return dict(zip(players_df["id"], players_df["name"]))


# def add_player(name):
#     name = name.strip()
#     if not name:
#         return False, "Please enter a name."
#     if name.lower().startswith("guest"):
#         return False, "That name is reserved for guest players — use the 'Add Guest' button instead."
#     players_df = load_players()
#     if not players_df.empty and name.lower() in players_df["name"].str.lower().values:
#         return False, f"Player '{name}' already exists."
#     new_row = {
#         "id": next_id(players_df),
#         "name": name,
#         "rating": STARTING_RATING,
#         "wins": 0,
#         "losses": 0,
#         "active": True,
#         "is_guest": False,
#     }
#     players_df = pd.concat([players_df, pd.DataFrame([new_row])], ignore_index=True)
#     save_players(players_df)
#     return True, f"Added player '{name}'."


# def set_player_active(player_id, active):
#     players_df = load_players()
#     players_df.loc[players_df["id"] == player_id, "active"] = active
#     save_players(players_df)


# # ----------------------------------------------------------------------------
# # CSV storage helpers — today's session (check-ins & rotation tracking)
# # ----------------------------------------------------------------------------

# def load_session_raw():
#     df = pd.read_csv(SESSION_CSV)
#     for col in SESSION_COLUMNS:
#         if col not in df.columns:
#             df[col] = pd.Series(dtype="object")
#     if not df.empty:
#         df["id"] = pd.to_numeric(df["id"], errors="coerce").astype(int)
#         df["checked_in"] = _parse_bool_column(df["checked_in"], default=False)
#         df["games_today"] = pd.to_numeric(df["games_today"], errors="coerce").fillna(0).astype(int)
#         df["sitouts_today"] = pd.to_numeric(df["sitouts_today"], errors="coerce").fillna(0).astype(int)
#         df["date"] = df["date"].astype(str)
#     return df


# def save_session(df):
#     df.to_csv(SESSION_CSV, index=False)


# def sync_session(players_df):
#     """Keep session.csv in sync with the player roster and the calendar day.

#     - Adds a row for any player who doesn't have one yet (defaults to not
#       checked in, 0 games/sit-outs today).
#     - Drops rows for players that no longer exist at all.
#     - If the stored date isn't today, resets everyone's check-in status and
#       today's counts — a fresh day of open play starts from zero.
#     """
#     today_str = date.today().isoformat()
#     df = load_session_raw()

#     if df.empty:
#         rows = [
#             {"id": pid, "checked_in": False, "games_today": 0, "sitouts_today": 0, "date": today_str}
#             for pid in players_df["id"]
#         ]
#         df = pd.DataFrame(rows, columns=SESSION_COLUMNS)
#     else:
#         current_date = df["date"].iloc[0]
#         if current_date != today_str:
#             df["checked_in"] = False
#             df["games_today"] = 0
#             df["sitouts_today"] = 0
#             df["date"] = today_str

#         existing_ids = set(df["id"])
#         new_ids = [pid for pid in players_df["id"] if pid not in existing_ids]
#         if new_ids:
#             new_rows = pd.DataFrame(
#                 [
#                     {"id": pid, "checked_in": False, "games_today": 0, "sitouts_today": 0, "date": today_str}
#                     for pid in new_ids
#                 ]
#             )
#             df = pd.concat([df, new_rows], ignore_index=True)

#         df = df[df["id"].isin(players_df["id"])].reset_index(drop=True)

#     save_session(df)
#     return df


# def set_checked_in(session_df, checked_in_ids):
#     """Overwrite checked_in flags to exactly match the given set of ids."""
#     session_df = session_df.copy()
#     session_df["checked_in"] = session_df["id"].isin(checked_in_ids)
#     save_session(session_df)
#     return session_df


# def apply_round_result(session_df, playing_ids, sitting_ids):
#     session_df = session_df.copy()
#     session_df.loc[session_df["id"].isin(playing_ids), "games_today"] += 1
#     session_df.loc[session_df["id"].isin(sitting_ids), "sitouts_today"] += 1
#     save_session(session_df)
#     return session_df


# def reset_today_stats(session_df):
#     session_df = session_df.copy()
#     session_df["games_today"] = 0
#     session_df["sitouts_today"] = 0
#     save_session(session_df)
#     return session_df


# # ----------------------------------------------------------------------------
# # Elo rating logic for doubles
# # ----------------------------------------------------------------------------

# def expected_score(team_rating, opp_rating):
#     return 1 / (1 + 10 ** ((opp_rating - team_rating) / 400))


# def margin_multiplier(score1, score2):
#     """Scale the rating change by how lopsided the score was.

#     A 11-9 nail-biter barely tells you more than a coin flip did; an 11-1
#     blowout is much stronger evidence of a skill gap. This scales the
#     rating change from 1.0x (very close game) up to 1.5x (a total
#     blowout), based on the margin as a share of total points played.
#     """
#     total_points = score1 + score2
#     if total_points <= 0:
#         return 1.0
#     margin_ratio = abs(score1 - score2) / total_points
#     return 1 + min(margin_ratio, 0.5)


# def record_match(team1_ids, team2_ids, score1, score2, match_date):
#     """Update ratings/records for a manually entered doubles match result.

#     Guest players (is_guest=True) never have their own rating or win/loss
#     record changed — they stay locked at 1000 — but they still count
#     normally toward their team's average rating for everyone else's Elo
#     calculation, exactly like a real 1000-rated opponent/partner would.
#     """
#     if score1 == score2:
#         return False, "Scores can't be tied — pickleball games need a winner."

#     players_df = load_players()
#     players_df = players_df.set_index("id")

#     team1_rating = (players_df.loc[team1_ids[0], "rating"] + players_df.loc[team1_ids[1], "rating"]) / 2
#     team2_rating = (players_df.loc[team2_ids[0], "rating"] + players_df.loc[team2_ids[1], "rating"]) / 2

#     actual1 = 1 if score1 > score2 else 0
#     actual2 = 1 - actual1
#     exp1 = expected_score(team1_rating, team2_rating)
#     exp2 = 1 - exp1

#     mult = margin_multiplier(score1, score2)
#     delta1 = K_FACTOR * mult * (actual1 - exp1)
#     delta2 = K_FACTOR * mult * (actual2 - exp2)

#     winning_team = 1 if actual1 == 1 else 2

#     for pid in team1_ids:
#         if players_df.loc[pid, "is_guest"]:
#             continue
#         players_df.loc[pid, "rating"] += delta1
#         if winning_team == 1:
#             players_df.loc[pid, "wins"] += 1
#         else:
#             players_df.loc[pid, "losses"] += 1

#     for pid in team2_ids:
#         if players_df.loc[pid, "is_guest"]:
#             continue
#         players_df.loc[pid, "rating"] += delta2
#         if winning_team == 2:
#             players_df.loc[pid, "wins"] += 1
#         else:
#             players_df.loc[pid, "losses"] += 1

#     players_df = players_df.reset_index()
#     save_players(players_df)

#     matches_df = load_matches()
#     new_match = {
#         "id": next_id(matches_df),
#         "date": match_date.isoformat(),
#         "team1_p1": team1_ids[0],
#         "team1_p2": team1_ids[1],
#         "team2_p1": team2_ids[0],
#         "team2_p2": team2_ids[1],
#         "score1": score1,
#         "score2": score2,
#         "winning_team": winning_team,
#         "rating_change": round(abs(delta1), 2),
#     }
#     matches_df = pd.concat([matches_df, pd.DataFrame([new_match])], ignore_index=True)
#     save_matches(matches_df)

#     return True, f"Match recorded: {score1}-{score2}. Ratings updated."


# def get_matches_display_df():
#     matches_df = load_matches()
#     players_df = load_players()
#     if matches_df.empty:
#         return pd.DataFrame()
#     player_map = get_player_map(players_df)
#     df = matches_df.copy()
#     df["Team 1"] = df["team1_p1"].map(player_map) + " / " + df["team1_p2"].map(player_map)
#     df["Team 2"] = df["team2_p1"].map(player_map) + " / " + df["team2_p2"].map(player_map)
#     df["Score"] = df["score1"].astype(int).astype(str) + " - " + df["score2"].astype(int).astype(str)
#     df["Winner"] = df.apply(
#         lambda r: r["Team 1"] if r["winning_team"] == 1 else r["Team 2"], axis=1
#     )
#     df["Rating +/-"] = df["rating_change"]
#     df = df.sort_values("id", ascending=False)
#     return df[["date", "Team 1", "Team 2", "Score", "Winner", "Rating +/-"]].rename(
#         columns={"date": "Date"}
#     )


# # ----------------------------------------------------------------------------
# # Partner/opponent strength metric
# # ----------------------------------------------------------------------------

# def compute_partner_opponent_stats(players_df, matches_df):
#     """For every player, average the CURRENT rating of their teammates and
#     opponents across all their recorded matches.

#     This uses today's ratings, not a historical snapshot from when each
#     match was played, so it's an approximation — but it's a quick way to
#     spot a player whose rating looks strong mostly because they keep
#     getting paired with stronger partners, not necessarily because of their
#     own play.

#     Returns a dict: id -> {"partner_avg", "opponent_avg", "n"} (values are
#     None if the player has no recorded matches).
#     """
#     rating_map = dict(zip(players_df["id"], players_df["rating"]))
#     stats = {pid: {"partner_sum": 0.0, "opponent_sum": 0.0, "n": 0} for pid in players_df["id"]}

#     for _, m in matches_df.iterrows():
#         team1 = [int(m["team1_p1"]), int(m["team1_p2"])]
#         team2 = [int(m["team2_p1"]), int(m["team2_p2"])]
#         for team, opp in ((team1, team2), (team2, team1)):
#             opp_avg = (rating_map.get(opp[0], STARTING_RATING) + rating_map.get(opp[1], STARTING_RATING)) / 2
#             for i, pid in enumerate(team):
#                 if pid not in stats:
#                     continue
#                 partner_id = team[1 - i]
#                 stats[pid]["partner_sum"] += rating_map.get(partner_id, STARTING_RATING)
#                 stats[pid]["opponent_sum"] += opp_avg
#                 stats[pid]["n"] += 1

#     result = {}
#     for pid, s in stats.items():
#         if s["n"] > 0:
#             result[pid] = {
#                 "partner_avg": s["partner_sum"] / s["n"],
#                 "opponent_avg": s["opponent_sum"] / s["n"],
#                 "n": s["n"],
#             }
#         else:
#             result[pid] = {"partner_avg": None, "opponent_avg": None, "n": 0}
#     return result


# # ----------------------------------------------------------------------------
# # Matchmaking / rotation logic
# # ----------------------------------------------------------------------------

# def build_matchups(available_records, num_courts):
#     """Suggest courts + teams + a bench for the next round.

#     available_records: list of dicts, each with id, name, rating,
#         games_today, sitouts_today — for every checked-in player.
#     num_courts: how many courts of 4 to fill this round.

#     Returns (courts, sitting_ids):
#         courts is a list of {"team1": [id, id], "team2": [id, id]}
#         sitting_ids is a list of player ids sitting out this round.

#     Approach:
#       1. Rank everyone by a "priority to play" score (more sit-outs and
#          fewer games so far = higher priority). This is the fairness pass.
#       2. Group the players selected to play into skill tiers (sorted by
#          rating, chunked into fours) so courts are naturally competitive.
#       3. If a court's rating spread is too wide, look for a bench player
#          who is a closer skill fit AND whose fairness priority is close
#          enough that swapping them in isn't a big fairness hit. This is how
#          a high-rated player can end up sitting an extra round waiting for
#          a good match — but because sitting out raises their priority score
#          for next round, it can't compound indefinitely.
#       4. Within each finalized court, form teams by pairing the strongest
#          and weakest player against the middle two, which balances the two
#          teams' average rating for a closer game.
#     """
#     records = [dict(r) for r in available_records]
#     for r in records:
#         # Small random jitter breaks exact ties fairly instead of always
#         # favoring, say, whoever happens to be first alphabetically.
#         r["priority"] = r["sitouts_today"] - r["games_today"] + random.uniform(-0.01, 0.01)
#     records.sort(key=lambda r: r["priority"], reverse=True)

#     needed = num_courts * 4
#     playing = records[:needed]
#     sitting = records[needed:]

#     playing.sort(key=lambda r: r["rating"], reverse=True)
#     courts = [playing[i:i + 4] for i in range(0, len(playing), 4)]

#     def court_spread(court):
#         ratings = [p["rating"] for p in court]
#         return max(ratings) - min(ratings) if ratings else 0

#     # Pass 1: swap players *between* courts to tighten skill groupings.
#     # This never changes who plays vs. who sits, so it's always safe —
#     # just a better arrangement of the people already selected to play.
#     for _ in range(10):
#         improved = False
#         for i in range(len(courts)):
#             for j in range(i + 1, len(courts)):
#                 if len(courts[i]) < 4 or len(courts[j]) < 4:
#                     continue
#                 base = court_spread(courts[i]) + court_spread(courts[j])
#                 best_gain, best_pair = 0, None
#                 for a in courts[i]:
#                     for b in courts[j]:
#                         trial_i = [p for p in courts[i] if p is not a] + [b]
#                         trial_j = [p for p in courts[j] if p is not b] + [a]
#                         gain = base - (court_spread(trial_i) + court_spread(trial_j))
#                         if gain > best_gain:
#                             best_gain, best_pair = gain, (a, b)
#                 if best_pair:
#                     a, b = best_pair
#                     courts[i] = [p for p in courts[i] if p is not a] + [b]
#                     courts[j] = [p for p in courts[j] if p is not b] + [a]
#                     improved = True
#         if not improved:
#             break

#     # Pass 2: for any court still too spread out, look to the bench for a
#     # better-fitting player. Only players whose fairness priority is close
#     # to the outlier's are eligible, so this doesn't badly hurt fairness —
#     # it's how a high-rated player can end up sitting an extra round
#     # waiting for a good match, without it snowballing (sitting raises
#     # their priority for next round).
#     for _ in range(2):
#         for court in courts:
#             if len(court) < 4:
#                 continue
#             ratings = [p["rating"] for p in court]
#             spread = max(ratings) - min(ratings)
#             if spread <= RATING_SPREAD_THRESHOLD or not sitting:
#                 continue

#             top_p = max(court, key=lambda p: p["rating"])
#             bottom_p = min(court, key=lambda p: p["rating"])
#             rest_sum = sum(ratings)
#             rest_avg_excl_top = (rest_sum - top_p["rating"]) / 3
#             rest_avg_excl_bottom = (rest_sum - bottom_p["rating"]) / 3

#             if (top_p["rating"] - rest_avg_excl_top) >= (rest_avg_excl_bottom - bottom_p["rating"]):
#                 outlier, rest_avg = top_p, rest_avg_excl_top
#             else:
#                 outlier, rest_avg = bottom_p, rest_avg_excl_bottom

#             eligible = [p for p in sitting if abs(p["priority"] - outlier["priority"]) <= FAIRNESS_TOLERANCE]
#             eligible.sort(key=lambda p: abs(p["rating"] - rest_avg))

#             for candidate in eligible:
#                 new_ratings = [p["rating"] for p in court if p["id"] != outlier["id"]] + [candidate["rating"]]
#                 if max(new_ratings) - min(new_ratings) < spread:
#                     court.remove(outlier)
#                     court.append(candidate)
#                     sitting.remove(candidate)
#                     sitting.append(outlier)
#                     break

#     # Pass 3: some fixes need multiple simultaneous swaps (pulling in
#     # several better-fitting bench players while benching several current
#     # ones at once) because doing it one at a time would briefly make
#     # things worse and get rejected. Court/bench sizes here are small, so
#     # brute-forcing small combinations (k=2 or 3 at a time) is cheap.
#     def try_k_for_k(court, sitting, k):
#         if len(sitting) < k or len(court) < k:
#             return False
#         ratings = [p["rating"] for p in court]
#         spread = max(ratings) - min(ratings)
#         if spread <= RATING_SPREAD_THRESHOLD:
#             return False
#         best_gain, best_out, best_in = 0, None, None
#         for out_combo in itertools.combinations(court, k):
#             out_priority_avg = sum(p["priority"] for p in out_combo) / k
#             eligible = [p for p in sitting if abs(p["priority"] - out_priority_avg) <= FAIRNESS_TOLERANCE * k]
#             for in_combo in itertools.combinations(eligible, k):
#                 remaining = [p for p in court if p not in out_combo]
#                 new_ratings = [p["rating"] for p in remaining + list(in_combo)]
#                 gain = spread - (max(new_ratings) - min(new_ratings))
#                 if gain > best_gain:
#                     best_gain, best_out, best_in = gain, out_combo, in_combo
#         if best_out:
#             for p in best_out:
#                 court.remove(p)
#                 sitting.append(p)
#             for p in best_in:
#                 sitting.remove(p)
#                 court.append(p)
#             return True
#         return False

#     for court in courts:
#         if len(court) < 4:
#             continue
#         for k in (2, 3):
#             for _ in range(3):
#                 if not try_k_for_k(court, sitting, k):
#                     break

#     court_dicts = []
#     for court in courts:
#         court_sorted = sorted(court, key=lambda p: p["rating"], reverse=True)
#         ids = [p["id"] for p in court_sorted]
#         if len(ids) == 4:
#             team1 = [ids[0], ids[3]]
#             team2 = [ids[1], ids[2]]
#         else:
#             # Shouldn't happen in normal use (courts are only built from
#             # complete groups of 4), but guard against a short last group.
#             half = len(ids) // 2
#             team1, team2 = ids[:half], ids[half:]
#         court_dicts.append({"team1": team1, "team2": team2})

#     sitting_ids = [p["id"] for p in sitting]
#     return court_dicts, sitting_ids


# # ----------------------------------------------------------------------------
# # Streamlit UI
# # ----------------------------------------------------------------------------

# st.set_page_config(page_title="Pickleball Doubles Rankings", page_icon="🏓", layout="wide")
# init_csvs()
# ensure_guest_exists()

# # Confirmation messages that need to survive a st.rerun() are stashed here
# # on the run that triggers the rerun, then shown (once) on the next run.
# # Without this, a message set right before st.rerun() gets wiped before the
# # person ever really sees it.
# if "flash" in st.session_state:
#     _kind, _msg = st.session_state.pop("flash")
#     getattr(st, _kind)(_msg)


# def flash(kind, msg):
#     st.session_state["flash"] = (kind, msg)


# st.title("🏓 Pickleball Doubles Rankings")
# st.caption("All data is stored locally in CSV files next to this app.")

# page = st.sidebar.radio(
#     "Navigate",
#     ["Matchmaking", "Leaderboard", "Add Player", "Record Match", "Match History", "Player Profile"],
# )

# # ---- Matchmaking -------------------------------------------------------------
# if page == "Matchmaking":
#     st.header("Today's Matchmaking")

#     players_df = load_players()
#     active_df = players_df[players_df["active"]]
#     if len(active_df) < 4:
#         st.warning("You need at least 4 active players in the system before you can run matchmaking. Add players first.")
#     else:
#         session_df = sync_session(players_df)

#         st.session_state.setdefault("mm_stage", "checkin")
#         st.session_state.setdefault("mm_gen", 0)
#         st.session_state.setdefault("mm_round", 1)

#         info = players_df.set_index("id")

#         # ---- Stage 1: Check-in ------------------------------------------
#         if st.session_state["mm_stage"] == "checkin":
#             st.subheader(f"Round {st.session_state['mm_round']} — Who's here?")
#             st.write("Check people in as they arrive, and check them out if they leave. This list can change between rounds.")

#             all_names = active_df.sort_values("name")["name"].tolist()
#             name_to_id = dict(zip(active_df["name"], active_df["id"]))
#             currently_checked_in = session_df[session_df["checked_in"]]["id"].tolist()
#             default_names = [n for n in all_names if name_to_id[n] in currently_checked_in]

#             selected_names = st.multiselect("Checked in", all_names, default=default_names, key="mm_checkin_select")
#             selected_ids = [name_to_id[n] for n in selected_names]
#             session_df = set_checked_in(session_df, selected_ids)

#             n_here = len(selected_ids)
#             st.metric("Players checked in", n_here)

#             if n_here > 0:
#                 status = session_df[session_df["id"].isin(selected_ids)].merge(
#                     players_df[["id", "name", "rating"]], on="id"
#                 )
#                 status = status.sort_values(["sitouts_today", "games_today"], ascending=[False, True])
#                 st.dataframe(
#                     status[["name", "rating", "games_today", "sitouts_today"]].rename(
#                         columns={"name": "Player", "rating": "Rating", "games_today": "Games Today", "sitouts_today": "Sit-outs Today"}
#                     ),
#                     use_container_width=True,
#                     hide_index=True,
#                 )

#             max_courts = n_here // 4
#             if max_courts < 1:
#                 st.info("Check in at least 4 players to generate matchups.")
#             else:
#                 num_courts = st.number_input(
#                     "Number of courts to fill this round",
#                     min_value=1, max_value=max_courts, value=max_courts, step=1,
#                 )
#                 if st.button("Suggest Matchups ▶", type="primary"):
#                     available_records = status.to_dict("records") if n_here > 0 else []
#                     courts, bench = build_matchups(available_records, int(num_courts))
#                     st.session_state["mm_courts"] = courts
#                     st.session_state["mm_bench"] = bench
#                     st.session_state["mm_gen"] += 1
#                     st.session_state["mm_stage"] = "review"
#                     st.rerun()

#             st.divider()
#             c1, c2 = st.columns(2)
#             if c1.button("Reset today's rotation stats"):
#                 session_df = reset_today_stats(session_df)
#                 flash("success", "Games/sit-out counts reset to zero for today.")
#                 st.rerun()
#             if c2.button("Check everyone out"):
#                 session_df = set_checked_in(session_df, [])
#                 st.rerun()

#         # ---- Stage 2: Review / Edit suggestion ---------------------------
#         elif st.session_state["mm_stage"] == "review":
#             st.subheader(f"Round {st.session_state['mm_round']} — Suggested Matchups")
#             st.write("Edit any slot below if you want to adjust for outside factors, then confirm.")

#             gen = st.session_state["mm_gen"]
#             courts = st.session_state["mm_courts"]
#             checked_in_ids = session_df[session_df["checked_in"]]["id"].tolist()

#             def label(pid):
#                 return f"{info.loc[pid, 'name']} ({info.loc[pid, 'rating']:.0f})"

#             options = sorted([label(pid) for pid in checked_in_ids])
#             label_to_id = {label(pid): pid for pid in checked_in_ids}

#             for i, court in enumerate(courts):
#                 st.markdown(f"**Court {i + 1}**")
#                 c1, c2 = st.columns(2)
#                 with c1:
#                     st.caption("Team 1")
#                     st.selectbox("Player A", options, index=options.index(label(court["team1"][0])), key=f"c{gen}_{i}_t1p1")
#                     st.selectbox("Player B", options, index=options.index(label(court["team1"][1])), key=f"c{gen}_{i}_t1p2")
#                 with c2:
#                     st.caption("Team 2")
#                     st.selectbox("Player C", options, index=options.index(label(court["team2"][0])), key=f"c{gen}_{i}_t2p1")
#                     st.selectbox("Player D", options, index=options.index(label(court["team2"][1])), key=f"c{gen}_{i}_t2p2")

#             # Gather the (possibly edited) assignment
#             assigned_ids, new_courts = [], []
#             for i in range(len(courts)):
#                 ids = [
#                     label_to_id[st.session_state[f"c{gen}_{i}_t1p1"]],
#                     label_to_id[st.session_state[f"c{gen}_{i}_t1p2"]],
#                     label_to_id[st.session_state[f"c{gen}_{i}_t2p1"]],
#                     label_to_id[st.session_state[f"c{gen}_{i}_t2p2"]],
#                 ]
#                 assigned_ids.extend(ids)
#                 new_courts.append({"team1": ids[0:2], "team2": ids[2:4]})

#             bench_ids = [pid for pid in checked_in_ids if pid not in assigned_ids]
#             duplicates = len(assigned_ids) != len(set(assigned_ids))

#             st.markdown("**Sitting out this round:**")
#             if bench_ids:
#                 st.write(", ".join(info.loc[pid, "name"] for pid in bench_ids))
#             else:
#                 st.write("No one — every checked-in player is on a court.")

#             if duplicates:
#                 st.error("A player is assigned to more than one slot. Fix the duplicate before confirming.")

#             st.divider()
#             b1, b2, b3 = st.columns(3)
#             if b1.button("🔄 Regenerate Suggestion"):
#                 available_records = session_df[session_df["id"].isin(checked_in_ids)].merge(
#                     players_df[["id", "name", "rating"]], on="id"
#                 ).to_dict("records")
#                 courts2, bench2 = build_matchups(available_records, len(courts))
#                 st.session_state["mm_courts"] = courts2
#                 st.session_state["mm_bench"] = bench2
#                 st.session_state["mm_gen"] += 1
#                 st.rerun()
#             if b2.button("◀ Back to Check-in"):
#                 st.session_state["mm_stage"] = "checkin"
#                 st.rerun()
#             if b3.button("✅ Confirm Matchups", type="primary", disabled=duplicates):
#                 session_df = apply_round_result(session_df, assigned_ids, bench_ids)
#                 st.session_state["mm_active_courts"] = new_courts
#                 st.session_state["mm_stage"] = "scoring"
#                 st.rerun()

#         # ---- Stage 3: Scoring ---------------------------------------------
#         elif st.session_state["mm_stage"] == "scoring":
#             st.subheader(f"Round {st.session_state['mm_round']} — Enter Scores")
#             active_courts = st.session_state["mm_active_courts"]

#             score_inputs = []
#             for i, court in enumerate(active_courts):
#                 t1_names = " / ".join(info.loc[pid, "name"] for pid in court["team1"])
#                 t2_names = " / ".join(info.loc[pid, "name"] for pid in court["team2"])
#                 st.markdown(f"**Court {i + 1}:** {t1_names} vs {t2_names}")
#                 c1, c2 = st.columns(2)
#                 s1 = c1.number_input(f"{t1_names} score", min_value=0, step=1, value=11, key=f"score_{i}_t1")
#                 s2 = c2.number_input(f"{t2_names} score", min_value=0, step=1, value=0, key=f"score_{i}_t2")
#                 score_inputs.append((court["team1"], court["team2"], s1, s2))

#             st.divider()
#             b1, b2, b3 = st.columns(3)
#             if b1.button("◀ Edit Matchups Again"):
#                 st.session_state["mm_stage"] = "review"
#                 st.rerun()
#             if b2.button("⏭ Skip Recording Scores"):
#                 st.session_state["mm_stage"] = "checkin"
#                 st.session_state["mm_round"] += 1
#                 st.rerun()
#             if b3.button("🏁 Submit Scores & Finish Round", type="primary"):
#                 errors = []
#                 recorded = 0
#                 for team1_ids, team2_ids, s1, s2 in score_inputs:
#                     success, msg = record_match(team1_ids, team2_ids, int(s1), int(s2), date.today())
#                     if not success:
#                         errors.append(msg)
#                     else:
#                         recorded += 1
#                 if errors:
#                     for e in errors:
#                         st.error(e)
#                 else:
#                     flash("success", f"✅ Round {st.session_state['mm_round']} complete — {recorded} score(s) recorded and ratings updated.")
#                     st.session_state["mm_stage"] = "checkin"
#                     st.session_state["mm_round"] += 1
#                     st.rerun()

# # ---- Leaderboard ------------------------------------------------------------
# elif page == "Leaderboard":
#     st.header("Leaderboard")
#     players_df = load_players()
#     matches_df = load_matches()
#     # The leaderboard only shows active, real (non-guest) players.
#     df = players_df[players_df["active"] & ~players_df["is_guest"]].copy()

#     if df.empty:
#         st.info("No players yet. Add some players to get started!")
#     else:
#         for col in ["rating", "wins", "losses"]:
#             df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

#         df["Games"] = df["wins"] + df["losses"]
#         df["Win %"] = (df["wins"] / df["Games"] * 100).round(1)

#         partner_stats = compute_partner_opponent_stats(players_df, matches_df)
#         df["Avg Partner Rating"] = df["id"].map(lambda pid: partner_stats[pid]["partner_avg"])
#         df["Partner Δ"] = df["Avg Partner Rating"] - df["rating"]
#         df["Boosted?"] = df["Partner Δ"].apply(
#             lambda d: "⚠️ Yes" if pd.notna(d) and d > PARTNER_BOOST_THRESHOLD else ""
#         )

#         df = df.sort_values("rating", ascending=False).reset_index(drop=True)
#         df.insert(0, "Rank", df.index + 1)
#         display_df = df[
#             ["Rank", "name", "rating", "wins", "losses", "Games", "Win %", "Avg Partner Rating", "Boosted?"]
#         ].rename(columns={"name": "Player", "rating": "Rating"})
#         display_df["Rating"] = display_df["Rating"].round(1)
#         display_df["Avg Partner Rating"] = display_df["Avg Partner Rating"].round(1)
#         st.dataframe(display_df, use_container_width=True, hide_index=True)
#         st.caption(
#             "**Boosted?** flags players whose average partner is rated "
#             f"{PARTNER_BOOST_THRESHOLD}+ points above their own rating — their record may be "
#             "propped up by consistently strong teammates rather than their own play. "
#             "Partner ratings use each player's *current* rating, not a historical snapshot."
#         )

#         st.subheader("Rating Comparison")
#         chart_df = df.set_index("name")[["rating"]].rename(columns={"rating": "Rating"})
#         chart_df["Rating"] = pd.to_numeric(chart_df["Rating"], errors="coerce")
#         st.bar_chart(chart_df)

# # ---- Add Player -------------------------------------------------------------
# elif page == "Add Player":
#     st.header("Add a New Player")
#     st.write("Manually enter a player's name to add them to the system. Everyone starts at a rating of 1000.")
#     with st.form("add_player_form", clear_on_submit=True):
#         name = st.text_input("Player name")
#         submitted = st.form_submit_button("Add Player")
#         if submitted:
#             success, msg = add_player(name)
#             if success:
#                 st.success(msg)
#             else:
#                 st.error(msg)

#     st.write("Need an extra body to fill out a court? Guests are always rated exactly 1000 and never affect the leaderboard.")
#     if st.button("➕ Add Another Guest Slot"):
#         new_name = add_guest_slot()
#         flash("success", f"Added a new guest slot: '{new_name}'.")
#         st.rerun()

#     st.divider()
#     st.subheader("Active Players")
#     players_df = load_players()
#     active_regular = players_df[players_df["active"] & ~players_df["is_guest"]].sort_values("name")
#     active_guests = players_df[players_df["active"] & players_df["is_guest"]].sort_values("name")

#     if active_regular.empty:
#         st.info("No active players yet.")
#     else:
#         for _, row in active_regular.iterrows():
#             col1, col2 = st.columns([4, 1])
#             col1.write(f"**{row['name']}** — Rating: {row['rating']:.1f} ({int(row['wins'])}W-{int(row['losses'])}L)")
#             if col2.button("Remove", key=f"deactivate_{row['id']}"):
#                 set_player_active(row["id"], False)
#                 flash("success", f"Removed '{row['name']}' from the leaderboard. Their match history is kept.")
#                 st.rerun()

#     if not active_guests.empty:
#         st.caption("Guest slots (always rated 1000, never removed from selection lists):")
#         for _, row in active_guests.iterrows():
#             st.write(f"🎽 **{row['name']}** — locked at rating 1000")

#     inactive_df = players_df[~players_df["active"] & ~players_df["is_guest"]].sort_values("name")
#     if not inactive_df.empty:
#         with st.expander(f"Removed players ({len(inactive_df)})"):
#             st.write("These players are hidden from the leaderboard and pickers, but their past matches are still in Match History.")
#             for _, row in inactive_df.iterrows():
#                 col1, col2 = st.columns([4, 1])
#                 col1.write(f"{row['name']} — Rating: {row['rating']:.1f}")
#                 if col2.button("Restore", key=f"reactivate_{row['id']}"):
#                     set_player_active(row["id"], True)
#                     flash("success", f"Restored '{row['name']}' to the leaderboard.")
#                     st.rerun()

# # ---- Record Match -----------------------------------------------------------
# elif page == "Record Match":
#     st.header("Record a Doubles Match")
#     st.write("Pick the four players and manually enter the final score.")
#     players_df = load_players()
#     active_df = players_df[players_df["active"]]

#     if len(active_df) < 4:
#         st.warning("You need at least 4 active players before you can record a doubles match.")
#     else:
#         names = active_df.sort_values("name")["name"].tolist()
#         name_to_id = dict(zip(active_df["name"], active_df["id"]))

#         st.subheader("Team 1")
#         c1, c2 = st.columns(2)
#         t1p1 = c1.selectbox("Player 1", names, key="t1p1")
#         t1p2 = c2.selectbox("Player 2", [n for n in names if n != t1p1], key="t1p2")

#         st.subheader("Team 2")
#         remaining = [n for n in names if n not in (t1p1, t1p2)]
#         c3, c4 = st.columns(2)
#         t2p1 = c3.selectbox("Player 1", remaining, key="t2p1")
#         t2p2 = c4.selectbox(
#             "Player 2", [n for n in remaining if n != t2p1], key="t2p2"
#         )

#         st.subheader("Score")
#         c5, c6 = st.columns(2)
#         score1 = c5.number_input(f"{t1p1} / {t1p2} score", min_value=0, step=1, value=11)
#         score2 = c6.number_input(f"{t2p1} / {t2p2} score", min_value=0, step=1, value=0)

#         match_date = st.date_input("Match date", value=date.today())

#         if st.button("Submit Match", type="primary"):
#             team1_ids = [name_to_id[t1p1], name_to_id[t1p2]]
#             team2_ids = [name_to_id[t2p1], name_to_id[t2p2]]
#             success, msg = record_match(team1_ids, team2_ids, int(score1), int(score2), match_date)
#             if success:
#                 flash("success", msg)
#                 st.rerun()
#             else:
#                 st.error(msg)

# # ---- Match History -----------------------------------------------------------
# elif page == "Match History":
#     st.header("Match History")
#     df = get_matches_display_df()
#     if df.empty:
#         st.info("No matches recorded yet.")
#     else:
#         st.dataframe(df, use_container_width=True, hide_index=True)

# # ---- Player Profile -----------------------------------------------------------
# elif page == "Player Profile":
#     st.header("Player Profile")
#     players_df = load_players()
#     profile_df = players_df[players_df["active"] & ~players_df["is_guest"]]
#     if profile_df.empty:
#         st.info("No players yet.")
#     else:
#         name = st.selectbox("Select a player", profile_df.sort_values("name")["name"].tolist())
#         row = profile_df[profile_df["name"] == name].iloc[0]
#         games = row["wins"] + row["losses"]
#         win_pct = (row["wins"] / games * 100) if games else 0

#         m1, m2, m3, m4 = st.columns(4)
#         m1.metric("Rating", f"{row['rating']:.1f}")
#         m2.metric("Wins", int(row["wins"]))
#         m3.metric("Losses", int(row["losses"]))
#         m4.metric("Win %", f"{win_pct:.1f}%")

#         matches_df = load_matches()
#         partner_stats = compute_partner_opponent_stats(players_df, matches_df)
#         pstat = partner_stats.get(int(row["id"]), {"partner_avg": None, "opponent_avg": None, "n": 0})

#         st.subheader("Strength of Schedule")
#         p1, p2 = st.columns(2)
#         if pstat["partner_avg"] is not None:
#             p1.metric("Avg. Partner Rating", f"{pstat['partner_avg']:.1f}")
#             p2.metric("Avg. Opponent Rating", f"{pstat['opponent_avg']:.1f}")
#             diff = pstat["partner_avg"] - row["rating"]
#             if diff > PARTNER_BOOST_THRESHOLD:
#                 st.warning(
#                     f"This player's average partner is rated {diff:.0f} points above their own rating. "
#                     "Their record may be partly boosted by consistently strong teammates rather than their own play."
#                 )
#             elif diff < -PARTNER_BOOST_THRESHOLD:
#                 st.info(
#                     f"This player's average partner is rated {abs(diff):.0f} points below their own rating — "
#                     "they've generally had to carry weaker teams."
#                 )
#             st.caption("Based on partners'/opponents' *current* ratings, not a historical snapshot from when each match was played.")
#         else:
#             st.info("No matches recorded yet for this player.")

#         st.subheader(f"{name}'s Match History")
#         player_id = int(row["id"])
#         if matches_df.empty:
#             st.info("No matches yet for this player.")
#         else:
#             mask = (
#                 (matches_df["team1_p1"] == player_id)
#                 | (matches_df["team1_p2"] == player_id)
#                 | (matches_df["team2_p1"] == player_id)
#                 | (matches_df["team2_p2"] == player_id)
#             )
#             raw = matches_df[mask].sort_values("id", ascending=False).copy()
#             if raw.empty:
#                 st.info("No matches yet for this player.")
#             else:
#                 player_map = get_player_map(players_df)
#                 raw["Team 1"] = raw["team1_p1"].map(player_map) + " / " + raw["team1_p2"].map(player_map)
#                 raw["Team 2"] = raw["team2_p1"].map(player_map) + " / " + raw["team2_p2"].map(player_map)
#                 raw["Score"] = raw["score1"].astype(int).astype(str) + " - " + raw["score2"].astype(int).astype(str)
#                 raw["Result"] = raw.apply(
#                     lambda r: "Win" if (
#                         (player_id in (r["team1_p1"], r["team1_p2"]) and r["winning_team"] == 1)
#                         or (player_id in (r["team2_p1"], r["team2_p2"]) and r["winning_team"] == 2)
#                     ) else "Loss",
#                     axis=1,
#                 )
#                 st.dataframe(
#                     raw[["date", "Team 1", "Team 2", "Score", "Result"]].rename(
#                         columns={"date": "Date"}
#                     ),
#                     use_container_width=True,
#                     hide_index=True,
#                 )

# # ---- Sidebar info ------------------------------------------------------------
# st.sidebar.divider()
# st.sidebar.caption(
#     "Data files:\n"
#     f"- `{PLAYERS_CSV}`\n"
#     f"- `{MATCHES_CSV}`\n"
#     f"- `{SESSION_CSV}`\n\n"
#     "Delete these files to reset all data."
# )
"""
Pickleball Doubles Ranking App (Google Sheets edition)
---------------------------------------------
A Streamlit app for manually entering doubles pickleball players and match
scores, tracking records, ranking players with an Elo-style rating, and
generating fair, skill-balanced matchups for a day of open play.

Run with:
    streamlit run app.py

All data is stored in a shared Google Sheet (not local files — see the
"Google Sheets storage backend" section below and secrets.toml.example),
with one worksheet tab per table:
    players        -> id, name, rating, wins, losses, active, is_guest
    matches        -> id, date, team1_p1, team1_p2, team2_p1, team2_p2,
                       score1, score2, winning_team, rating_change
    session        -> id, checked_in, games_today, sitouts_today, date
                       (today's rotation tracking — who's here, and how
                       many games/sit-outs they've had today)
    seasons, season_players, season_matches, season_backup_*
                   -> season archive/undo bookkeeping (see start_new_season)

Storing data in Sheets (instead of local CSVs) means it survives redeploys
and restarts on hosts with an ephemeral filesystem, like Streamlit
Community Cloud — and you get a normal spreadsheet you can open, filter,
and back up directly in Google Sheets any time.
"""

import itertools
import random
from datetime import date

import altair as alt
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# Every "tab" below used to be its own CSV file; it's now a worksheet tab in
# one shared Google Sheet (see the Google Sheets storage backend further
# down), addressed by the spreadsheet ID in st.secrets. Renamed from *_CSV
# to *_TAB since these are now worksheet names, not filenames.
PLAYERS_TAB = "players"
MATCHES_TAB = "matches"
SESSION_TAB = "session"

# Season archive tabs. The live players/matches tabs above always hold only
# the *current* season; "New Season / Reset" snapshots them into these
# archive tabs before clearing them out for a fresh start.
SEASONS_TAB = "seasons"
SEASON_PLAYERS_TAB = "season_players"
SEASON_MATCHES_TAB = "season_matches"

# One-shot backup of the live tabs taken right before a reset, so an
# accidental "New Season / Reset" can be undone. Cleared once used, or once
# superseded by the next reset.
SEASON_BACKUP_PLAYERS_TAB = "season_backup_players"
SEASON_BACKUP_MATCHES_TAB = "season_backup_matches"
SEASON_BACKUP_META_TAB = "season_backup_meta"

PLAYERS_COLUMNS = ["id", "name", "rating", "wins", "losses", "active", "is_guest"]
MATCHES_COLUMNS = [
    "id", "date", "team1_p1", "team1_p2", "team2_p1", "team2_p2",
    "score1", "score2", "winning_team", "rating_change",
]
SESSION_COLUMNS = ["id", "checked_in", "games_today", "sitouts_today", "date"]

SEASONS_COLUMNS = ["season_id", "label", "start_date", "end_date"]
SEASON_PLAYERS_COLUMNS = ["season_id", "player_id", "name", "rating", "wins", "losses", "is_guest"]
SEASON_MATCHES_COLUMNS = ["season_id"] + MATCHES_COLUMNS

# Every tab's column order, in one place — the source of truth the Sheets
# backend uses to create a tab, read one back with the right shape, and
# write one out.
SHEET_COLUMNS = {
    PLAYERS_TAB: PLAYERS_COLUMNS,
    MATCHES_TAB: MATCHES_COLUMNS,
    SESSION_TAB: SESSION_COLUMNS,
    SEASONS_TAB: SEASONS_COLUMNS,
    SEASON_PLAYERS_TAB: SEASON_PLAYERS_COLUMNS,
    SEASON_MATCHES_TAB: SEASON_MATCHES_COLUMNS,
    SEASON_BACKUP_PLAYERS_TAB: PLAYERS_COLUMNS,
    SEASON_BACKUP_MATCHES_TAB: MATCHES_COLUMNS,
    SEASON_BACKUP_META_TAB: ["season_id"],
}

K_FACTOR = 32
STARTING_RATING = 1000
GUEST_NAME = "Guest"

# ----------------------------------------------------------------------------
# Google Sheets storage backend
# ----------------------------------------------------------------------------
#
# Everything in this app used to read/write local CSV files directly. That
# doesn't survive a redeploy or restart on most free hosts (Streamlit
# Community Cloud included — its filesystem is ephemeral), so all storage
# now goes through one shared Google Sheet instead: each "tab" above is a
# worksheet in it. This section is the *only* place that knows about
# gspread/Sheets — every load_*/save_* function elsewhere in the app just
# calls _read_tab/_write_tab below and has no idea the data isn't local
# disk anymore.
#
# Requires two things in Streamlit secrets (see secrets.toml.example):
#   [gcp_service_account]   — the full service-account JSON key, as a table
#   spreadsheet_id = "..."  — the target spreadsheet's ID (from its URL)
# The spreadsheet must be shared (Editor access) with the service account's
# client_email.

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@st.cache_resource(show_spinner=False)
def _gspread_client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SHEETS_SCOPES
    )
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _spreadsheet():
    return _gspread_client().open_by_key(st.secrets["spreadsheet_id"])


def _get_worksheet(tab_name):
    """Return the worksheet for `tab_name`, creating it (with just a header
    row) the first time it's needed. Mirrors the old init_csvs() behavior
    of only creating a file if it's missing — an existing tab's data is
    never touched here."""
    sh = _spreadsheet()
    try:
        return sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        columns = SHEET_COLUMNS[tab_name]
        ws = sh.add_worksheet(title=tab_name, rows=200, cols=max(len(columns), 1))
        ws.update(values=[columns], range_name="A1")
        return ws


@st.cache_data(ttl=8, show_spinner=False)
def _read_tab(tab_name):
    """Read a worksheet into a DataFrame shaped exactly like
    SHEET_COLUMNS[tab_name] (missing columns added empty), same as the old
    self-healing CSV loaders. Cached briefly so clicking around the app
    doesn't re-hit the Sheets API on every single rerun."""
    ws = _get_worksheet(tab_name)
    records = ws.get_all_records()
    columns = SHEET_COLUMNS[tab_name]
    df = pd.DataFrame(records)
    for col in columns:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    return df[columns] if not df.empty else pd.DataFrame(columns=columns)


def _write_tab(tab_name, df):
    """Overwrite a worksheet's contents with `df`, then clear the read
    cache so the very next load sees the fresh data."""
    ws = _get_worksheet(tab_name)
    columns = SHEET_COLUMNS[tab_name]
    df = df.reindex(columns=columns)
    body = df.astype(object).where(pd.notna(df), "").values.tolist()
    ws.clear()
    ws.update(values=[columns] + body, range_name="A1")
    _read_tab.clear()



# A guest's rating is fixed (never moved by match results), but it no longer
# has to be exactly 1000 — pick a starting point that reflects how strong a
# fill-in player actually is, so team-average Elo math for the *real* players
# in their match stays fair.
GUEST_RATING_OPTIONS = [1050, 1000, 950, 900]

# "T-shirt size" starting ratings for a new season, keyed off each player's
# rank (by final rating) at the end of the season being archived. Applied
# top-down: a player in the top `percentile` fraction of *that season's*
# ranked, active participants gets `rating`. The last tier's percentile
# should be 1.0 so everyone is covered. Players who didn't play a single
# match last season have no performance to rank, so they always start the
# new season at STARTING_RATING regardless of these tiers.
SEASON_START_TIERS = [
    {"label": "Top", "percentile": 0.25, "rating": 1050},
    {"label": "Middle", "percentile": 0.75, "rating": 1000},
    {"label": "Bottom", "percentile": 1.0, "rating": 950},
]

# Matchmaking tuning knobs:
# If a court's rating spread (max - min of its 4 players) is above this,
# the algorithm looks for a better-fitting bench player to swap in.
RATING_SPREAD_THRESHOLD = 200
# A bench player is only "eligible" to be swapped in for fairness reasons if
# their priority-to-play score is within this many points of the outlier
# they'd replace. Keeps skill-based swaps from being too unfair to the
# person being benched.
FAIRNESS_TOLERANCE = 1.5

# A player whose average partner is rated more than this many points above
# their own rating gets flagged — their rating may be partly propped up by
# consistently strong teammates rather than their own play.
PARTNER_BOOST_THRESHOLD = 100

# ----------------------------------------------------------------------------
# CSV storage helpers — players & matches
# ----------------------------------------------------------------------------

def _parse_bool_column(series, default):
    """Robustly parse a CSV column of True/False (or missing) into real bools."""
    mapped = series.astype(str).str.strip().str.lower().map({"true": True, "false": False})
    return mapped.fillna(default)


def init_storage():
    """Make sure every tab exists in the spreadsheet, creating any that are
    missing. Never touches a tab that's already there."""
    for tab_name in SHEET_COLUMNS:
        _get_worksheet(tab_name)


def load_players():
    """Load the players tab, self-healing older data that predates the
    active/is_guest columns, and enforcing the "Guest is never ranked
    (no wins/losses)" rule on every load. A guest's rating is fixed but
    adjustable — see GUEST_RATING_OPTIONS — not hardcoded to 1000.
    """
    df = _read_tab(PLAYERS_TAB)
    for col in PLAYERS_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")

    if df.empty:
        return df

    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype(int)
    # Always float64: whole-number ratings (e.g. a fresh 1000) otherwise
    # round-trip through the Sheet/pd.to_numeric as int64, which later
    # raises the first time a match produces a fractional Elo delta.
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(STARTING_RATING).astype(float)
    df["wins"] = pd.to_numeric(df["wins"], errors="coerce").fillna(0).astype(int)
    df["losses"] = pd.to_numeric(df["losses"], errors="coerce").fillna(0).astype(int)
    df["active"] = _parse_bool_column(df["active"], default=True)
    df["is_guest"] = _parse_bool_column(df["is_guest"], default=False)

    # Auto-migrate: if the data already has a player literally named
    # "Guest" (any case) but no is_guest flag yet, treat it as the guest.
    df.loc[df["name"].astype(str).str.strip().str.lower() == "guest", "is_guest"] = True

    # A guest is never individually ranked: no win/loss record, regardless of
    # what happened to have been written to the sheet. Their rating, however,
    # is now a fixed-but-adjustable value (see GUEST_RATING_OPTIONS) rather
    # than being forced back to STARTING_RATING on every load.
    guest_mask = df["is_guest"]
    df.loc[guest_mask, "wins"] = 0
    df.loc[guest_mask, "losses"] = 0

    return df


def save_players(df):
    _write_tab(PLAYERS_TAB, df)


def ensure_guest_exists():
    """Guarantee a global Guest player always exists, auto-creating one if
    needed. Called at startup so it's always available without any manual
    setup — a permanent 1000-rated slot for filling in a court."""
    df = load_players()
    if df.empty or not df["is_guest"].any():
        new_row = {
            "id": next_id(df),
            "name": GUEST_NAME,
            "rating": STARTING_RATING,
            "wins": 0,
            "losses": 0,
            "active": True,
            "is_guest": True,
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        save_players(df)


def add_guest_slot(rating=STARTING_RATING):
    """Add an additional guest (Guest 2, Guest 3, ...) for days when more
    than one fill-in player is needed at once. `rating` sets their fixed
    rating (see GUEST_RATING_OPTIONS) — it's never moved by match results,
    but it does feed into team-average Elo math for the real players in
    their matches, so picking a realistic value matters."""
    df = load_players()
    n = 1
    existing_names = set(df["name"].str.lower()) if not df.empty else set()
    name = GUEST_NAME
    while name.lower() in existing_names:
        n += 1
        name = f"{GUEST_NAME} {n}"
    new_row = {
        "id": next_id(df),
        "name": name,
        "rating": rating,
        "wins": 0,
        "losses": 0,
        "active": True,
        "is_guest": True,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_players(df)
    return name


def set_guest_rating(player_id, rating):
    """Change a guest's fixed rating (e.g. from 1000 to 950). No-op safety
    check keeps this from ever touching a non-guest player's rating."""
    df = load_players()
    df = df.set_index("id")
    if player_id not in df.index or not bool(df.loc[player_id, "is_guest"]):
        return False, "That player isn't a guest."
    df.loc[player_id, "rating"] = rating
    df = df.reset_index()
    save_players(df)
    return True, "Guest rating updated."


def load_matches():
    df = _read_tab(MATCHES_TAB)
    for col in MATCHES_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    if not df.empty:
        df["id"] = pd.to_numeric(df["id"], errors="coerce").astype(int)
        for col in ("team1_p1", "team1_p2", "team2_p1", "team2_p2", "score1", "score2", "winning_team"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        # Always float64, for the same reason as players' rating column (see
        # load_players): a whole-number value round-trips through the sheet
        # as int64 otherwise, which then raises on the next fractional value.
        df["rating_change"] = pd.to_numeric(df["rating_change"], errors="coerce").fillna(0.0).astype(float)
        df["date"] = df["date"].astype(str)
    return df


def save_matches(df):
    _write_tab(MATCHES_TAB, df)


def next_id(df):
    if df.empty:
        return 1
    return int(df["id"].max()) + 1


def get_player_map(players_df):
    """Maps id -> name for ALL players, including inactive ones, so past
    matches involving a since-removed player still display correctly."""
    return dict(zip(players_df["id"], players_df["name"]))


def add_player(name):
    name = name.strip()
    if not name:
        return False, "Please enter a name."
    if name.lower().startswith("guest"):
        return False, "That name is reserved for guest players — use the 'Add Guest' button instead."
    players_df = load_players()
    if not players_df.empty and name.lower() in players_df["name"].str.lower().values:
        return False, f"Player '{name}' already exists."
    new_row = {
        "id": next_id(players_df),
        "name": name,
        "rating": STARTING_RATING,
        "wins": 0,
        "losses": 0,
        "active": True,
        "is_guest": False,
    }
    players_df = pd.concat([players_df, pd.DataFrame([new_row])], ignore_index=True)
    save_players(players_df)
    return True, f"Added player '{name}'."


def set_player_active(player_id, active):
    players_df = load_players()
    players_df.loc[players_df["id"] == player_id, "active"] = active
    save_players(players_df)


# ----------------------------------------------------------------------------
# Storage helpers — season archive
# ----------------------------------------------------------------------------
#
# The players / matches tabs always represent the *current* season only.
# "New Season / Reset" (see start_new_season) snapshots them into the
# archive tabs below, then clears the live tabs for a fresh start — so
# every current-season calculation elsewhere in the app automatically only
# ever sees current-season matches, with no extra filtering needed.

def load_seasons():
    df = _read_tab(SEASONS_TAB)
    for col in SEASONS_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    if not df.empty:
        df["season_id"] = pd.to_numeric(df["season_id"], errors="coerce").astype(int)
    return df


def save_seasons(df):
    _write_tab(SEASONS_TAB, df)


def load_season_players():
    df = _read_tab(SEASON_PLAYERS_TAB)
    for col in SEASON_PLAYERS_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    if not df.empty:
        df["season_id"] = pd.to_numeric(df["season_id"], errors="coerce").astype(int)
        df["player_id"] = pd.to_numeric(df["player_id"], errors="coerce").astype(int)
        df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(STARTING_RATING)
        df["wins"] = pd.to_numeric(df["wins"], errors="coerce").fillna(0).astype(int)
        df["losses"] = pd.to_numeric(df["losses"], errors="coerce").fillna(0).astype(int)
        df["is_guest"] = _parse_bool_column(df["is_guest"], default=False)
    return df


def save_season_players(df):
    _write_tab(SEASON_PLAYERS_TAB, df)


def load_season_matches():
    df = _read_tab(SEASON_MATCHES_TAB)
    for col in SEASON_MATCHES_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    if not df.empty:
        df["season_id"] = pd.to_numeric(df["season_id"], errors="coerce").astype(int)
    return df


def save_season_matches(df):
    _write_tab(SEASON_MATCHES_TAB, df)


def current_season_number():
    """The season currently in progress — one past however many seasons
    have already been archived. There's no separate counter to keep in
    sync; this is always derived from the archive itself."""
    return len(load_seasons()) + 1


def has_undoable_reset():
    return not _read_tab(SEASON_BACKUP_META_TAB).empty


def compute_tiered_start_ratings(players_df):
    """T-shirt-size starting ratings for the upcoming season, based on how
    each player ranked (by rating) among *active participants* at the end
    of the season now ending. See SEASON_START_TIERS.

    Only non-guest players who played at least one match this season are
    ranked — someone who sat the whole season out has no performance to
    base a tier on, so they (and guests) fall through to STARTING_RATING.

    Returns {player_id: new_rating} for every non-guest player.
    """
    ranked = players_df[
        (~players_df["is_guest"]) & ((players_df["wins"] + players_df["losses"]) > 0)
    ].sort_values("rating", ascending=False).reset_index(drop=True)

    n = len(ranked)
    tiered = {}
    for i, row in ranked.iterrows():
        rank_percentile = (i + 1) / n  # 1st place -> smallest percentile
        rating = SEASON_START_TIERS[-1]["rating"]
        for tier in SEASON_START_TIERS:
            if rank_percentile <= tier["percentile"]:
                rating = tier["rating"]
                break
        tiered[int(row["id"])] = rating

    # Everyone else (didn't play this season, or is a guest) starts flat.
    for pid in players_df["id"]:
        if int(pid) not in tiered:
            tiered[int(pid)] = STARTING_RATING

    return tiered


def start_new_season(start_mode="flat"):
    """Archive the current season's players and matches, then reset the
    live files for a fresh start.

    Historical wins/losses/ratings/match counts are preserved forever in
    the season archive (see the Previous Seasons tab) — only the *live*
    players.csv/matches.csv are reset, so current-season leaderboards,
    streaks, etc. start from a clean slate. Guests keep whatever fixed
    rating was dialed in for them, since that's a manual setting rather
    than a season-earned stat.

    start_mode:
      "flat"   — every non-guest player resets to STARTING_RATING (1000).
      "tiered" — non-guest players start at a "t-shirt size" rating based
                 on where they ranked this season (see SEASON_START_TIERS
                 / compute_tiered_start_ratings).
    """
    players_df = load_players()
    matches_df = load_matches()

    if matches_df.empty:
        return False, "There are no matches recorded this season yet — nothing to archive."

    seasons_df = load_seasons()
    season_id = int(len(seasons_df) + 1)
    start_date = matches_df["date"].astype(str).min()
    end_date = date.today().isoformat()

    # Snapshot the live files *before* changing anything, so an accidental
    # reset can be undone (see undo_last_reset). This overwrites any
    # earlier backup — only the most recent reset can be undone.
    _write_tab(SEASON_BACKUP_PLAYERS_TAB, players_df)
    _write_tab(SEASON_BACKUP_MATCHES_TAB, matches_df)
    _write_tab(SEASON_BACKUP_META_TAB, pd.DataFrame([{"season_id": season_id}]))

    # Archive season metadata.
    season_row = {"season_id": season_id, "label": f"Season {season_id}", "start_date": start_date, "end_date": end_date}
    seasons_df = pd.concat([seasons_df, pd.DataFrame([season_row])], ignore_index=True)
    save_seasons(seasons_df)

    # Archive every player's final standing for the season.
    snapshot = players_df.copy().rename(columns={"id": "player_id"})
    snapshot["season_id"] = season_id
    snapshot = snapshot[SEASON_PLAYERS_COLUMNS]
    season_players_df = load_season_players()
    season_players_df = pd.concat([season_players_df, snapshot], ignore_index=True)
    save_season_players(season_players_df)

    # Archive every match played this season.
    season_matches_snapshot = matches_df.copy()
    season_matches_snapshot["season_id"] = season_id
    season_matches_snapshot = season_matches_snapshot[SEASON_MATCHES_COLUMNS]
    season_matches_df = load_season_matches()
    season_matches_df = pd.concat([season_matches_df, season_matches_snapshot], ignore_index=True)
    save_season_matches(season_matches_df)

    # Reset the live files. Real players go back to a blank slate (flat, or
    # tiered by last season's final standings); guests are untouched
    # (their rating isn't season-earned).
    reset_df = players_df.copy()
    non_guest = ~reset_df["is_guest"]
    if start_mode == "tiered":
        tiered_ratings = compute_tiered_start_ratings(players_df)
        reset_df.loc[non_guest, "rating"] = reset_df.loc[non_guest, "id"].map(tiered_ratings).astype(float)
    else:
        reset_df.loc[non_guest, "rating"] = float(STARTING_RATING)
    reset_df.loc[non_guest, "wins"] = 0
    reset_df.loc[non_guest, "losses"] = 0
    save_players(reset_df)
    save_matches(pd.DataFrame(columns=MATCHES_COLUMNS))

    mode_desc = "tiered starting ratings based on final standings" if start_mode == "tiered" else "a flat reset to 1000"
    return True, f"Season {season_id} archived. Season {season_id + 1} starts now with {mode_desc}."


def undo_last_reset():
    """Restore players/matches to exactly how they were right before the
    most recent 'New Season / Reset', and remove the archive entries that
    reset created. Only the single most recent reset can be undone, and
    only once — any matches or players added after the reset will be
    lost."""
    if not has_undoable_reset():
        return False, "There's no recent reset to undo."

    meta = _read_tab(SEASON_BACKUP_META_TAB)
    season_id = int(meta.iloc[0]["season_id"])

    backup_players = _read_tab(SEASON_BACKUP_PLAYERS_TAB)
    backup_matches = _read_tab(SEASON_BACKUP_MATCHES_TAB)
    save_players(backup_players)
    save_matches(backup_matches)

    seasons_df = load_seasons()
    save_seasons(seasons_df[seasons_df["season_id"] != season_id])

    season_players_df = load_season_players()
    save_season_players(season_players_df[season_players_df["season_id"] != season_id])

    season_matches_df = load_season_matches()
    save_season_matches(season_matches_df[season_matches_df["season_id"] != season_id])

    for tab_name in (SEASON_BACKUP_PLAYERS_TAB, SEASON_BACKUP_MATCHES_TAB, SEASON_BACKUP_META_TAB):
        _write_tab(tab_name, pd.DataFrame(columns=SHEET_COLUMNS[tab_name]))

    return True, f"Season {season_id}'s reset has been undone — players and matches are back to how they were."


# ----------------------------------------------------------------------------
# Storage helpers — today's session (check-ins & rotation tracking)
# ----------------------------------------------------------------------------

def load_session_raw():
    df = _read_tab(SESSION_TAB)
    for col in SESSION_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype="object")
    if not df.empty:
        df["id"] = pd.to_numeric(df["id"], errors="coerce").astype(int)
        df["checked_in"] = _parse_bool_column(df["checked_in"], default=False)
        df["games_today"] = pd.to_numeric(df["games_today"], errors="coerce").fillna(0).astype(int)
        df["sitouts_today"] = pd.to_numeric(df["sitouts_today"], errors="coerce").fillna(0).astype(int)
        df["date"] = df["date"].astype(str)
    return df


def save_session(df):
    _write_tab(SESSION_TAB, df)


def sync_session(players_df):
    """Keep session.csv in sync with the player roster and the calendar day.

    - Adds a row for any player who doesn't have one yet (defaults to not
      checked in, 0 games/sit-outs today).
    - Drops rows for players that no longer exist at all.
    - If the stored date isn't today, resets everyone's check-in status and
      today's counts — a fresh day of open play starts from zero.
    """
    today_str = date.today().isoformat()
    df = load_session_raw()

    if df.empty:
        rows = [
            {"id": pid, "checked_in": False, "games_today": 0, "sitouts_today": 0, "date": today_str}
            for pid in players_df["id"]
        ]
        df = pd.DataFrame(rows, columns=SESSION_COLUMNS)
    else:
        current_date = df["date"].iloc[0]
        if current_date != today_str:
            df["checked_in"] = False
            df["games_today"] = 0
            df["sitouts_today"] = 0
            df["date"] = today_str

        existing_ids = set(df["id"])
        new_ids = [pid for pid in players_df["id"] if pid not in existing_ids]
        if new_ids:
            new_rows = pd.DataFrame(
                [
                    {"id": pid, "checked_in": False, "games_today": 0, "sitouts_today": 0, "date": today_str}
                    for pid in new_ids
                ]
            )
            df = pd.concat([df, new_rows], ignore_index=True)

        df = df[df["id"].isin(players_df["id"])].reset_index(drop=True)

    save_session(df)
    return df


def set_checked_in(session_df, checked_in_ids):
    """Overwrite checked_in flags to exactly match the given set of ids."""
    session_df = session_df.copy()
    session_df["checked_in"] = session_df["id"].isin(checked_in_ids)
    save_session(session_df)
    return session_df


def apply_round_result(session_df, playing_ids, sitting_ids):
    session_df = session_df.copy()
    session_df.loc[session_df["id"].isin(playing_ids), "games_today"] += 1
    session_df.loc[session_df["id"].isin(sitting_ids), "sitouts_today"] += 1
    save_session(session_df)
    return session_df


def reset_today_stats(session_df):
    session_df = session_df.copy()
    session_df["games_today"] = 0
    session_df["sitouts_today"] = 0
    save_session(session_df)
    return session_df


# ----------------------------------------------------------------------------
# Elo rating logic for doubles
# ----------------------------------------------------------------------------

def expected_score(team_rating, opp_rating):
    return 1 / (1 + 10 ** ((opp_rating - team_rating) / 400))


def margin_multiplier(score1, score2):
    """Scale the rating change by how lopsided the score was.

    A 11-9 nail-biter barely tells you more than a coin flip did; an 11-1
    blowout is much stronger evidence of a skill gap. This scales the
    rating change from 1.0x (very close game) up to 1.5x (a total
    blowout), based on the margin as a share of total points played.
    """
    total_points = score1 + score2
    if total_points <= 0:
        return 1.0
    margin_ratio = abs(score1 - score2) / total_points
    return 1 + min(margin_ratio, 0.5)


def record_match(team1_ids, team2_ids, score1, score2, match_date):
    """Record a manually entered doubles match result, then replay the
    *entire* current-season match history (see full_recalculation_replay)
    so every stored rating and win/loss record stays fully consistent.

    Guest players (is_guest=True) never have their own rating or win/loss
    record changed by a match — their rating stays fixed at whatever value
    was set when they were added (see GUEST_RATING_OPTIONS) — but they
    still count normally toward their team's average rating for everyone
    else's Elo calculation, exactly like a real opponent/partner at that
    rating would.
    """
    if score1 == score2:
        return False, "Scores can't be tied — pickleball games need a winner."

    players_df = load_players()
    matches_df = load_matches()

    new_id = next_id(matches_df)
    new_match = {
        "id": new_id,
        "date": match_date.isoformat(),
        "team1_p1": team1_ids[0],
        "team1_p2": team1_ids[1],
        "team2_p1": team2_ids[0],
        "team2_p2": team2_ids[1],
        "score1": score1,
        "score2": score2,
        "winning_team": 1,      # placeholder — overwritten by the replay below
        "rating_change": 0.0,   # placeholder — overwritten by the replay below
    }
    matches_df = pd.concat([matches_df, pd.DataFrame([new_match])], ignore_index=True)

    players_df, matches_df = full_recalculation_replay(players_df, matches_df)
    save_players(players_df)
    save_matches(matches_df)

    saved_delta = float(matches_df.loc[matches_df["id"] == new_id, "rating_change"].iloc[0])
    return True, f"Match recorded: {score1}-{score2}. Ratings updated (±{saved_delta:.1f})."


def get_matches_display_df():
    matches_df = load_matches()
    players_df = load_players()
    if matches_df.empty:
        return pd.DataFrame()
    player_map = get_player_map(players_df)
    df = matches_df.copy()
    df["Team 1"] = df["team1_p1"].map(player_map) + " / " + df["team1_p2"].map(player_map)
    df["Team 2"] = df["team2_p1"].map(player_map) + " / " + df["team2_p2"].map(player_map)
    df["Score"] = df["score1"].astype(int).astype(str) + " - " + df["score2"].astype(int).astype(str)
    df["Winner"] = df.apply(
        lambda r: r["Team 1"] if r["winning_team"] == 1 else r["Team 2"], axis=1
    )
    df["Rating +/-"] = df["rating_change"]
    df = df.sort_values("id", ascending=False)
    return df[["date", "Team 1", "Team 2", "Score", "Winner", "Rating +/-"]].rename(
        columns={"date": "Date"}
    )


# ----------------------------------------------------------------------------
# Full recalculation replay
# ----------------------------------------------------------------------------
#
# Ratings are cumulative: each match's Elo delta depends on the ratings
# produced by every match before it. So whenever a match's score/players
# change — or a match is deleted, or a new one is inserted — every match's
# delta from that point forward needs to be recomputed, not just the one
# that was touched. Rather than track that cascade by hand, this simply
# replays the *entire* match history from a blank slate every time, in id
# order (id reflects recording order, which is what ratings were actually
# built on — not necessarily the "date" field, since a match can be
# backfilled with an earlier date). It's cheap at this scale and it's the
# only way to guarantee the stored numbers are always self-consistent.

def full_recalculation_replay(players_df, matches_df):
    """Replay every match in `matches_df`, in id order, recomputing each
    match's Elo delta from scratch based on team ratings *as of that point
    in the replay* — overwriting each match's stored winning_team and
    rating_change as it goes, and rebuilding every non-guest player's
    rating/wins/losses to match.

    Guests never have their own rating/record touched (it's a fixed,
    manually-set value — see GUEST_RATING_OPTIONS), but their fixed rating
    still counts normally toward their team's average for the *other*
    players' Elo math, exactly as it always has.

    Returns (players_df, matches_df), both updated and ready to save.
    """
    players_indexed = players_df.set_index("id").copy()
    non_guest_mask = ~players_indexed["is_guest"]
    players_indexed.loc[non_guest_mask, "rating"] = float(STARTING_RATING)
    players_indexed.loc[non_guest_mask, "wins"] = 0
    players_indexed.loc[non_guest_mask, "losses"] = 0

    ordered = matches_df.sort_values("id").reset_index(drop=True)
    for idx in ordered.index:
        r = ordered.loc[idx]
        team1_ids = [int(r["team1_p1"]), int(r["team1_p2"])]
        team2_ids = [int(r["team2_p1"]), int(r["team2_p2"])]
        score1, score2 = float(r["score1"]), float(r["score2"])

        team1_rating = (players_indexed.loc[team1_ids[0], "rating"] + players_indexed.loc[team1_ids[1], "rating"]) / 2
        team2_rating = (players_indexed.loc[team2_ids[0], "rating"] + players_indexed.loc[team2_ids[1], "rating"]) / 2

        actual1 = 1 if score1 > score2 else 0
        actual2 = 1 - actual1
        exp1 = expected_score(team1_rating, team2_rating)
        exp2 = 1 - exp1

        mult = margin_multiplier(score1, score2)
        delta1 = K_FACTOR * mult * (actual1 - exp1)
        delta2 = K_FACTOR * mult * (actual2 - exp2)
        winning_team = 1 if actual1 == 1 else 2

        for pid in team1_ids:
            if players_indexed.loc[pid, "is_guest"]:
                continue
            players_indexed.loc[pid, "rating"] += delta1
            players_indexed.loc[pid, "wins" if winning_team == 1 else "losses"] += 1
        for pid in team2_ids:
            if players_indexed.loc[pid, "is_guest"]:
                continue
            players_indexed.loc[pid, "rating"] += delta2
            players_indexed.loc[pid, "wins" if winning_team == 2 else "losses"] += 1

        ordered.loc[idx, "winning_team"] = winning_team
        ordered.loc[idx, "rating_change"] = round(abs(delta1), 2)

    return players_indexed.reset_index(), ordered


# ----------------------------------------------------------------------------
# Editing / deleting a match
# ----------------------------------------------------------------------------
#
# Editing is scoped to *today's* matches — or, if nothing was played today,
# the most recent day that has a match on record — so older, long-settled
# history isn't casually rewritten. Whenever a match in that window is
# corrected or deleted, the whole match history is replayed from scratch
# (full_recalculation_replay) so the edited match *and* everything recorded
# after it end up with correct, consistent ratings and records.

def get_editable_day(matches_df):
    """The one calendar day whose matches can currently be edited: today,
    if anything was played today, otherwise the most recent day that has a
    match on record. Returns None if there are no matches at all."""
    if matches_df.empty:
        return None
    today_str = date.today().isoformat()
    dates = matches_df["date"].astype(str)
    if (dates == today_str).any():
        return today_str
    return dates.max()


def get_editable_match_ids(matches_df):
    """IDs of every match that falls on the current editable day (see
    get_editable_day)."""
    day = get_editable_day(matches_df)
    if day is None:
        return []
    return matches_df[matches_df["date"].astype(str) == day]["id"].astype(int).tolist()


def delete_match(match_id):
    """Remove a match and recalculate every match's ratings/records from
    scratch. Only allowed for matches on the current editable day."""
    matches_df = load_matches()
    if match_id not in get_editable_match_ids(matches_df):
        return False, "This match can't be deleted — it isn't on the current editable day."

    matches_df = matches_df[matches_df["id"] != match_id]
    players_df = load_players()
    players_df, matches_df = full_recalculation_replay(players_df, matches_df)
    save_players(players_df)
    save_matches(matches_df)
    return True, "Match deleted. Ratings and records for that match and everything after it have been recalculated."


def edit_match(match_id, new_team1_ids, new_team2_ids, new_score1, new_score2, new_date):
    """Correct a match's players/score/date in place (its id is preserved,
    so its position in the recorded order doesn't change), then
    recalculate every match's ratings/records from scratch. Only allowed
    for matches on the current editable day."""
    if new_score1 == new_score2:
        return False, "Scores can't be tied — pickleball games need a winner."

    matches_df = load_matches()
    if match_id not in get_editable_match_ids(matches_df):
        return False, "This match can't be edited — it isn't on the current editable day."

    idx = matches_df.index[matches_df["id"] == match_id][0]
    matches_df.loc[idx, "team1_p1"] = new_team1_ids[0]
    matches_df.loc[idx, "team1_p2"] = new_team1_ids[1]
    matches_df.loc[idx, "team2_p1"] = new_team2_ids[0]
    matches_df.loc[idx, "team2_p2"] = new_team2_ids[1]
    matches_df.loc[idx, "score1"] = new_score1
    matches_df.loc[idx, "score2"] = new_score2
    matches_df.loc[idx, "date"] = new_date.isoformat()

    players_df = load_players()
    players_df, matches_df = full_recalculation_replay(players_df, matches_df)
    save_players(players_df)
    save_matches(matches_df)
    return True, "Ratings and records for that match and everything after it have been recalculated."


# ----------------------------------------------------------------------------
# Partner/opponent strength metric
# ----------------------------------------------------------------------------

def compute_partner_opponent_stats(players_df, matches_df):
    """For every player, average the CURRENT rating of their teammates and
    opponents across all their recorded matches.

    This uses today's ratings, not a historical snapshot from when each
    match was played, so it's an approximation — but it's a quick way to
    spot a player whose rating looks strong mostly because they keep
    getting paired with stronger partners, not necessarily because of their
    own play.

    Returns a dict: id -> {"partner_avg", "opponent_avg", "n"} (values are
    None if the player has no recorded matches).
    """
    rating_map = dict(zip(players_df["id"], players_df["rating"]))
    stats = {pid: {"partner_sum": 0.0, "opponent_sum": 0.0, "n": 0} for pid in players_df["id"]}

    for _, m in matches_df.iterrows():
        team1 = [int(m["team1_p1"]), int(m["team1_p2"])]
        team2 = [int(m["team2_p1"]), int(m["team2_p2"])]
        for team, opp in ((team1, team2), (team2, team1)):
            opp_avg = (rating_map.get(opp[0], STARTING_RATING) + rating_map.get(opp[1], STARTING_RATING)) / 2
            for i, pid in enumerate(team):
                if pid not in stats:
                    continue
                partner_id = team[1 - i]
                stats[pid]["partner_sum"] += rating_map.get(partner_id, STARTING_RATING)
                stats[pid]["opponent_sum"] += opp_avg
                stats[pid]["n"] += 1

    result = {}
    for pid, s in stats.items():
        if s["n"] > 0:
            result[pid] = {
                "partner_avg": s["partner_sum"] / s["n"],
                "opponent_avg": s["opponent_sum"] / s["n"],
                "n": s["n"],
            }
        else:
            result[pid] = {"partner_avg": None, "opponent_avg": None, "n": 0}
    return result


# ----------------------------------------------------------------------------
# Win streaks
# ----------------------------------------------------------------------------

def compute_streaks(players_df, matches_df):
    """For every player, walk their matches in the order they were recorded
    (by id, which is when ratings were actually applied — not necessarily
    the "date" field, since a match can be backfilled with an earlier date)
    and compute:
      - current_streak / current_type: the run of W's or L's ending at
        their most recent match (current_type is "W", "L", or None).
      - best_win_streak: the longest winning streak they've ever had.

    Returns {id: {"current_streak": int, "current_type": str|None,
    "best_win_streak": int}}.
    """
    ordered = matches_df.sort_values("id")
    sequences = {pid: [] for pid in players_df["id"]}

    for _, m in ordered.iterrows():
        team1 = [int(m["team1_p1"]), int(m["team1_p2"])]
        team2 = [int(m["team2_p1"]), int(m["team2_p2"])]
        winning_team = int(m["winning_team"])
        for pid in team1:
            if pid in sequences:
                sequences[pid].append("W" if winning_team == 1 else "L")
        for pid in team2:
            if pid in sequences:
                sequences[pid].append("W" if winning_team == 2 else "L")

    results = {}
    for pid, seq in sequences.items():
        if not seq:
            results[pid] = {"current_streak": 0, "current_type": None, "best_win_streak": 0}
            continue
        last = seq[-1]
        current = 0
        for r in reversed(seq):
            if r == last:
                current += 1
            else:
                break
        best, run = 0, 0
        for r in seq:
            if r == "W":
                run += 1
                best = max(best, run)
            else:
                run = 0
        results[pid] = {"current_streak": current, "current_type": last, "best_win_streak": best}
    return results


def format_streak(streak_info):
    if not streak_info or streak_info["current_type"] is None:
        return "-"
    icon = "🔥" if streak_info["current_type"] == "W" and streak_info["current_streak"] >= 3 else ""
    return f"{icon}{streak_info['current_streak']}{streak_info['current_type']}".strip()


# ----------------------------------------------------------------------------
# Rating history (for the Player Profile trend chart)
# ----------------------------------------------------------------------------

def compute_rating_history(matches_df, player_id):
    """Reconstruct a player's rating after each of their matches, in
    chronological (match id) order.

    There's no stored per-match "rating after this game" column, so this
    replays the same math record_match already used: each match's
    `rating_change` is the magnitude of that match's Elo delta, and the
    sign is recoverable from whether the player's team won or lost. Walking
    every one of the player's matches in id order and accumulating those
    deltas from STARTING_RATING reproduces their rating at each point in
    time — and lands on their current stored rating by construction.

    Returns a DataFrame with columns: game_num (0 = starting point, before
    any match), match_id, date, rating.
    """
    mask = (
        (matches_df["team1_p1"] == player_id)
        | (matches_df["team1_p2"] == player_id)
        | (matches_df["team2_p1"] == player_id)
        | (matches_df["team2_p2"] == player_id)
    )
    player_matches = matches_df[mask].sort_values("id")

    rating = STARTING_RATING
    rows = [{"game_num": 0, "match_id": None, "date": "Start", "rating": rating}]
    for i, (_, r) in enumerate(player_matches.iterrows(), start=1):
        on_team1 = player_id in (int(r["team1_p1"]), int(r["team1_p2"]))
        won = (on_team1 and int(r["winning_team"]) == 1) or (not on_team1 and int(r["winning_team"]) == 2)
        delta = float(r["rating_change"]) if won else -float(r["rating_change"])
        rating += delta
        rows.append({
            "game_num": i,
            "match_id": int(r["id"]),
            "date": r["date"],
            "rating": rating,
        })
    return pd.DataFrame(rows)


def recompute_ratings_from_history(players_df, matches_df):
    """Rebuild every non-guest player's rating/wins/losses from scratch by
    replaying the entire logged match history in order.

    This is the source of truth: players.csv should always be derivable
    from matches.csv, but a manual edit to either file (outside the app's
    own record/edit/delete flow) can let them drift apart. Running this
    resets every non-guest player to STARTING_RATING/0/0 and re-applies
    every match's stored rating_change in id order, so the two files are
    guaranteed to agree afterward. Guests are untouched — their rating is a
    fixed, manually-set value, never derived from match play.
    """
    df = players_df.set_index("id")
    non_guest_mask = ~df["is_guest"]
    df.loc[non_guest_mask, "rating"] = float(STARTING_RATING)
    df.loc[non_guest_mask, "wins"] = 0
    df.loc[non_guest_mask, "losses"] = 0

    for _, r in matches_df.sort_values("id").iterrows():
        team1_ids = [int(r["team1_p1"]), int(r["team1_p2"])]
        team2_ids = [int(r["team2_p1"]), int(r["team2_p2"])]
        winning_team = int(r["winning_team"])
        magnitude = float(r["rating_change"])
        delta1 = magnitude if winning_team == 1 else -magnitude
        delta2 = -delta1

        for pid in team1_ids:
            if pid not in df.index or df.loc[pid, "is_guest"]:
                continue
            df.loc[pid, "rating"] += delta1
            df.loc[pid, "wins" if winning_team == 1 else "losses"] += 1

        for pid in team2_ids:
            if pid not in df.index or df.loc[pid, "is_guest"]:
                continue
            df.loc[pid, "rating"] += delta2
            df.loc[pid, "wins" if winning_team == 2 else "losses"] += 1

    return df.reset_index()


# ----------------------------------------------------------------------------
# Partnership (teammate) win rates
# ----------------------------------------------------------------------------

def compute_partnership_stats(players_df, matches_df):
    """For every pair of players who have been teammates at least once,
    tally wins/losses as a team. Returns a list of dicts:
        {"p1_id", "p2_id", "p1_name", "p2_name", "wins", "losses",
         "games", "win_pct"}
    Guest-involving partnerships are excluded (a guest isn't a tracked,
    rankable entity), consistent with the Leaderboard.
    """
    name_map = get_player_map(players_df)
    guest_ids = set(players_df[players_df["is_guest"]]["id"])

    pair_stats = {}
    for _, m in matches_df.iterrows():
        team1 = tuple(sorted([int(m["team1_p1"]), int(m["team1_p2"])]))
        team2 = tuple(sorted([int(m["team2_p1"]), int(m["team2_p2"])]))
        winning_team = int(m["winning_team"])
        for team, won in ((team1, winning_team == 1), (team2, winning_team == 2)):
            if guest_ids.intersection(team):
                continue
            entry = pair_stats.setdefault(team, {"wins": 0, "losses": 0})
            if won:
                entry["wins"] += 1
            else:
                entry["losses"] += 1

    rows = []
    for (p1, p2), s in pair_stats.items():
        games = s["wins"] + s["losses"]
        rows.append(
            {
                "p1_id": p1,
                "p2_id": p2,
                "p1_name": name_map.get(p1, f"#{p1}"),
                "p2_name": name_map.get(p2, f"#{p2}"),
                "wins": s["wins"],
                "losses": s["losses"],
                "games": games,
                "win_pct": round(s["wins"] / games * 100, 1) if games else 0.0,
            }
        )
    return rows


# ----------------------------------------------------------------------------
# Matchmaking / rotation logic
# ----------------------------------------------------------------------------

def build_matchups(available_records, num_courts):
    """Suggest courts + teams + a bench for the next round.

    available_records: list of dicts, each with id, name, rating,
        games_today, sitouts_today — for every checked-in player.
    num_courts: how many courts of 4 to fill this round.

    Returns (courts, sitting_ids):
        courts is a list of {"team1": [id, id], "team2": [id, id]}
        sitting_ids is a list of player ids sitting out this round.

    Approach:
      1. Rank everyone by a "priority to play" score (more sit-outs and
         fewer games so far = higher priority). This is the fairness pass.
      2. Group the players selected to play into skill tiers (sorted by
         rating, chunked into fours) so courts are naturally competitive.
      3. If a court's rating spread is too wide, look for a bench player
         who is a closer skill fit AND whose fairness priority is close
         enough that swapping them in isn't a big fairness hit. This is how
         a high-rated player can end up sitting an extra round waiting for
         a good match — but because sitting out raises their priority score
         for next round, it can't compound indefinitely.
      4. Within each finalized court, form teams by pairing the strongest
         and weakest player against the middle two, which balances the two
         teams' average rating for a closer game.
    """
    records = [dict(r) for r in available_records]
    for r in records:
        # Small random jitter breaks exact ties fairly instead of always
        # favoring, say, whoever happens to be first alphabetically.
        r["priority"] = r["sitouts_today"] - r["games_today"] + random.uniform(-0.01, 0.01)
    records.sort(key=lambda r: r["priority"], reverse=True)

    needed = num_courts * 4
    playing = records[:needed]
    sitting = records[needed:]

    playing.sort(key=lambda r: r["rating"], reverse=True)
    courts = [playing[i:i + 4] for i in range(0, len(playing), 4)]

    def court_spread(court):
        ratings = [p["rating"] for p in court]
        return max(ratings) - min(ratings) if ratings else 0

    # Pass 1: swap players *between* courts to tighten skill groupings.
    # This never changes who plays vs. who sits, so it's always safe —
    # just a better arrangement of the people already selected to play.
    for _ in range(10):
        improved = False
        for i in range(len(courts)):
            for j in range(i + 1, len(courts)):
                if len(courts[i]) < 4 or len(courts[j]) < 4:
                    continue
                base = court_spread(courts[i]) + court_spread(courts[j])
                best_gain, best_pair = 0, None
                for a in courts[i]:
                    for b in courts[j]:
                        trial_i = [p for p in courts[i] if p is not a] + [b]
                        trial_j = [p for p in courts[j] if p is not b] + [a]
                        gain = base - (court_spread(trial_i) + court_spread(trial_j))
                        if gain > best_gain:
                            best_gain, best_pair = gain, (a, b)
                if best_pair:
                    a, b = best_pair
                    courts[i] = [p for p in courts[i] if p is not a] + [b]
                    courts[j] = [p for p in courts[j] if p is not b] + [a]
                    improved = True
        if not improved:
            break

    # Pass 2: for any court still too spread out, look to the bench for a
    # better-fitting player. Only players whose fairness priority is close
    # to the outlier's are eligible, so this doesn't badly hurt fairness —
    # it's how a high-rated player can end up sitting an extra round
    # waiting for a good match, without it snowballing (sitting raises
    # their priority for next round).
    for _ in range(2):
        for court in courts:
            if len(court) < 4:
                continue
            ratings = [p["rating"] for p in court]
            spread = max(ratings) - min(ratings)
            if spread <= RATING_SPREAD_THRESHOLD or not sitting:
                continue

            top_p = max(court, key=lambda p: p["rating"])
            bottom_p = min(court, key=lambda p: p["rating"])
            rest_sum = sum(ratings)
            rest_avg_excl_top = (rest_sum - top_p["rating"]) / 3
            rest_avg_excl_bottom = (rest_sum - bottom_p["rating"]) / 3

            if (top_p["rating"] - rest_avg_excl_top) >= (rest_avg_excl_bottom - bottom_p["rating"]):
                outlier, rest_avg = top_p, rest_avg_excl_top
            else:
                outlier, rest_avg = bottom_p, rest_avg_excl_bottom

            eligible = [p for p in sitting if abs(p["priority"] - outlier["priority"]) <= FAIRNESS_TOLERANCE]
            eligible.sort(key=lambda p: abs(p["rating"] - rest_avg))

            for candidate in eligible:
                new_ratings = [p["rating"] for p in court if p["id"] != outlier["id"]] + [candidate["rating"]]
                if max(new_ratings) - min(new_ratings) < spread:
                    court.remove(outlier)
                    court.append(candidate)
                    sitting.remove(candidate)
                    sitting.append(outlier)
                    break

    # Pass 3: some fixes need multiple simultaneous swaps (pulling in
    # several better-fitting bench players while benching several current
    # ones at once) because doing it one at a time would briefly make
    # things worse and get rejected. Court/bench sizes here are small, so
    # brute-forcing small combinations (k=2 or 3 at a time) is cheap.
    def try_k_for_k(court, sitting, k):
        if len(sitting) < k or len(court) < k:
            return False
        ratings = [p["rating"] for p in court]
        spread = max(ratings) - min(ratings)
        if spread <= RATING_SPREAD_THRESHOLD:
            return False
        best_gain, best_out, best_in = 0, None, None
        for out_combo in itertools.combinations(court, k):
            out_priority_avg = sum(p["priority"] for p in out_combo) / k
            eligible = [p for p in sitting if abs(p["priority"] - out_priority_avg) <= FAIRNESS_TOLERANCE * k]
            for in_combo in itertools.combinations(eligible, k):
                remaining = [p for p in court if p not in out_combo]
                new_ratings = [p["rating"] for p in remaining + list(in_combo)]
                gain = spread - (max(new_ratings) - min(new_ratings))
                if gain > best_gain:
                    best_gain, best_out, best_in = gain, out_combo, in_combo
        if best_out:
            for p in best_out:
                court.remove(p)
                sitting.append(p)
            for p in best_in:
                sitting.remove(p)
                court.append(p)
            return True
        return False

    for court in courts:
        if len(court) < 4:
            continue
        for k in (2, 3):
            for _ in range(3):
                if not try_k_for_k(court, sitting, k):
                    break

    court_dicts = []
    for court in courts:
        court_sorted = sorted(court, key=lambda p: p["rating"], reverse=True)
        ids = [p["id"] for p in court_sorted]
        if len(ids) == 4:
            team1 = [ids[0], ids[3]]
            team2 = [ids[1], ids[2]]
        else:
            # Shouldn't happen in normal use (courts are only built from
            # complete groups of 4), but guard against a short last group.
            half = len(ids) // 2
            team1, team2 = ids[:half], ids[half:]
        court_dicts.append({"team1": team1, "team2": team2})

    sitting_ids = [p["id"] for p in sitting]
    return court_dicts, sitting_ids


# ----------------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Pickleball Doubles Rankings", page_icon="🏓", layout="wide")
try:
    init_storage()
except Exception as e:
    st.error(
        "Couldn't connect to the Google Sheet. Double-check that `gcp_service_account` and "
        "`spreadsheet_id` are set in Streamlit secrets, and that the sheet is shared (Editor "
        "access) with the service account's `client_email`. See secrets.toml.example for the "
        f"expected format.\n\nDetails: {e}"
    )
    st.stop()
ensure_guest_exists()

# Confirmation messages that need to survive a st.rerun() are stashed here
# on the run that triggers the rerun, then shown (once) on the next run.
# Without this, a message set right before st.rerun() gets wiped before the
# person ever really sees it.
if "flash" in st.session_state:
    _kind, _msg = st.session_state.pop("flash")
    getattr(st, _kind)(_msg)


def flash(kind, msg):
    st.session_state["flash"] = (kind, msg)


st.title("🏓 Pickleball Doubles Rankings")
st.caption(f"Season {current_season_number()} in progress. All data is stored locally in CSV files next to this app.")

page = st.sidebar.radio(
    "Navigate",
    [
        "Matchmaking", "Leaderboard", "Best Partnerships", "Add Player", "Record Match",
        "Match History", "Player Profile", "Previous Seasons", "Settings",
    ],
)

# ---- Matchmaking -------------------------------------------------------------
if page == "Matchmaking":
    st.header("Today's Matchmaking")

    players_df = load_players()
    active_df = players_df[players_df["active"]]
    if len(active_df) < 4:
        st.warning("You need at least 4 active players in the system before you can run matchmaking. Add players first.")
    else:
        session_df = sync_session(players_df)

        st.session_state.setdefault("mm_stage", "checkin")
        st.session_state.setdefault("mm_gen", 0)
        st.session_state.setdefault("mm_round", 1)

        info = players_df.set_index("id")

        # ---- Stage 1: Check-in ------------------------------------------
        if st.session_state["mm_stage"] == "checkin":
            st.subheader(f"Round {st.session_state['mm_round']} — Who's here?")
            st.write("Check people in as they arrive, and check them out if they leave. This list can change between rounds.")

            all_names = active_df.sort_values("name")["name"].tolist()
            name_to_id = dict(zip(active_df["name"], active_df["id"]))
            currently_checked_in = session_df[session_df["checked_in"]]["id"].tolist()
            default_names = [n for n in all_names if name_to_id[n] in currently_checked_in]

            selected_names = st.multiselect("Checked in", all_names, default=default_names, key="mm_checkin_select")
            selected_ids = [name_to_id[n] for n in selected_names]
            session_df = set_checked_in(session_df, selected_ids)

            n_here = len(selected_ids)
            st.metric("Players checked in", n_here)

            if n_here > 0:
                status = session_df[session_df["id"].isin(selected_ids)].merge(
                    players_df[["id", "name", "rating"]], on="id"
                )
                status = status.sort_values(["sitouts_today", "games_today"], ascending=[False, True])
                st.dataframe(
                    status[["name", "rating", "games_today", "sitouts_today"]].rename(
                        columns={"name": "Player", "rating": "Rating", "games_today": "Games Today", "sitouts_today": "Sit-outs Today"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            max_courts = n_here // 4
            if max_courts < 1:
                st.info("Check in at least 4 players to generate matchups.")
            else:
                num_courts = st.number_input(
                    "Number of courts to fill this round",
                    min_value=1, max_value=max_courts, value=max_courts, step=1,
                )
                if st.button("Suggest Matchups ▶", type="primary"):
                    available_records = status.to_dict("records") if n_here > 0 else []
                    courts, bench = build_matchups(available_records, int(num_courts))
                    st.session_state["mm_courts"] = courts
                    st.session_state["mm_bench"] = bench
                    st.session_state["mm_gen"] += 1
                    st.session_state["mm_stage"] = "review"
                    st.rerun()

            st.divider()
            c1, c2 = st.columns(2)
            if c1.button("Reset today's rotation stats"):
                session_df = reset_today_stats(session_df)
                flash("success", "Games/sit-out counts reset to zero for today.")
                st.rerun()
            if c2.button("Check everyone out"):
                session_df = set_checked_in(session_df, [])
                st.rerun()

        # ---- Stage 2: Review / Edit suggestion ---------------------------
        elif st.session_state["mm_stage"] == "review":
            st.subheader(f"Round {st.session_state['mm_round']} — Suggested Matchups")
            st.write("Edit any slot below if you want to adjust for outside factors, then confirm.")

            gen = st.session_state["mm_gen"]
            courts = st.session_state["mm_courts"]
            checked_in_ids = session_df[session_df["checked_in"]]["id"].tolist()

            def label(pid):
                return f"{info.loc[pid, 'name']} ({info.loc[pid, 'rating']:.0f})"

            options = sorted([label(pid) for pid in checked_in_ids])
            label_to_id = {label(pid): pid for pid in checked_in_ids}

            for i, court in enumerate(courts):
                st.markdown(f"**Court {i + 1}**")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("Team 1")
                    st.selectbox("Player A", options, index=options.index(label(court["team1"][0])), key=f"c{gen}_{i}_t1p1")
                    st.selectbox("Player B", options, index=options.index(label(court["team1"][1])), key=f"c{gen}_{i}_t1p2")
                with c2:
                    st.caption("Team 2")
                    st.selectbox("Player C", options, index=options.index(label(court["team2"][0])), key=f"c{gen}_{i}_t2p1")
                    st.selectbox("Player D", options, index=options.index(label(court["team2"][1])), key=f"c{gen}_{i}_t2p2")

            # Gather the (possibly edited) assignment
            assigned_ids, new_courts = [], []
            for i in range(len(courts)):
                ids = [
                    label_to_id[st.session_state[f"c{gen}_{i}_t1p1"]],
                    label_to_id[st.session_state[f"c{gen}_{i}_t1p2"]],
                    label_to_id[st.session_state[f"c{gen}_{i}_t2p1"]],
                    label_to_id[st.session_state[f"c{gen}_{i}_t2p2"]],
                ]
                assigned_ids.extend(ids)
                new_courts.append({"team1": ids[0:2], "team2": ids[2:4]})

            bench_ids = [pid for pid in checked_in_ids if pid not in assigned_ids]
            duplicates = len(assigned_ids) != len(set(assigned_ids))

            st.markdown("**Sitting out this round:**")
            if bench_ids:
                st.write(", ".join(info.loc[pid, "name"] for pid in bench_ids))
            else:
                st.write("No one — every checked-in player is on a court.")

            if duplicates:
                st.error("A player is assigned to more than one slot. Fix the duplicate before confirming.")

            st.divider()
            b1, b2, b3 = st.columns(3)
            if b1.button("🔄 Regenerate Suggestion"):
                available_records = session_df[session_df["id"].isin(checked_in_ids)].merge(
                    players_df[["id", "name", "rating"]], on="id"
                ).to_dict("records")
                courts2, bench2 = build_matchups(available_records, len(courts))
                st.session_state["mm_courts"] = courts2
                st.session_state["mm_bench"] = bench2
                st.session_state["mm_gen"] += 1
                st.rerun()
            if b2.button("◀ Back to Check-in"):
                st.session_state["mm_stage"] = "checkin"
                st.rerun()
            if b3.button("✅ Confirm Matchups", type="primary", disabled=duplicates):
                session_df = apply_round_result(session_df, assigned_ids, bench_ids)
                st.session_state["mm_active_courts"] = new_courts
                st.session_state["mm_stage"] = "scoring"
                st.rerun()

        # ---- Stage 3: Scoring ---------------------------------------------
        elif st.session_state["mm_stage"] == "scoring":
            st.subheader(f"Round {st.session_state['mm_round']} — Enter Scores")
            active_courts = st.session_state["mm_active_courts"]

            score_inputs = []
            for i, court in enumerate(active_courts):
                t1_names = " / ".join(info.loc[pid, "name"] for pid in court["team1"])
                t2_names = " / ".join(info.loc[pid, "name"] for pid in court["team2"])
                st.markdown(f"**Court {i + 1}:** {t1_names} vs {t2_names}")
                c1, c2 = st.columns(2)
                s1 = c1.number_input(f"{t1_names} score", min_value=0, step=1, value=11, key=f"score_{i}_t1")
                s2 = c2.number_input(f"{t2_names} score", min_value=0, step=1, value=0, key=f"score_{i}_t2")
                score_inputs.append((court["team1"], court["team2"], s1, s2))

            st.divider()
            b1, b2, b3 = st.columns(3)
            if b1.button("◀ Edit Matchups Again"):
                st.session_state["mm_stage"] = "review"
                st.rerun()
            if b2.button("⏭ Skip Recording Scores"):
                st.session_state["mm_stage"] = "checkin"
                st.session_state["mm_round"] += 1
                st.rerun()
            if b3.button("🏁 Submit Scores & Finish Round", type="primary"):
                errors = []
                recorded = 0
                for team1_ids, team2_ids, s1, s2 in score_inputs:
                    success, msg = record_match(team1_ids, team2_ids, int(s1), int(s2), date.today())
                    if not success:
                        errors.append(msg)
                    else:
                        recorded += 1
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    flash("success", f"✅ Round {st.session_state['mm_round']} complete — {recorded} score(s) recorded and ratings updated.")
                    st.session_state["mm_stage"] = "checkin"
                    st.session_state["mm_round"] += 1
                    st.rerun()

# ---- Leaderboard ------------------------------------------------------------
elif page == "Leaderboard":
    st.header("Leaderboard")
    players_df = load_players()
    matches_df = load_matches()
    # The leaderboard only shows active, real (non-guest) players.
    df = players_df[players_df["active"] & ~players_df["is_guest"]].copy()

    if df.empty:
        st.info("No players yet. Add some players to get started!")
    else:
        for col in ["rating", "wins", "losses"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df["Games"] = df["wins"] + df["losses"]
        df["Win %"] = (df["wins"] / df["Games"] * 100).round(1)

        partner_stats = compute_partner_opponent_stats(players_df, matches_df)
        df["Avg Partner Rating"] = df["id"].map(lambda pid: partner_stats[pid]["partner_avg"])
        df["Partner Δ"] = df["Avg Partner Rating"] - df["rating"]
        df["Boosted?"] = df["Partner Δ"].apply(
            lambda d: "⚠️ Yes" if pd.notna(d) and d > PARTNER_BOOST_THRESHOLD else ""
        )

        streaks = compute_streaks(players_df, matches_df)
        df["Streak"] = df["id"].map(lambda pid: format_streak(streaks.get(pid)))

        df = df.sort_values("rating", ascending=False).reset_index(drop=True)
        df.insert(0, "Rank", df.index + 1)
        display_df = df[
            ["Rank", "name", "rating", "wins", "losses", "Games", "Win %", "Streak", "Avg Partner Rating", "Boosted?"]
        ].rename(columns={"name": "Player", "rating": "Rating"})
        display_df["Rating"] = display_df["Rating"].round(1)
        display_df["Avg Partner Rating"] = pd.to_numeric(
            display_df["Avg Partner Rating"], errors="coerce"
        ).round(1)
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.caption(
            "**Streak** shows the player's current run (e.g. `3W` = 3 wins in a row, `2L` = 2 losses in a row); "
            "🔥 marks an active win streak of 3 or more. **Boosted?** flags players whose average partner is "
            f"rated {PARTNER_BOOST_THRESHOLD}+ points above their own rating — their record may be "
            "propped up by consistently strong teammates rather than their own play. "
            "Partner ratings use each player's *current* rating, not a historical snapshot."
        )

        st.subheader("Rating Comparison")
        chart_df = df.set_index("name")[["rating"]].rename(columns={"rating": "Rating"})
        chart_df["Rating"] = pd.to_numeric(chart_df["Rating"], errors="coerce")
        st.bar_chart(chart_df)

# ---- Best Partnerships -------------------------------------------------------
elif page == "Best Partnerships":
    st.header("Best Partnerships")
    st.write("Win rate for every pair of players who've been teammates at least once.")

    players_df = load_players()
    matches_df = load_matches()

    if matches_df.empty:
        st.info("No matches recorded yet.")
    else:
        rows = compute_partnership_stats(players_df, matches_df)
        if not rows:
            st.info("No partnerships to show yet.")
        else:
            pdf = pd.DataFrame(rows)
            min_games = st.slider("Minimum games played together", min_value=1, max_value=10, value=2)
            filtered = pdf[pdf["games"] >= min_games].sort_values(
                ["win_pct", "games"], ascending=[False, False]
            ).reset_index(drop=True)

            if filtered.empty:
                st.info(f"No partnerships have played {min_games}+ games together yet. Try lowering the minimum.")
            else:
                filtered.insert(0, "Rank", filtered.index + 1)
                display = filtered[["Rank", "p1_name", "p2_name", "games", "wins", "losses", "win_pct"]].rename(
                    columns={
                        "p1_name": "Player A", "p2_name": "Player B", "games": "Games",
                        "wins": "Wins", "losses": "Losses", "win_pct": "Win %",
                    }
                )
                st.dataframe(display, use_container_width=True, hide_index=True)
                st.caption(
                    "Only pairs who've played together at least the selected number of games are shown, "
                    "to avoid a single lucky win looking like a 100% record. Guest-involving partnerships "
                    "are excluded, same as the Leaderboard."
                )

# ---- Add Player -------------------------------------------------------------
elif page == "Add Player":
    st.header("Add a New Player")
    st.write("Manually enter a player's name to add them to the system. Everyone starts at a rating of 1000.")
    with st.form("add_player_form", clear_on_submit=True):
        name = st.text_input("Player name")
        submitted = st.form_submit_button("Add Player")
        if submitted:
            success, msg = add_player(name)
            if success:
                st.success(msg)
            else:
                st.error(msg)

    st.write(
        "Need an extra body to fill out a court? Guests never affect the leaderboard and their "
        "rating never moves — but you can set how strong a fill-in they are so team-average "
        "Elo math stays fair for the real players in their match."
    )
    guest_rating_labels = {
        r: f"{r}" + (" (default)" if r == STARTING_RATING else "") for r in GUEST_RATING_OPTIONS
    }
    c1, c2 = st.columns([2, 1])
    new_guest_rating = c1.selectbox(
        "Guest starting rating",
        GUEST_RATING_OPTIONS,
        index=GUEST_RATING_OPTIONS.index(STARTING_RATING),
        format_func=lambda r: guest_rating_labels[r],
        key="new_guest_rating",
    )
    if c2.button("➕ Add Guest Slot"):
        new_name = add_guest_slot(new_guest_rating)
        flash("success", f"Added a new guest slot: '{new_name}' at rating {new_guest_rating}.")
        st.rerun()

    st.divider()
    st.subheader("Active Players")
    players_df = load_players()
    active_regular = players_df[players_df["active"] & ~players_df["is_guest"]].sort_values("name")
    active_guests = players_df[players_df["active"] & players_df["is_guest"]].sort_values("name")

    if active_regular.empty:
        st.info("No active players yet.")
    else:
        for _, row in active_regular.iterrows():
            col1, col2 = st.columns([4, 1])
            col1.write(f"**{row['name']}** — Rating: {row['rating']:.1f} ({int(row['wins'])}W-{int(row['losses'])}L)")
            if col2.button("Remove", key=f"deactivate_{row['id']}"):
                set_player_active(row["id"], False)
                flash("success", f"Removed '{row['name']}' from the leaderboard. Their match history is kept.")
                st.rerun()

    if not active_guests.empty:
        st.caption("Guest slots (rating is fixed — never moved by match results — but adjustable below):")
        for _, row in active_guests.iterrows():
            gcol1, gcol2, gcol3 = st.columns([3, 2, 1])
            gcol1.write(f"🎽 **{row['name']}** — fixed at rating {row['rating']:.0f}")
            current_rating = int(row["rating"])
            options = sorted(set(GUEST_RATING_OPTIONS) | {current_rating})
            chosen = gcol2.selectbox(
                "New rating",
                options,
                index=options.index(current_rating),
                key=f"guest_rating_select_{row['id']}",
                label_visibility="collapsed",
            )
            if gcol3.button("Update", key=f"guest_rating_update_{row['id']}"):
                success, msg = set_guest_rating(row["id"], chosen)
                if success:
                    flash("success", f"{row['name']}'s rating set to {chosen}.")
                    st.rerun()
                else:
                    st.error(msg)

    inactive_df = players_df[~players_df["active"] & ~players_df["is_guest"]].sort_values("name")
    if not inactive_df.empty:
        with st.expander(f"Removed players ({len(inactive_df)})"):
            st.write("These players are hidden from the leaderboard and pickers, but their past matches are still in Match History.")
            for _, row in inactive_df.iterrows():
                col1, col2 = st.columns([4, 1])
                col1.write(f"{row['name']} — Rating: {row['rating']:.1f}")
                if col2.button("Restore", key=f"reactivate_{row['id']}"):
                    set_player_active(row["id"], True)
                    flash("success", f"Restored '{row['name']}' to the leaderboard.")
                    st.rerun()

    st.divider()
    with st.expander("🛠️ Data Integrity"):
        st.write(
            "Every player's rating and win/loss record should always be derivable from the matches "
            "logged in Match History. If players.csv was ever edited by hand (or a match was fixed up "
            "outside the app), the two can drift apart. This recomputes every non-guest player's "
            "rating, wins, and losses from scratch by replaying the full match history in order — "
            "guests are untouched, since their rating is a fixed, manually-set value."
        )
        if st.button("🔄 Recompute All Ratings From Match History"):
            fixed_df = recompute_ratings_from_history(load_players(), load_matches())
            save_players(fixed_df)
            flash("success", "All player ratings, wins, and losses recomputed from the logged match history.")
            st.rerun()

# ---- Record Match -----------------------------------------------------------
elif page == "Record Match":
    st.header("Record a Doubles Match")
    st.write("Pick the four players and manually enter the final score.")
    players_df = load_players()
    active_df = players_df[players_df["active"]]

    if len(active_df) < 4:
        st.warning("You need at least 4 active players before you can record a doubles match.")
    else:
        names = active_df.sort_values("name")["name"].tolist()
        name_to_id = dict(zip(active_df["name"], active_df["id"]))

        st.subheader("Team 1")
        c1, c2 = st.columns(2)
        t1p1 = c1.selectbox("Player 1", names, key="t1p1")
        t1p2 = c2.selectbox("Player 2", [n for n in names if n != t1p1], key="t1p2")

        st.subheader("Team 2")
        remaining = [n for n in names if n not in (t1p1, t1p2)]
        c3, c4 = st.columns(2)
        t2p1 = c3.selectbox("Player 1", remaining, key="t2p1")
        t2p2 = c4.selectbox(
            "Player 2", [n for n in remaining if n != t2p1], key="t2p2"
        )

        st.subheader("Score")
        c5, c6 = st.columns(2)
        score1 = c5.number_input(f"{t1p1} / {t1p2} score", min_value=0, step=1, value=11)
        score2 = c6.number_input(f"{t2p1} / {t2p2} score", min_value=0, step=1, value=0)

        match_date = st.date_input("Match date", value=date.today())

        if st.button("Submit Match", type="primary"):
            team1_ids = [name_to_id[t1p1], name_to_id[t1p2]]
            team2_ids = [name_to_id[t2p1], name_to_id[t2p2]]
            success, msg = record_match(team1_ids, team2_ids, int(score1), int(score2), match_date)
            if success:
                flash("success", msg)
                st.rerun()
            else:
                st.error(msg)

# ---- Match History -----------------------------------------------------------
elif page == "Match History":
    st.header("Match History")
    matches_df = load_matches()
    players_df = load_players()

    if matches_df.empty:
        st.info("No matches recorded yet.")
    else:
        editable_day = get_editable_day(matches_df)
        editable_ids_set = set(get_editable_match_ids(matches_df))
        player_map = get_player_map(players_df)

        display = matches_df.copy().sort_values("id", ascending=False)
        display["Team 1"] = display["team1_p1"].map(player_map) + " / " + display["team1_p2"].map(player_map)
        display["Team 2"] = display["team2_p1"].map(player_map) + " / " + display["team2_p2"].map(player_map)
        display["Score"] = display["score1"].astype(int).astype(str) + " - " + display["score2"].astype(int).astype(str)
        display["Winner"] = display.apply(lambda r: r["Team 1"] if r["winning_team"] == 1 else r["Team 2"], axis=1)
        display["Editable"] = display["id"].map(lambda i: "✅" if i in editable_ids_set else "🔒")
        st.dataframe(
            display[["id", "date", "Team 1", "Team 2", "Score", "Winner", "rating_change", "Editable"]].rename(
                columns={"id": "ID", "date": "Date", "rating_change": "Rating +/-"}
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"✅ = editable — matches from {editable_day} (the current day of play). 🔒 = older history, kept "
            "locked so it isn't casually rewritten. Correcting or deleting an editable match recalculates "
            "ratings and records for that match and every match after it."
        )

        st.divider()
        st.subheader("✏️ Correct or Delete a Match")

        def match_option_label(mid):
            r = matches_df[matches_df["id"] == mid].iloc[0]
            t1 = f"{player_map.get(int(r['team1_p1']))}/{player_map.get(int(r['team1_p2']))}"
            t2 = f"{player_map.get(int(r['team2_p1']))}/{player_map.get(int(r['team2_p2']))}"
            return f"#{mid} — {r['date']} — {t1} vs {t2} ({int(r['score1'])}-{int(r['score2'])})"

        editable_ids = sorted(editable_ids_set, reverse=True)
        if not editable_ids:
            st.info("No matches are currently editable.")
        else:
            chosen_label = st.selectbox(
                "Pick a match", [match_option_label(mid) for mid in editable_ids], key="edit_match_select"
            )
            chosen_id = editable_ids[[match_option_label(mid) for mid in editable_ids].index(chosen_label)]
            match_row = matches_df[matches_df["id"] == chosen_id].iloc[0]

            action = st.radio("What do you want to do?", ["Correct the score/players", "Delete this match"], horizontal=True)

            if action == "Delete this match":
                st.warning(
                    "Deleting will reverse the rating and win/loss changes this match caused, "
                    "putting the 4 players' ratings back to what they were right before it."
                )
                confirm = st.checkbox("I understand this can't be undone.")
                if st.button("🗑️ Delete Match", type="primary", disabled=not confirm):
                    success, msg = delete_match(chosen_id)
                    if success:
                        flash("success", msg)
                        st.rerun()
                    else:
                        st.error(msg)

            else:  # Correct the score/players
                all_names_sorted = players_df.sort_values("name")["name"].tolist()
                name_to_id_all = dict(zip(players_df["name"], players_df["id"]))
                id_to_name_all = {v: k for k, v in name_to_id_all.items()}

                st.caption("Change any of the 4 players and/or the score, then save.")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("Team 1")
                    new_t1p1 = st.selectbox(
                        "Player 1", all_names_sorted,
                        index=all_names_sorted.index(id_to_name_all[int(match_row["team1_p1"])]),
                        key="edit_t1p1",
                    )
                    new_t1p2 = st.selectbox(
                        "Player 2", all_names_sorted,
                        index=all_names_sorted.index(id_to_name_all[int(match_row["team1_p2"])]),
                        key="edit_t1p2",
                    )
                with c2:
                    st.caption("Team 2")
                    new_t2p1 = st.selectbox(
                        "Player 1", all_names_sorted,
                        index=all_names_sorted.index(id_to_name_all[int(match_row["team2_p1"])]),
                        key="edit_t2p1",
                    )
                    new_t2p2 = st.selectbox(
                        "Player 2", all_names_sorted,
                        index=all_names_sorted.index(id_to_name_all[int(match_row["team2_p2"])]),
                        key="edit_t2p2",
                    )

                c3, c4 = st.columns(2)
                new_score1 = c3.number_input("Team 1 score", min_value=0, step=1, value=int(match_row["score1"]), key="edit_score1")
                new_score2 = c4.number_input("Team 2 score", min_value=0, step=1, value=int(match_row["score2"]), key="edit_score2")
                new_date = st.date_input("Date", value=pd.to_datetime(match_row["date"]).date(), key="edit_date")

                chosen_ids = [name_to_id_all[n] for n in (new_t1p1, new_t1p2, new_t2p1, new_t2p2)]
                if len(set(chosen_ids)) != 4:
                    st.error("All 4 players must be different.")
                elif st.button("💾 Save Correction", type="primary"):
                    success, msg = edit_match(
                        chosen_id,
                        [name_to_id_all[new_t1p1], name_to_id_all[new_t1p2]],
                        [name_to_id_all[new_t2p1], name_to_id_all[new_t2p2]],
                        int(new_score1), int(new_score2), new_date,
                    )
                    if success:
                        flash("success", f"Match corrected. {msg}")
                        st.rerun()
                    else:
                        st.error(msg)

        locked_count = len(matches_df) - len(editable_ids_set)
        if locked_count:
            st.caption(f"🔒 {locked_count} older match(es) from before {editable_day} are locked from editing.")

# ---- Player Profile -----------------------------------------------------------
elif page == "Player Profile":
    st.header("Player Profile")
    players_df = load_players()
    profile_df = players_df[players_df["active"] & ~players_df["is_guest"]]
    if profile_df.empty:
        st.info("No players yet.")
    else:
        name = st.selectbox("Select a player", profile_df.sort_values("name")["name"].tolist())
        row = profile_df[profile_df["name"] == name].iloc[0]
        games = row["wins"] + row["losses"]
        win_pct = (row["wins"] / games * 100) if games else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Rating", f"{row['rating']:.1f}")
        m2.metric("Wins", int(row["wins"]))
        m3.metric("Losses", int(row["losses"]))
        m4.metric("Win %", f"{win_pct:.1f}%")

        matches_df = load_matches()
        streaks = compute_streaks(players_df, matches_df)
        streak_info = streaks.get(int(row["id"]))
        m5.metric("Current Streak", format_streak(streak_info))
        if streak_info and streak_info["best_win_streak"] > 0:
            st.caption(f"🏆 Best win streak ever: {streak_info['best_win_streak']} in a row")

        partner_stats = compute_partner_opponent_stats(players_df, matches_df)
        pstat = partner_stats.get(int(row["id"]), {"partner_avg": None, "opponent_avg": None, "n": 0})

        st.subheader("Strength of Schedule")
        p1, p2 = st.columns(2)
        if pstat["partner_avg"] is not None:
            p1.metric("Avg. Partner Rating", f"{pstat['partner_avg']:.1f}")
            p2.metric("Avg. Opponent Rating", f"{pstat['opponent_avg']:.1f}")
            diff = pstat["partner_avg"] - row["rating"]
            if diff > PARTNER_BOOST_THRESHOLD:
                st.warning(
                    f"This player's average partner is rated {diff:.0f} points above their own rating. "
                    "Their record may be partly boosted by consistently strong teammates rather than their own play."
                )
            elif diff < -PARTNER_BOOST_THRESHOLD:
                st.info(
                    f"This player's average partner is rated {abs(diff):.0f} points below their own rating — "
                    "they've generally had to carry weaker teams."
                )
            st.caption("Based on partners'/opponents' *current* ratings, not a historical snapshot from when each match was played.")
        else:
            st.info("No matches recorded yet for this player.")

        st.subheader("Rating Over Time")
        history_df = compute_rating_history(matches_df, int(row["id"]))
        if len(history_df) <= 1:
            st.info("No matches recorded yet — nothing to chart.")
        else:
            rating_chart = (
                alt.Chart(history_df)
                .mark_line(point=True, color="#2E86AB")
                .encode(
                    x=alt.X("game_num:Q", title="Game #", axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("rating:Q", title="Rating", scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip("date:N", title="Date"),
                        alt.Tooltip("rating:Q", title="Rating", format=".1f"),
                    ],
                )
                .properties(height=300)
            )
            st.altair_chart(rating_chart, use_container_width=True)
            st.caption(
                "Reconstructed by replaying each match's stored rating change in order, starting from 1000 "
                "— this is how the rating evolved match by match, not just a before/after snapshot."
            )

        st.subheader(f"{name}'s Match History")
        player_id = int(row["id"])
        if matches_df.empty:
            st.info("No matches yet for this player.")
        else:
            mask = (
                (matches_df["team1_p1"] == player_id)
                | (matches_df["team1_p2"] == player_id)
                | (matches_df["team2_p1"] == player_id)
                | (matches_df["team2_p2"] == player_id)
            )
            raw = matches_df[mask].sort_values("id", ascending=False).copy()
            if raw.empty:
                st.info("No matches yet for this player.")
            else:
                player_map = get_player_map(players_df)
                raw["Team 1"] = raw["team1_p1"].map(player_map) + " / " + raw["team1_p2"].map(player_map)
                raw["Team 2"] = raw["team2_p1"].map(player_map) + " / " + raw["team2_p2"].map(player_map)
                raw["Score"] = raw["score1"].astype(int).astype(str) + " - " + raw["score2"].astype(int).astype(str)
                raw["Result"] = raw.apply(
                    lambda r: "Win" if (
                        (player_id in (r["team1_p1"], r["team1_p2"]) and r["winning_team"] == 1)
                        or (player_id in (r["team2_p1"], r["team2_p2"]) and r["winning_team"] == 2)
                    ) else "Loss",
                    axis=1,
                )
                st.dataframe(
                    raw[["date", "Team 1", "Team 2", "Score", "Result"]].rename(
                        columns={"date": "Date"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

# ---- Previous Seasons ---------------------------------------------------------
elif page == "Previous Seasons":
    st.header("Previous Seasons")
    seasons_df = load_seasons()

    if seasons_df.empty:
        st.info("No seasons have been archived yet. Use Settings → New Season once this season wraps up.")
    else:
        season_players_df = load_season_players()
        season_matches_df = load_season_matches()

        for _, srow in seasons_df.sort_values("season_id", ascending=False).iterrows():
            sid = int(srow["season_id"])
            with st.expander(f"🏆 {srow['label']}  —  {srow['start_date']} to {srow['end_date']}", expanded=False):
                season_all = season_players_df[season_players_df["season_id"] == sid].rename(columns={"player_id": "id"})
                season_matches_sid = season_matches_df[season_matches_df["season_id"] == sid]
                sp = season_all[~season_all["is_guest"]].copy()

                if sp.empty:
                    st.info("No player data recorded for this season.")
                    continue

                sp["Games"] = sp["wins"] + sp["losses"]
                sp["Win %"] = (sp["wins"] / sp["Games"].replace(0, pd.NA) * 100).round(1)
                sp = sp.sort_values("rating", ascending=False).reset_index(drop=True)
                sp.insert(0, "Rank", sp.index + 1)

                st.subheader("Final Leaderboard")
                leaderboard_display = sp[["Rank", "name", "rating", "wins", "losses", "Games", "Win %"]].rename(
                    columns={"name": "Player", "rating": "Rating"}
                )
                leaderboard_display["Rating"] = leaderboard_display["Rating"].round(1)
                st.dataframe(leaderboard_display, use_container_width=True, hide_index=True)

                st.subheader("Player Profile")
                chosen_name = st.selectbox(
                    "Select a player", sp["name"].tolist(), key=f"season_player_select_{sid}"
                )
                prow = sp[sp["name"] == chosen_name].iloc[0]
                player_id = int(prow["id"])
                win_pct = float(prow["Win %"]) if pd.notna(prow["Win %"]) else 0.0

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Final Rating", f"{prow['rating']:.1f}")
                m2.metric("Wins", int(prow["wins"]))
                m3.metric("Losses", int(prow["losses"]))
                m4.metric("Win %", f"{win_pct:.1f}%")
                st.caption(f"{int(prow['Games'])} match(es) played in {srow['label']}.")

                partner_stats = compute_partner_opponent_stats(season_all, season_matches_sid)
                pstat = partner_stats.get(player_id, {"partner_avg": None, "opponent_avg": None, "n": 0})
                if pstat["partner_avg"] is not None:
                    st.markdown("**Strength of Schedule**")
                    p1, p2 = st.columns(2)
                    p1.metric("Avg. Partner Rating", f"{pstat['partner_avg']:.1f}")
                    p2.metric("Avg. Opponent Rating", f"{pstat['opponent_avg']:.1f}")

                st.markdown("**Rating Over Time**")
                history_df = compute_rating_history(season_matches_sid, player_id)
                if len(history_df) <= 1:
                    st.info("No matches recorded for this player in this season.")
                else:
                    season_chart = (
                        alt.Chart(history_df)
                        .mark_line(point=True, color="#2E86AB")
                        .encode(
                            x=alt.X("game_num:Q", title="Game #", axis=alt.Axis(tickMinStep=1)),
                            y=alt.Y("rating:Q", title="Rating", scale=alt.Scale(zero=False)),
                            tooltip=[
                                alt.Tooltip("date:N", title="Date"),
                                alt.Tooltip("rating:Q", title="Rating", format=".1f"),
                            ],
                        )
                        .properties(height=280)
                    )
                    st.altair_chart(season_chart, use_container_width=True)

# ---- Settings -------------------------------------------------------------------
elif page == "Settings":
    st.header("Settings")

    st.subheader("🆕 New Season")
    st.write(
        "Archive this season's results and start fresh. Every player's rating and record resets "
        "for the new season, but the full history of this season — final ratings, wins, losses, "
        "win %, and match counts — is preserved forever in **Previous Seasons**."
    )
    matches_df = load_matches()
    if matches_df.empty:
        st.info("No matches recorded yet this season — there's nothing to archive.")
    else:
        st.write(
            f"This will archive **Season {current_season_number()}** "
            f"({len(matches_df)} match{'es' if len(matches_df) != 1 else ''} recorded) "
            f"and start **Season {current_season_number() + 1}**."
        )

        start_mode_label = st.radio(
            "How should ratings start for the new season?",
            ["Flat reset (everyone starts at 1000)", "Tiered start (based on this season's final standings)"],
            key="new_season_start_mode",
        )
        start_mode = "tiered" if start_mode_label.startswith("Tiered") else "flat"

        if start_mode == "tiered":
            tier_desc = " / ".join(
                f"top {int(t['percentile'] * 100)}%: {t['rating']}" for t in SEASON_START_TIERS
            )
            st.caption(
                f"Players are ranked by their final rating this season and placed into tiers ({tier_desc}). "
                "Anyone who didn't play a match this season starts at 1000, same as always."
            )
            preview_players = load_players()
            tiered_ratings = compute_tiered_start_ratings(preview_players)
            preview = preview_players[~preview_players["is_guest"]].copy()
            preview["New Rating"] = preview["id"].map(tiered_ratings)
            preview = preview.sort_values(["New Rating", "rating"], ascending=[False, False])
            st.dataframe(
                preview[["name", "rating", "New Rating"]].rename(
                    columns={"name": "Player", "rating": "Current Rating"}
                ),
                use_container_width=True,
                hide_index=True,
            )

        confirm_reset = st.checkbox(
            "I understand this resets every player's rating and record for the new season.",
            key="confirm_new_season",
        )
        if st.button("🏁 Start New Season / Reset", type="primary", disabled=not confirm_reset):
            success, msg = start_new_season(start_mode=start_mode)
            if success:
                flash("success", msg)
                st.rerun()
            else:
                st.error(msg)

    st.divider()
    with st.expander("⚙️ Advanced Settings"):
        st.subheader("Undo Last Reset")
        if has_undoable_reset():
            st.warning(
                "This restores players and matches to exactly how they were right before the most "
                "recent 'New Season / Reset' — undoing that reset and removing it from Previous "
                "Seasons. Any matches or players added since the reset will be lost. This only works "
                "once, right after the reset it's undoing."
            )
            confirm_undo = st.checkbox(
                "I understand this will undo the most recent season reset.", key="confirm_undo_reset"
            )
            if st.button("↩️ Undo Last Reset", disabled=not confirm_undo):
                success, msg = undo_last_reset()
                if success:
                    flash("success", msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.caption("There's no recent reset to undo.")

# ---- Sidebar info ------------------------------------------------------------
st.sidebar.divider()
try:
    _sheet_url = _spreadsheet().url
    st.sidebar.caption(f"Data is stored in [this Google Sheet]({_sheet_url}), tabs: "
                        f"`{PLAYERS_TAB}`, `{MATCHES_TAB}`, `{SESSION_TAB}`, `{SEASONS_TAB}`, "
                        f"`{SEASON_PLAYERS_TAB}`, `{SEASON_MATCHES_TAB}`.")
except Exception:
    st.sidebar.caption("Data is stored in a Google Sheet (see secrets.toml.example for setup).")
