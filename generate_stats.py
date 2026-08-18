import os
import math
import random
import requests
from datetime import datetime

# GitHub API configuration
TOKEN = os.environ['GITHUB_TOKEN']
USERNAME = 'pachir1su'
CURRENT_YEAR = datetime.now().year

HEADERS = {
    'Authorization': f'bearer {TOKEN}',
    'Content-Type': 'application/json',
}

# Night-sky palette, shared with README. Text sits on bare VOID — the nebula
# is confined to the ring — so contrast holds at figures 15.99:1, labels
# 6.90:1, display 7.16:1. Inside the ring the pool lifts the ground to
# #24154c, where the rank reads 13.39:1 and its caption 5.78:1.
VOID = '#0b0a1f'
STAR = '#e9e6ff'
MUTED = '#9c93c9'
VIOLET = '#a78bfa'
DEEP = '#7c3aed'
GOLD = '#fde68a'

# Old-style serif for the display line, tabular mono for figures and labels.
SERIF = "'Iowan Old Style','Palatino Linotype','Book Antiqua',Palatino,Georgia,serif"
MONO = "'SF Mono','SFMono-Regular','Cascadia Mono','Segoe UI Mono','Roboto Mono','DejaVu Sans Mono',monospace"

# The starfield is seeded so a daily regeneration reproduces the same sky
# and the committed SVG does not churn.
STAR_SEED = 7
STAR_COUNT = 55

RING_RADIUS = 42
RING_LENGTH = 2 * math.pi * RING_RADIUS

# The README renders this card at its authored size inside a centred block,
# so one unit lands as one pixel and the type below is sized for that.
CARD_WIDTH = 495
CARD_HEIGHT = 208

# GraphQL query to fetch user statistics
QUERY = '''
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes { stargazers { totalCount } }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
    }
    pullRequests { totalCount }
    issues { totalCount }
  }
}
'''

def fetch_stats():
    """Fetch user stats from GitHub GraphQL API."""
    resp = requests.post(
        'https://api.github.com/graphql',
        headers=HEADERS,
        json={'query': QUERY, 'variables': {'login': USERNAME}},
        timeout=30,
    )
    resp.raise_for_status()
    user = resp.json()['data']['user']

    return {
        'name': user['name'] or USERNAME,
        'stars':    sum(r['stargazers']['totalCount'] for r in user['repositories']['nodes']),
        'commits':  user['contributionsCollection']['totalCommitContributions'],
        'reviews':  user['contributionsCollection']['totalPullRequestReviewContributions'],
        'prs':      user['pullRequests']['totalCount'],
        'issues':   user['issues']['totalCount'],
        'followers': user['followers']['totalCount'],
    }

def _normalcdf(mean, sigma, x):
    """Normal CDF via error function."""
    z = (x - mean) / (sigma * math.sqrt(2))
    return 0.5 * (1 + math.erf(z))

def calculate_rank(stats):
    """Calculate rank and percentile using the same algorithm as github-readme-stats."""
    metrics = [
        (stats['commits'],  250, 2),
        (stats['prs'],       50, 3),
        (stats['issues'],    25, 1),
        (stats['reviews'],    2, 1),
        (stats['stars'],     50, 4),
        (stats['followers'], 10, 1),
    ]
    total_weight = sum(w for _, _, w in metrics)
    score = sum(
        w * _normalcdf(median, median, value)
        for value, median, w in metrics
    ) / total_weight

    percentile = (1 - score) * 100

    if percentile < 1:    return 'S', percentile
    if percentile < 12.5: return 'A+', percentile
    if percentile < 25:   return 'A', percentile
    if percentile < 37.5: return 'A-', percentile
    if percentile < 50:   return 'B+', percentile
    if percentile < 62.5: return 'B', percentile
    if percentile < 75:   return 'B-', percentile
    if percentile < 87.5: return 'C+', percentile
    return 'C', percentile

def _starfield(blocked, ringCentre, ringRadius):
    """Scatter stars over the empty ground only.

    Rejection sampling against the text blocks and the ring keeps a star from
    landing beside a figure, where it reads as punctuation rather than sky.
    The seed is fixed, so the sampling reproduces the same sky every run.
    """
    rng = random.Random(STAR_SEED)
    marks = []
    attempts = 0
    while len(marks) < STAR_COUNT and attempts < 6000:
        attempts += 1
        starX = round(rng.uniform(5, CARD_WIDTH - 5), 1)
        starY = round(rng.uniform(5, CARD_HEIGHT - 5), 1)
        radius = round(rng.uniform(0.5, 1.7), 2)
        alpha = round(rng.uniform(0.25, 0.9), 2)
        tone = rng.random()
        fill = VIOLET if tone < 0.18 else (GOLD if tone < 0.28 else STAR)

        # A sparkle reaches further than its centre, so clear the blocks by its
        # arm rather than by the point alone.
        sparkle = len(marks) % 9 == 4
        arm = round(radius * 2.6, 2)
        reach = arm if sparkle else radius
        if any(x0 - reach <= starX <= x1 + reach and y0 - reach <= starY <= y1 + reach
               for x0, y0, x1, y1 in blocked):
            continue
        if math.dist((starX, starY), ringCentre) < ringRadius + 14 + reach:
            continue

        if sparkle:
            marks.append(
                f'    <g stroke="{fill}" stroke-opacity="{alpha}" stroke-width="0.7" stroke-linecap="round">\n'
                f'      <line x1="{starX - arm}" y1="{starY}" x2="{starX + arm}" y2="{starY}"/>\n'
                f'      <line x1="{starX}" y1="{starY - arm}" x2="{starX}" y2="{starY + arm}"/>\n'
                f'    </g>'
            )
        else:
            marks.append(
                f'    <circle cx="{starX}" cy="{starY}" r="{radius}" '
                f'fill="{fill}" fill-opacity="{alpha}"/>'
            )
    return '\n'.join(marks)

