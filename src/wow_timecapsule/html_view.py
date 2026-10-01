from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SECTION_LABELS = {
    "character_profile": "Profile",
    "equipment": "Equipment",
    "achievements": "Achievements",
    "achievement_details": "Achievement reference details",
    "appearance": "Appearance",
    "hunter_pets": "Hunter pets",
    "pets": "Account pets",
    "mounts": "Account mounts",
    "professions": "Professions",
    "reputations": "Reputations",
    "statistics": "Statistics",
    "quests": "Completed quests",
}

GAME_LABELS = {
    "profile": "Retail",
    "profile-classic": "Classic progression",
    "profile-classic1x": "Classic Era / Hardcore / seasonal",
}


def generate_html(root: str | Path) -> Path:
    root = Path(root).resolve()
    database = root / "wow_archive.sqlite"
    if not database.is_file():
        raise FileNotFoundError("Choose an archive containing wow_archive.sqlite")
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    payload = _archive_payload(db)
    db.close()
    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    target = root / "index.html"
    target.write_text(_document(encoded), encoding="utf-8")
    return target


def _archive_payload(db: sqlite3.Connection) -> dict[str, Any]:
    latest = db.execute("""
        SELECT c.*, s.*
        FROM character c
        JOIN character_snapshot s ON s.character_id=c.character_id
        JOIN archive_run r ON r.archive_run_id=s.archive_run_id AND r.status='complete'
        WHERE s.character_snapshot_id=(
            SELECT s2.character_snapshot_id
            FROM character_snapshot s2
            JOIN archive_run r2 ON r2.archive_run_id=s2.archive_run_id AND r2.status='complete'
            WHERE s2.character_id=c.character_id
            ORDER BY s2.observed_at DESC, s2.character_snapshot_id DESC LIMIT 1
        )
        ORDER BY c.character_name COLLATE NOCASE, c.realm_name COLLATE NOCASE
    """).fetchall()
    characters = [_character_payload(db, row) for row in latest]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "characters": characters,
        "collections": _collections_payload(db),
        "timeline": _timeline_payload(db),
    }


