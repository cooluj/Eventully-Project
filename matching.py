"""Smart club matching algorithm: scores every club against a student's
selected categories, major, and time-commitment preference."""
import re

MAJOR_KEYWORDS = {
    "Computer Science": ["computer", "software", "coding", "programming", "tech", "cs", "algorithm", "ai", "data", "cyber"],
    "Engineering": ["engineer", "technical", "robotics", "design", "build", "mechanical", "electrical"],
    "Business": ["business", "entrepreneur", "finance", "marketing", "consulting", "management"],
    "Pre-Med": ["medicine", "medical", "health", "pre-med", "premed", "clinical", "hospital", "dental"],
    "Biology": ["bio", "science", "research", "lab", "ecology", "cell", "molecular"],
    "Psychology": ["psych", "mental", "cognitive", "behavior", "counseling", "wellness"],
    "Art": ["art", "design", "creative", "visual", "music", "theater", "dance", "film"],
    "Communications": ["media", "journalism", "communication", "broadcasting", "writing"],
    "Economics": ["economic", "finance", "market", "business"],
    "Political Science": ["political", "policy", "government", "law", "justice"],
}

COMMITMENT_KEYWORDS = {
    "low": ["casual", "flexible", "open", "welcome"],
    "medium": ["weekly", "regular", "meeting"],
    "high": ["competitive", "team", "championship"],
}

MAJORS = list(MAJOR_KEYWORDS.keys()) + ["Other"]


def keyword_matches(text, keyword):
    if len(keyword) <= 3:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def smart_match_clubs(clubs, categories, major="", time_commitment=""):
    """clubs: list of Club model instances. Returns a list of dicts sorted by score desc."""
    matches = []
    categories = set(categories or [])

    if not categories and not major:
        for club in sorted(clubs, key=lambda c: (-c.member_count, c.name)):
            matches.append({"club": club, "score": 50, "reasons": ["Browse all UW clubs"], "badge": None})
        return matches

    for club in clubs:
        score = 0
        reasons = []
        club_text = f"{club.name} {club.description}".lower()
        major_hits = []

        if categories and club.category in categories:
            score += 55
            reasons.append(f"{club.category} club")

        if major and major in MAJOR_KEYWORDS:
            for keyword in MAJOR_KEYWORDS[major]:
                if keyword_matches(club_text, keyword):
                    major_hits.append(keyword)
            if major_hits:
                score += min(35, 15 + (len(major_hits) * 5))
                reasons.append(f"Connects with {major}")

        if time_commitment:
            for keyword in COMMITMENT_KEYWORDS.get(time_commitment, []):
                if keyword_matches(club_text, keyword):
                    score += 10
                    reasons.append("Fits your time commitment")
                    break

        # Time-commitment keywords alone are too weak to make a club feel relevant.
        if not reasons or reasons == ["Fits your time commitment"]:
            continue

        badge = None
        if score >= 80:
            badge = "perfect"
        elif score >= 60:
            badge = "great"
        elif score >= 40:
            badge = "good"

        if score > 0:
            matches.append({
                "club": club,
                "score": min(score, 100),
                "reasons": reasons or ["Matches your preferences"],
                "badge": badge,
            })

    matches.sort(
        key=lambda m: (
            m["score"],
            len(m["reasons"]),
            m["club"].member_count,
            -len(m["club"].name),
        ),
        reverse=True,
    )

    if not matches and categories:
        for club in sorted(clubs, key=lambda c: c.name):
            if club.category in categories:
                matches.append({"club": club, "score": 50, "reasons": [f"{club.category} club"], "badge": "good"})

    return matches