def _escape(text):
    """Escape text for use in SVG text nodes and attribute values."""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))

def generate_svg(stats):
    """Generate a night-sky GitHub Stats SVG."""
    rank, percentile = calculate_rank(stats)

    # The arc encodes the score itself, so it moves with the data instead of
    # snapping to one of nine per-grade lengths. A planet rides its leading end.
    score = max(0.0, min(1.0, 1 - percentile / 100))
    ringFill = RING_LENGTH * score
    orbitAngle = math.radians(-90 + 360 * score)
    planetX = RING_RADIUS * math.cos(orbitAngle)
    planetY = RING_RADIUS * math.sin(orbitAngle)

    name = _escape(stats['name'])

    # Two columns, three rows. Labels sit above their figure so the numbers
    # share one vertical rhythm and stay scannable. The gap inside a pair is
    # deliberately tighter than the gap between rows, so each label binds to
    # its own figure rather than floating between two.
    cells = [
        ('STARS EARNED', stats['stars']),
        (f'COMMITS &#183; {CURRENT_YEAR}', stats['commits']),
        ('PULL REQUESTS', stats['prs']),
        ('ISSUES OPENED', stats['issues']),
        ('CODE REVIEWS', stats['reviews']),
        ('FOLLOWERS', stats['followers']),
    ]

    # Blocks the starfield must keep clear of, so no star lands beside a
    # figure and reads as a stray decimal point.
    cellMarkup = []
    for index, (label, value) in enumerate(cells):
        cellX = 28 + (index % 2) * 162
        labelY = 78 + (index // 2) * 46
        cellMarkup.append(
            f'  <text x="{cellX}" y="{labelY}" font-family="{MONO}" font-size="12.5" '
            f'letter-spacing="0.9" fill="{MUTED}">{label}</text>\n'
            f'  <text x="{cellX}" y="{labelY + 22}" font-family="{MONO}" font-size="23" '
            f'font-weight="600" fill="{STAR}">{value}</text>'
        )
    statGrid = '\n'.join(cellMarkup)

    blocked = [(16, 18, 262, 48), (366, 22, 478, 48), (20, 46, 475, 60)]
    for index in range(len(cells)):
        cellX = 28 + (index % 2) * 162
        labelY = 78 + (index // 2) * 46
        blocked.append((cellX - 10, labelY - 15, cellX + 152, labelY + 30))
    starfield = _starfield(blocked, (410, 130), RING_RADIUS)

    svg = f'''<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{name} GitHub stats, rank {rank}">
  <defs>
    <clipPath id="gs-card">
      <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="6"/>
    </clipPath>
    <radialGradient id="gs-nebula" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{DEEP}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <g clip-path="url(#gs-card)">
    <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="{VOID}"/>
    <ellipse cx="410" cy="130" rx="118" ry="102" fill="url(#gs-nebula)"/>
{starfield}
  </g>

  <text x="28" y="38" font-family="{SERIF}" font-size="21" fill="{VIOLET}">{name}</text>
  <text x="467" y="38" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">@{USERNAME}</text>
  <line x1="28" y1="53" x2="467" y2="53" stroke="{VIOLET}" stroke-opacity="0.22"/>

{statGrid}

  <g transform="translate(410,130)">
    <circle r="{RING_RADIUS}" fill="none" stroke="{VIOLET}" stroke-opacity="0.16" stroke-width="5"/>
    <circle r="{RING_RADIUS}" fill="none" stroke="{VIOLET}" stroke-width="5"
      stroke-dasharray="{ringFill:.1f} {RING_LENGTH:.1f}" stroke-linecap="round" transform="rotate(-90)"/>
    <circle cx="{planetX:.1f}" cy="{planetY:.1f}" r="3.4" fill="{GOLD}"/>
    <text y="-2" text-anchor="middle" font-family="{SERIF}" font-size="28" fill="{STAR}">{rank}</text>
    <text y="20" text-anchor="middle" font-family="{MONO}" font-size="11.5" letter-spacing="0.9" fill="{MUTED}">TOP {percentile:.0f}%</text>
  </g>

  <rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{VIOLET}" stroke-opacity="0.28"/>
</svg>'''

    with open('github-stats.svg', 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f'Generated github-stats.svg — Rank: {rank} (top {percentile:.1f}%)')

if __name__ == '__main__':
    stats = fetch_stats()
    generate_svg(stats)