def _character_payload(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    sid = row["character_snapshot_id"]
    cid = row["character_id"]
    equipment = []
    for item in db.execute("""
        SELECT e.name,e.slot_type,ce.raw_json
        FROM character_equipment ce JOIN equipment e ON e.equipment_id=ce.equipment_id
        WHERE ce.character_snapshot_id=? ORDER BY e.slot_type,e.name
    """, (sid,)):
        raw = _json(item["raw_json"])
        equipment.append({
            "name": item["name"] or "Unknown item",
            "slot": item["slot_type"] or "OTHER",
            "level": (raw.get("level") or {}).get("value"),
        })
    achievements = [{
        "id": item["achievement_id"],
        "name": item["name"] or f"Achievement {item['achievement_id']}",
        "description": item["description"],
        "requirements": item["requirements"],
        "reward": item["reward_description"],
        "category": item["category"],
        "account_wide": item["is_account_wide"],
        "points": item["points"],
        "completed": _timestamp(item["completed_at"]),
    } for item in db.execute("""
        SELECT a.achievement_id,a.name,a.description,a.requirements,
               a.reward_description,a.category,a.is_account_wide,a.points,ca.completed_at
        FROM character_achievement ca JOIN achievement a ON a.achievement_id=ca.achievement_id
        WHERE ca.character_snapshot_id=? AND ca.is_completed=1
        ORDER BY COALESCE(ca.completed_at,'') DESC,a.name COLLATE NOCASE
    """, (sid,))]
    professions = [dict(item) for item in db.execute("""
        SELECT p.profession_id,p.name,cp.skill_points,cp.max_skill_points
        FROM character_profession cp JOIN profession p ON p.profession_id=cp.profession_id
        WHERE cp.character_snapshot_id=? ORDER BY p.name COLLATE NOCASE
    """, (sid,))]
    for profession in professions:
        profession["tiers"] = [dict(item) for item in db.execute("""
            SELECT pt.name,cpt.skill_points,cpt.max_skill_points,cpt.known_recipes
            FROM character_profession_tier cpt
            JOIN profession_tier pt
              ON pt.profession_tier_id=cpt.profession_tier_id
            JOIN profession p ON p.profession_id=pt.profession_id
            WHERE cpt.character_snapshot_id=? AND p.profession_id=?
            ORDER BY pt.profession_tier_id DESC
        """, (sid, profession["profession_id"]))]
    reputations = [dict(item) for item in db.execute("""
        SELECT r.name,cr.standing,cr.value
        FROM character_reputation cr JOIN reputation r ON r.reputation_id=cr.reputation_id
        WHERE cr.character_snapshot_id=? ORDER BY r.name COLLATE NOCASE
    """, (sid,))]
    hunter_pets = [dict(item) for item in db.execute("""
        SELECT name,level,slot,is_active,creature_id,display_id
        FROM character_hunter_pet WHERE character_snapshot_id=?
        ORDER BY is_active DESC,slot,name COLLATE NOCASE
    """, (sid,))]
    outcomes = [{
        "key": item["section_name"],
        "label": SECTION_LABELS.get(item["section_name"], item["section_name"].replace("_", " ").title()),
        "status": item["status"],
        "count": item["record_count"],
        "detail": item["detail"] or "",
    } for item in db.execute("""
        SELECT section_name,status,record_count,detail
        FROM capture_section WHERE character_snapshot_id=? ORDER BY section_name
    """, (sid,))]
    screenshots = [dict(item) for item in db.execute(
        "SELECT relative_path,caption,added_at FROM screenshot WHERE character_id=? ORDER BY added_at",
        (cid,),
    )]
    memories = [dict(item) for item in db.execute(
        "SELECT title,body,created_at FROM character_memory WHERE character_id=? ORDER BY created_at DESC",
        (cid,),
    )]
    return {
        "id": cid,
        "snapshot_id": sid,
        "name": row["character_name"],
        "realm": row["realm_name"] or row["realm_slug"],
        "region": row["region"].upper(),
        "game": GAME_LABELS.get(row["namespace"], row["namespace"]),
        "captured": row["observed_at"],
        "level": row["level"],
        "race": row["race_name"],
        "class_name": row["class_name"],
        "specialization": row["specialization"],
        "faction": row["faction"],
        "guild": row["guild_name"],
        "achievement_points": row["achievement_points"],
        "equipment": equipment,
        "achievements": achievements,
        "professions": professions,
        "reputations": reputations,
        "hunter_pets": hunter_pets,
        "outcomes": outcomes,
        "screenshots": screenshots,
        "memories": memories,
    }


def _collections_payload(db: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in ("pets", "mounts"):
        latest = db.execute(
            "SELECT * FROM collection_snapshot WHERE kind=? ORDER BY observed_at DESC,collection_snapshot_id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        successful = db.execute(
            "SELECT * FROM collection_snapshot WHERE kind=? AND status='captured' ORDER BY observed_at DESC,collection_snapshot_id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        records: list[dict[str, Any]] = []
        if successful and kind == "pets":
            records = [dict(item) for item in db.execute("""
                SELECT COALESCE(p.custom_name,p.name,'Unknown pet') AS name,p.name AS species,
                       cp.level,cp.quality,cp.is_favorite
                FROM collection_pet cp JOIN pet p ON p.pet_id=cp.pet_id
                WHERE cp.collection_snapshot_id=? ORDER BY name COLLATE NOCASE
            """, (successful["collection_snapshot_id"],))]
        elif successful:
            records = [dict(item) for item in db.execute("""
                SELECT m.name,cm.is_collected
                FROM collection_mount cm JOIN mount m ON m.mount_id=cm.mount_id
                WHERE cm.collection_snapshot_id=? ORDER BY m.name COLLATE NOCASE
            """, (successful["collection_snapshot_id"],))]
        result[kind] = {
            "status": latest["status"] if latest else "unavailable",
            "detail": (latest["detail"] or "") if latest else "No collection capture has been saved.",
            "captured": successful["observed_at"] if successful else None,
            "records": records,
            "using_previous_capture": bool(latest and successful and latest["collection_snapshot_id"] != successful["collection_snapshot_id"]),
        }
    return result


def _timeline_payload(db: sqlite3.Connection) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(value: Any, kind: str, character: str, realm: str, title: str,
            detail: str = "", image: str | None = None) -> None:
        timestamp = _iso_timestamp(value)
        if timestamp:
            events.append({
                "timestamp": timestamp,
                "day": timestamp[:10],
                "kind": kind,
                "character": character,
                "realm": realm,
                "title": title,
                "detail": detail,
                "image": image,
            })

    for row in db.execute("""
        SELECT DISTINCT c.character_name,COALESCE(c.realm_name,c.realm_slug) AS realm,
               s.last_login_if_available
        FROM character_snapshot s JOIN character c ON c.character_id=s.character_id
        JOIN archive_run r ON r.archive_run_id=s.archive_run_id AND r.status='complete'
        WHERE s.last_login_if_available IS NOT NULL
    """):
        add(row["last_login_if_available"], "played", row["character_name"], row["realm"],
            "Last played", "Last-login time reported by Blizzard; this is not a full play-session log.")
    for row in db.execute("""
        SELECT c.character_name,COALESCE(c.realm_name,c.realm_slug) AS realm,
               s.observed_at,s.level
        FROM character_snapshot s JOIN character c ON c.character_id=s.character_id
        JOIN archive_run r ON r.archive_run_id=s.archive_run_id AND r.status='complete'
    """):
        add(row["observed_at"], "capture", row["character_name"], row["realm"],
            "Character archived", f"Level {row['level']}" if row["level"] is not None else "")
    seen_account_achievements: set[tuple[int, str]] = set()
    for row in db.execute("""
        SELECT DISTINCT c.character_name,COALESCE(c.realm_name,c.realm_slug) AS realm,
               ca.completed_at,a.achievement_id,a.name,a.description,a.is_account_wide
        FROM character_achievement ca
        JOIN character_snapshot s ON s.character_snapshot_id=ca.character_snapshot_id
        JOIN archive_run r ON r.archive_run_id=s.archive_run_id AND r.status='complete'
        JOIN character c ON c.character_id=s.character_id
        JOIN achievement a ON a.achievement_id=ca.achievement_id
        WHERE ca.is_completed=1 AND ca.completed_at IS NOT NULL
    """):
        character_name, realm = row["character_name"], row["realm"]
        description = row["description"] or ""
        if row["is_account_wide"]:
            key = (int(row["achievement_id"]), str(row["completed_at"]))
            if key in seen_account_achievements:
                continue
            seen_account_achievements.add(key)
            character_name, realm = "Account-wide", ""
            description = (description + " Account-wide achievement.").strip()
        add(row["completed_at"], "achievement", character_name, realm,
            row["name"] or "Achievement completed", description)
    for row in db.execute("""
        SELECT c.character_name,COALESCE(c.realm_name,c.realm_slug) AS realm,
               sc.added_at,sc.caption,sc.relative_path
        FROM screenshot sc JOIN character c ON c.character_id=sc.character_id
    """):
        add(row["added_at"], "screenshot", row["character_name"], row["realm"],
            row["caption"] or "Screenshot added", "", row["relative_path"])
    for row in db.execute("""
        SELECT c.character_name,COALESCE(c.realm_name,c.realm_slug) AS realm,
               m.created_at,m.title,m.body
        FROM character_memory m JOIN character c ON c.character_id=m.character_id
    """):
        add(row["created_at"], "memory", row["character_name"], row["realm"],
            row["title"] or "Memory added", row["body"] or "")
    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events


def _json(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        return datetime.fromtimestamp(number, UTC).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return value


def _iso_timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        return datetime.fromtimestamp(number, UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    except (ValueError, TypeError, OSError, OverflowError):
        return str(value)


def _document(data: str) -> str:
    # All presentation code and archive data are embedded; the page makes no network requests.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WoW Time Capsule</title>
<style>
:root{{--ink:#e8edf6;--muted:#9da9bb;--panel:#171d29;--panel2:#202838;--line:#303b50;--gold:#e3b55f;--blue:#6ab7ff;--ok:#75d49b;--bad:#ff8e8e}}
*{{box-sizing:border-box}} body{{margin:0;background:#0d1119;color:var(--ink);font:15px/1.5 system-ui,"Segoe UI",sans-serif}}
header{{padding:34px 5vw 24px;background:linear-gradient(135deg,#18263b,#111722);border-bottom:1px solid var(--line)}}
h1,h2,h3{{margin:.15em 0;color:#fff}} h1{{font-size:30px}} .muted{{color:var(--muted)}}
main{{max-width:1280px;margin:auto;padding:28px 5vw 60px}} button,input{{font:inherit}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 24px}} button{{border:1px solid var(--line);background:var(--panel2);color:var(--ink);padding:10px 15px;border-radius:10px;cursor:pointer}} button:hover,button.active{{border-color:var(--gold);color:#fff}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));gap:15px}} .card,.section{{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:18px;box-shadow:0 12px 35px #0004}}
.card{{cursor:pointer;display:flex;gap:14px;align-items:center}} .card:hover{{border-color:var(--gold);transform:translateY(-1px)}}
.avatar{{width:62px;height:62px;border-radius:13px;object-fit:cover;background:linear-gradient(145deg,#315680,#624b7b);display:grid;place-items:center;font-size:22px;font-weight:700}}
.detail{{display:none}} .detail.active{{display:block}} .hero{{display:grid;grid-template-columns:minmax(180px,280px) 1fr;gap:24px;margin-bottom:18px}} .hero img{{width:100%;max-height:250px;object-fit:cover;border-radius:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}} .section{{margin-bottom:16px}} ul{{padding-left:20px}} .facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}} .fact{{background:var(--panel2);padding:10px;border-radius:9px}}
.status{{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px}} .captured{{background:#183b2a;color:var(--ok)}} .request_failed{{background:#442326;color:var(--bad)}} .unavailable{{background:#343947;color:#c6ceda}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}} .gallery img{{width:100%;height:170px;object-fit:cover;border-radius:10px}} .memory{{border-left:3px solid var(--gold);padding-left:12px;margin:12px 0}}
.equipment{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}} .item{{background:var(--panel2);border-radius:8px;padding:9px;margin-bottom:5px}} .slot{{color:var(--gold);font-size:12px}} .achievement-search,select{{width:100%;background:#0d1119;border:1px solid var(--line);color:#fff;padding:10px;border-radius:8px}}
.achievement summary{{cursor:pointer}} .achievement .more{{padding:9px 0 2px;color:var(--muted)}} .tiers{{margin:8px 0 0 12px;border-left:2px solid var(--line);padding-left:10px}}
.timeline{{position:relative;margin-left:18px;border-left:2px solid var(--line);padding-left:26px}} .event{{position:relative;margin:0 0 14px}} .event:before{{content:'';position:absolute;width:11px;height:11px;border-radius:50%;background:var(--gold);left:-33px;top:17px}} .event-head{{display:flex;justify-content:space-between;gap:12px}} .event img{{width:150px;max-height:100px;object-fit:cover;border-radius:8px;margin-top:8px}} .kind{{color:var(--blue);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}
.scroll{{max-height:370px;overflow:auto}} .empty{{color:var(--muted);font-style:italic}} @media(max-width:700px){{.hero{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>WoW Time Capsule</h1><div class="muted">A quiet album of preserved character information · Generated <span id="generated"></span></div></header>
<main><div class="toolbar"><button id="rosterBtn" class="active">Characters</button><button id="timelineBtn">Timeline</button><button id="collectionsBtn">Shared Collections</button></div><div id="app"></div></main>
<script>const archive={data};
const app=document.getElementById('app'), rosterBtn=document.getElementById('rosterBtn'), timelineBtn=document.getElementById('timelineBtn'), collectionsBtn=document.getElementById('collectionsBtn'), esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
document.getElementById('generated').textContent=archive.generated_at;
const status=o=>`<span class="status ${{esc(o.status)}}">${{esc(o.status.replace('_',' '))}}</span>${{o.count===null||o.count===undefined?'':` · ${{o.count}} record${{o.count===1?'':'s'}}`}}${{o.detail?`<div class="muted">${{esc(o.detail)}}</div>`:''}}`;
function roster(){{document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));rosterBtn.classList.add('active');app.innerHTML=`<div class="cards">${{archive.characters.map((c,i)=>{{const shot=c.screenshots[0];return `<div class="card" onclick="character(${{i}})">${{shot?`<img class="avatar" src="${{encodeURI(shot.relative_path)}}">`:`<div class="avatar">${{esc(c.name.slice(0,2).toUpperCase())}}</div>`}}<div><h3>${{esc(c.name)}}</h3><div>${{esc(c.realm)}} · ${{esc(c.region)}}</div><div class="muted">${{esc(c.game)}} · Level ${{esc(c.level??'?')}} ${{esc(c.class_name??'')}}</div><small class="muted">${{esc(c.captured)}}</small></div></div>`}}).join('')}}</div>${{archive.characters.length?'':'<p class="empty">No successful character snapshots are in this archive.</p>'}}`;}}
function character(i){{const c=archive.characters[i], shot=c.screenshots[0];app.innerHTML=`<button onclick="roster()">← Character roster</button><div class="detail active"><div class="hero section">${{shot?`<img src="${{encodeURI(shot.relative_path)}}">`:`<div class="avatar" style="width:100%;height:210px;font-size:52px">${{esc(c.name.slice(0,2).toUpperCase())}}</div>`}}<div><div class="muted">${{esc(c.game)}}</div><h1>${{esc(c.name)}}</h1><h3>${{esc(c.realm)}} · ${{esc(c.region)}}</h3><div class="facts">${{[['Level',c.level],['Race',c.race],['Class',c.class_name],['Specialization',c.specialization],['Faction',c.faction],['Guild',c.guild],['Achievement points',c.achievement_points],['Captured',c.captured]].map(x=>`<div class="fact"><small class="muted">${{x[0]}}</small><br>${{esc(x[1]??'Not captured')}}</div>`).join('')}}</div></div></div>
<div class="section"><h2>Overview</h2>${{c.memories.length?c.memories.map(m=>`<div class="memory"><b>${{esc(m.title||'Memory')}}</b><div>${{esc(m.body).split(String.fromCharCode(10)).join('<br>')}}</div><small class="muted">${{esc(m.created_at)}}</small></div>`).join(''):'<p class="empty">No personal notes yet.</p>'}}</div>
<div class="section"><h2>Equipment</h2><div class="equipment">${{c.equipment.map(x=>`<div class="item"><div class="slot">${{esc(x.slot)}}</div>${{esc(x.name)}}${{x.level?` <span class="muted">· ilvl ${{x.level}}</span>`:''}}</div>`).join('')||'<p class="empty">No equipment records captured.</p>'}}</div></div>
<div class="section"><h2>Achievements</h2><input class="achievement-search" placeholder="Search completed achievements" oninput="filterAchievements(this.value)"><div id="achievementList" class="scroll">${{c.achievements.map(x=>`<details class="achievement item" data-name="${{esc((x.name+' '+(x.description||'')+' '+(x.category||'')).toLowerCase())}}"><summary><b>${{esc(x.name)}}</b>${{x.points?` · ${{x.points}} points`:''}}<div class="muted">${{esc(x.completed||'Completion date unavailable')}}${{x.category?` · ${{esc(x.category)}}`:''}}${{x.account_wide?' · Account-wide':''}}</div></summary><div class="more">${{x.description?`<p>${{esc(x.description)}}</p>`:''}}${{x.requirements?`<b>How to earn it</b><p>${{esc(x.requirements).split(String.fromCharCode(10)).join('<br>')}}</p>`:''}}${{x.reward?`<b>Reward</b><p>${{esc(x.reward)}}</p>`:''}}${{!x.description&&!x.requirements&&!x.reward?'<span>Detailed reference data was not available for this saved achievement.</span>':''}}</div></details>`).join('')||'<p class="empty">No completed achievements captured.</p>'}}</div></div>
<div class="grid"><div class="section"><h2>Professions</h2>${{c.professions.map(x=>`<div class="item"><b>${{esc(x.name)}}</b>${{x.skill_points!==null?` · ${{esc(x.skill_points)}}/${{esc(x.max_skill_points??'?')}} total`:''}}${{x.tiers.length?`<div class="tiers">${{x.tiers.map(t=>`<div><b>${{esc(t.name||'Skill tier')}}</b> · ${{esc(t.skill_points??'?')}}/${{esc(t.max_skill_points??'?')}}${{t.known_recipes?` · ${{t.known_recipes}} known recipes`:''}}</div>`).join('')}}</div>`:''}}</div>`).join('')||'<p class="empty">No professions captured. Check Archive details to see whether Blizzard returned this section.</p>'}}</div><div class="section"><h2>Reputations</h2><div class="scroll">${{c.reputations.map(x=>`<div class="item"><b>${{esc(x.name)}}</b> · ${{esc(x.standing||x.value||'Captured')}}</div>`).join('')||'<p class="empty">No reputations captured.</p>'}}</div></div></div>
<div class="section"><h2>Hunter companions</h2>${{c.hunter_pets.map(x=>`<div class="item"><b>${{esc(x.name||'Unnamed companion')}}</b>${{x.level?` · Level ${{x.level}}`:''}}${{x.is_active?' · Active':''}}</div>`).join('')||'<p class="empty">No hunter companion records captured.</p>'}}</div>
<div class="section"><h2>Memories</h2><div class="gallery">${{c.screenshots.map(x=>`<figure><img src="${{encodeURI(x.relative_path)}}"><figcaption>${{esc(x.caption||'')}}</figcaption></figure>`).join('')||'<p class="empty">No screenshots added.</p>'}}</div></div>
<div class="section"><h2>Archive details</h2>${{c.outcomes.map(o=>`<div class="item"><b>${{esc(o.label)}}</b><br>${{status(o)}}</div>`).join('')||'<p class="empty">This older snapshot has no section diagnostics.</p>'}}</div></div>`;window.scrollTo(0,0);}}
function showCharacterById(id){{const index=archive.characters.findIndex(c=>c.id===id);if(index>=0)character(index);}}
function filterAchievements(q){{document.querySelectorAll('.achievement').forEach(x=>x.style.display=x.dataset.name.includes(q.toLowerCase())?'':'none')}}
function timeline(){{document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));timelineBtn.classList.add('active');app.innerHTML=`<h1>Timeline</h1><p class="muted">Achievements, screenshots, memories, archive captures, and Blizzard's last-login time when available. This is not a complete play-session history.</p><div class="section"><select id="timelineFilter" onchange="renderTimeline(this.value)"><option value="">All events</option><option value="played">Played</option><option value="achievement">Achievements</option><option value="screenshot">Screenshots</option><option value="memory">Memories</option><option value="capture">Archive captures</option></select></div><div id="timelineEvents" class="timeline"></div>`;renderTimeline('');}}
function renderTimeline(kind){{const target=document.getElementById('timelineEvents');if(!target)return;const events=archive.timeline.filter(x=>!kind||x.kind===kind);target.innerHTML=events.map(x=>`<article class="event section"><div class="event-head"><div><div class="kind">${{esc(x.kind)}}</div><h3>${{esc(x.title)}}</h3><div>${{esc(x.character)}}${{x.realm?` · ${{esc(x.realm)}}`:''}}</div></div><time class="muted">${{esc(x.day)}}</time></div>${{x.detail?`<p>${{esc(x.detail)}}</p>`:''}}${{x.image?`<img src="${{encodeURI(x.image)}}">`:''}}</article>`).join('')||'<p class="empty">No dated events of this type are saved.</p>';window.scrollTo(0,0);}}
function collections(){{document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));collectionsBtn.classList.add('active');const block=(title,c)=>`<div class="section"><h2>${{title}}</h2>${{status({{status:c.status,count:c.records.length,detail:c.detail}})}}${{c.using_previous_capture?'<p class="muted">Showing the most recent successful saved collection because the latest request failed.</p>':''}}<div class="scroll">${{c.records.map(x=>`<div class="item"><b>${{esc(x.name)}}</b>${{x.species&&x.species!==x.name?` · ${{esc(x.species)}}`:''}}${{x.level?` · Level ${{x.level}}`:''}}</div>`).join('')||'<p class="empty">No saved records.</p>'}}</div></div>`;app.innerHTML=`<h1>Shared Collections</h1><p class="muted">Account collections are shown once and are not attributed to an individual character.</p><div class="grid">${{block('Battle pets',archive.collections.pets)}}${{block('Mounts',archive.collections.mounts)}}</div>`;}}
rosterBtn.onclick=roster;timelineBtn.onclick=timeline;collectionsBtn.onclick=collections;location.hash==='#timeline'?timeline():roster();</script></body></html>"""
