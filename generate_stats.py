import os
import math
import random
import requests
from datetime import datetime, timedelta

# GitHub API configuration
TOKEN = os.environ['GITHUB_TOKEN']
USERNAME = 'pachir1su'
CURRENT_YEAR = datetime.now().year

HEADERS = {
    'Authorization': f'bearer {TOKEN}',
    'Content-Type': 'application/json',
}

# Two cards come off one layout. The portfolio embeds github-stats.svg from
# this repository, so that file keeps the paper tone its page is built on;
# the profile README uses the night-sky variant instead.
#
# Contrast, measured against each ground:
#   paper  figures 16.71:1  labels 7.77:1  display 5.04:1
#   night  figures 15.99:1  labels 6.90:1  display 7.16:1
PALETTES = {
    'paper': {
        'ground': '#fffdf6', 'text': '#1f1c14', 'muted': '#5a5040',
        'accent': '#c63b3b', 'glow': '#c63b3b', 'spark': '#c63b3b',
        'line': '#1f1c14', 'lineAlpha': '0.12', 'edgeAlpha': '0.16',
        'trackAlpha': '0.12', 'sky': False,
    },
    'night': {
        'ground': '#0b0a1f', 'text': '#e9e6ff', 'muted': '#9c93c9',
        'accent': '#a78bfa', 'glow': '#7c3aed', 'spark': '#fde68a',
        'line': '#a78bfa', 'lineAlpha': '0.22', 'edgeAlpha': '0.28',
        'trackAlpha': '0.16', 'sky': True,
    },
}

CARDS = [('github-stats.svg', 'paper'), ('github-stats-night.svg', 'night')]
HOURS_CARDS = [('github-hours.svg', 'paper'), ('github-hours-night.svg', 'night')]
ACTIVITY_CARDS = [('github-activity.svg', 'paper'), ('github-activity-night.svg', 'night')]

# Old-style serif for the display line, tabular mono for figures and labels.
SERIF = "'Iowan Old Style','Palatino Linotype','Book Antiqua',Palatino,Georgia,serif"
MONO = "'SF Mono','SFMono-Regular','Cascadia Mono','Segoe UI Mono','Roboto Mono','DejaVu Sans Mono',monospace"

# The starfield is seeded so a daily regeneration reproduces the same sky
# and the committed SVG does not churn.
STAR_SEED = 7
STAR_COUNT = 55

RING_RADIUS = 42
RING_LENGTH = 2 * math.pi * RING_RADIUS

# Korea does not observe daylight saving, so a fixed offset is enough to move
# the UTC commit timestamps into the hours the author actually worked.
TIMEZONE_OFFSET = timedelta(hours=9)
TIMEZONE_LABEL = 'Asia/Seoul'

# Commit history is walked one repository at a time. The cap bounds the API
# cost against a repository with a very long history; at 100 commits per page
# it still reaches much further back than this account has pushed.
COMMIT_PAGE_LIMIT = 10

WEEKDAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

# The README renders this card at its authored size inside a centred block,
# so one unit lands as one pixel and the type below is sized for that.
CARD_WIDTH = 495
CARD_HEIGHT = 208

# The hours card carries a 24 bar chart rather than a figure grid, so it is
# shorter than the stats card while keeping the same width and margins.
HOURS_CARD_WIDTH = 495
HOURS_CARD_HEIGHT = 190

# The activity card carries a year of contributions rather than a single day,
# so it is drawn at twice the stats card width and sits full bleed in README.
ACTIVITY_CARD_WIDTH = 990
ACTIVITY_CARD_HEIGHT = 260

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

# The repository list doubles as the source of the author node id, which the
# history query needs to count only this user's commits in shared repositories.
REPOS_QUERY = '''
query($login: String!) {
  user(login: $login) {
    id
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes {
        name
        owner { login }
      }
    }
  }
}
'''

# Commit timestamps come from the default branch rather than from push events,
# so one push of twenty commits counts twenty times and the sample is not
# capped at the last few hundred events the way an activity feed would be.
HISTORY_QUERY = '''
query($owner: String!, $name: String!, $author: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(author: {id: $author}, first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate }
          }
        }
      }
    }
  }
}
'''

# The contribution calendar is the same series the profile heatmap draws, so
# the card stays in step with the graph GitHub itself shows on the profile.
CALENDAR_QUERY = '''
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
'''

def _graphql(query, variables):
    """Run one GraphQL query and return its data, raising on API errors."""
    resp = requests.post(
        'https://api.github.com/graphql',
        headers=HEADERS,
        json={'query': query, 'variables': variables},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get('errors'):
        raise RuntimeError(payload['errors'][0].get('message', 'GraphQL error'))
    return payload['data']

def fetch_stats():
    """Fetch user stats from GitHub GraphQL API."""
    user = _graphql(QUERY, {'login': USERNAME})['user']

    return {
        'name': user['name'] or USERNAME,
        'stars':    sum(r['stargazers']['totalCount'] for r in user['repositories']['nodes']),
        'commits':  user['contributionsCollection']['totalCommitContributions'],
        'reviews':  user['contributionsCollection']['totalPullRequestReviewContributions'],
        'prs':      user['pullRequests']['totalCount'],
        'issues':   user['issues']['totalCount'],
        'followers': user['followers']['totalCount'],
    }

def fetch_commit_hours():
    """Bucket the author's commits by local hour and weekday.

    Every owned repository is walked separately. A repository that was never
    pushed to has no default branch to read, and a branch head that is not a
    commit carries no history, so both are skipped rather than failing the run.
    """
    account = _graphql(REPOS_QUERY, {'login': USERNAME})['user']
    authorId = account['id']

    hours = [0] * 24
    days = [0] * 7
    total = 0

    for repo in account['repositories']['nodes']:
        cursor = None
        for _ in range(COMMIT_PAGE_LIMIT):
            branch = _graphql(HISTORY_QUERY, {
                'owner': repo['owner']['login'],
                'name': repo['name'],
                'author': authorId,
                'after': cursor,
            })['repository']['defaultBranchRef']
            if not branch:
                break
            history = branch['target'].get('history')
            if not history:
                break

            for node in history['nodes']:
                stamp = datetime.strptime(node['committedDate'], '%Y-%m-%dT%H:%M:%SZ') + TIMEZONE_OFFSET
                hours[stamp.hour] += 1
                days[stamp.weekday()] += 1
                total += 1

            if not history['pageInfo']['hasNextPage']:
                break
            cursor = history['pageInfo']['endCursor']

    return {'hours': hours, 'days': days, 'total': total}

def fetch_contributions():
    """Read the last year of daily contributions, aggregated by week.

    Daily counts are noisy at this card width, so the series is summed per
    calendar week. A partial trailing week is kept as it stands rather than
    scaled up, so the last point never overstates the current week.
    """
    calendar = (_graphql(CALENDAR_QUERY, {'login': USERNAME})
                ['user']['contributionsCollection']['contributionCalendar'])

    weeks = []
    bestDay = 0
    for week in calendar['weeks']:
        days = week['contributionDays']
        if not days:
            continue
        weeks.append({
            'start': days[0]['date'],
            'count': sum(day['contributionCount'] for day in days),
        })
        bestDay = max(bestDay, max(day['contributionCount'] for day in days))

    return {
        'weeks': weeks,
        'total': calendar['totalContributions'],
        'bestDay': bestDay,
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

def _starfield(palette, blocked, ringCentre, ringRadius):
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
        fill = (palette['accent'] if tone < 0.18
                else palette['spark'] if tone < 0.28 else palette['text'])

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

def generate_svg(stats, theme, path):
    """Render one stats card in the given palette."""
    palette = PALETTES[theme]
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

    cellMarkup = []
    blocked = [(16, 18, 262, 48), (366, 22, 478, 48), (20, 46, 475, 60)]
    for index, (label, value) in enumerate(cells):
        cellX = 28 + (index % 2) * 162
        labelY = 78 + (index // 2) * 46
        blocked.append((cellX - 10, labelY - 15, cellX + 152, labelY + 30))
        cellMarkup.append(
            f'  <text x="{cellX}" y="{labelY}" font-family="{MONO}" font-size="12.5" '
            f'letter-spacing="0.9" fill="{palette["muted"]}">{label}</text>\n'
            f'  <text x="{cellX}" y="{labelY + 22}" font-family="{MONO}" font-size="23" '
            f'font-weight="600" fill="{palette["text"]}">{value}</text>'
        )
    statGrid = '\n'.join(cellMarkup)

    if palette['sky']:
        starfield = _starfield(palette, blocked, (410, 130), RING_RADIUS)
        ground = f'''  <defs>
    <clipPath id="gs-card">
      <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="6"/>
    </clipPath>
    <radialGradient id="gs-nebula" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{palette["glow"]}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{palette["glow"]}" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <g clip-path="url(#gs-card)">
    <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="{palette["ground"]}"/>
    <ellipse cx="410" cy="130" rx="118" ry="102" fill="url(#gs-nebula)"/>
{starfield}
  </g>'''
    else:
        ground = (f'  <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
                  f'rx="6" fill="{palette["ground"]}"/>')

    svg = f'''<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{name} GitHub stats, rank {rank}">
{ground}

  <text x="28" y="38" font-family="{SERIF}" font-size="21" fill="{palette["accent"]}">{name}</text>
  <text x="467" y="38" text-anchor="end" font-family="{MONO}" font-size="12" fill="{palette["muted"]}">@{USERNAME}</text>
  <line x1="28" y1="53" x2="467" y2="53" stroke="{palette["line"]}" stroke-opacity="{palette["lineAlpha"]}"/>

{statGrid}

  <g transform="translate(410,130)">
    <circle r="{RING_RADIUS}" fill="none" stroke="{palette["line"]}" stroke-opacity="{palette["trackAlpha"]}" stroke-width="5"/>
    <circle r="{RING_RADIUS}" fill="none" stroke="{palette["accent"]}" stroke-width="5"
      stroke-dasharray="{ringFill:.1f} {RING_LENGTH:.1f}" stroke-linecap="round" transform="rotate(-90)"/>
    <circle cx="{planetX:.1f}" cy="{planetY:.1f}" r="3.4" fill="{palette["spark"]}"/>
    <text y="-2" text-anchor="middle" font-family="{SERIF}" font-size="28" fill="{palette["text"] if palette["sky"] else palette["accent"]}">{rank}</text>
    <text y="20" text-anchor="middle" font-family="{MONO}" font-size="11.5" letter-spacing="0.9" fill="{palette["muted"]}">TOP {percentile:.0f}%</text>
  </g>

  <rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{palette["line"]}" stroke-opacity="{palette["edgeAlpha"]}"/>
</svg>'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f'Generated {path} ({theme}) — Rank: {rank} (top {percentile:.1f}%)')

def generate_hours_svg(activity, theme, path):
    """Render one active-hours card in the given palette."""
    palette = PALETTES[theme]
    hours = activity['hours']
    days = activity['days']

    # An account with no readable history still renders a flat, honest card
    # rather than dividing by zero.
    ceiling = max(hours) or 1
    peak = max(range(24), key=lambda hour: hours[hour])
    busiest = max(range(7), key=lambda day: days[day])

    chartLeft, chartRight = 28, 467
    baseline, barCeiling = 128, 56
    gap = 4
    barWidth = (chartRight - chartLeft - gap * 23) / 24

    bars = []
    for hour, count in enumerate(hours):
        # Every hour keeps a stub, so a quiet hour reads as a measured zero
        # instead of as a gap in the chart.
        height = max(barCeiling * count / ceiling, 1.5)
        x = chartLeft + hour * (barWidth + gap)
        fill = palette['spark'] if hour == peak else palette['accent']
        bars.append(
            f'  <rect x="{x:.1f}" y="{baseline - height:.1f}" width="{barWidth:.1f}" '
            f'height="{height:.1f}" rx="1.5" fill="{fill}" '
            f'fill-opacity="{0.35 + 0.65 * count / ceiling:.2f}"/>'
        )
    barMarkup = '\n'.join(bars)

    ticks = []
    for hour in range(0, 24, 3):
        x = chartLeft + hour * (barWidth + gap) + barWidth / 2
        ticks.append(
            f'  <text x="{x:.1f}" y="143" text-anchor="middle" font-family="{MONO}" '
            f'font-size="9.5" fill="{palette["muted"]}">{hour:02d}</text>'
        )
    tickMarkup = '\n'.join(ticks)

    cells = [
        ('PEAK HOUR', f'{peak:02d}:00'),
        ('BUSIEST DAY', WEEKDAYS[busiest]),
        ('COMMITS READ', f'{activity["total"]:,}'),
    ]
    cellMarkup = []
    for index, (label, value) in enumerate(cells):
        cellX = 28 + index * 152
        cellMarkup.append(
            f'  <text x="{cellX}" y="165" font-family="{MONO}" font-size="11" '
            f'letter-spacing="0.9" fill="{palette["muted"]}">{label}</text>\n'
            f'  <text x="{cellX}" y="182" font-family="{MONO}" font-size="17" '
            f'font-weight="600" fill="{palette["text"]}">{value}</text>'
        )
    figureGrid = '\n'.join(cellMarkup)

    # The stats card scatters a starfield over its empty ground, but bars read
    # against their own baseline, so this card keeps a plain ground in both
    # palettes and lets the chart carry the contrast.
    svg = f'''<svg width="{HOURS_CARD_WIDTH}" height="{HOURS_CARD_HEIGHT}" viewBox="0 0 {HOURS_CARD_WIDTH} {HOURS_CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Commits by hour of day, peak at {peak:02d}:00 {TIMEZONE_LABEL}">
  <rect x="0" y="0" width="{HOURS_CARD_WIDTH}" height="{HOURS_CARD_HEIGHT}" rx="6" fill="{palette["ground"]}"/>

  <text x="28" y="38" font-family="{SERIF}" font-size="21" fill="{palette["accent"]}">Active hours</text>
  <text x="467" y="38" text-anchor="end" font-family="{MONO}" font-size="12" fill="{palette["muted"]}">{TIMEZONE_LABEL}</text>
  <line x1="28" y1="53" x2="467" y2="53" stroke="{palette["line"]}" stroke-opacity="{palette["lineAlpha"]}"/>

{barMarkup}
  <line x1="28" y1="{baseline + 0.5}" x2="467" y2="{baseline + 0.5}" stroke="{palette["line"]}" stroke-opacity="{palette["lineAlpha"]}"/>
{tickMarkup}

{figureGrid}

  <rect x="0.5" y="0.5" width="{HOURS_CARD_WIDTH - 1}" height="{HOURS_CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{palette["line"]}" stroke-opacity="{palette["edgeAlpha"]}"/>
</svg>'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f'Generated {path} ({theme}) — peak {peak:02d}:00, {activity["total"]} commits read')

def generate_activity_svg(contributions, theme, path):
    """Render one contribution activity card in the given palette."""
    palette = PALETTES[theme]
    weeks = contributions['weeks']

    chartLeft, chartRight = 40, ACTIVITY_CARD_WIDTH - 40
    baseline, chartTop = 200, 78

    # A single week carries no slope, and an empty calendar carries no data at
    # all, so both fall back to a flat baseline instead of dividing by zero.
    ceiling = max((week['count'] for week in weeks), default=0) or 1
    span = max(len(weeks) - 1, 1)

    points = []
    for index, week in enumerate(weeks):
        x = chartLeft + (chartRight - chartLeft) * index / span
        y = baseline - (baseline - chartTop) * week['count'] / ceiling
        points.append((x, y))
    if not points:
        points = [(chartLeft, baseline), (chartRight, baseline)]

    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    area = (f'{points[0][0]:.1f},{baseline} ' + line +
            f' {points[-1][0]:.1f},{baseline}')

    # Only the ends and the middle are labelled; a tick under every week would
    # crowd the axis at this width.
    tickMarkup = ''
    if weeks:
        marks = {0: weeks[0]['start'], len(weeks) - 1: weeks[-1]['start']}
        marks[len(weeks) // 2] = weeks[len(weeks) // 2]['start']
        ticks = []
        for index in sorted(marks):
            x = points[index][0]
            anchor = 'start' if index == 0 else 'end' if index == len(weeks) - 1 else 'middle'
            label = datetime.strptime(marks[index], '%Y-%m-%d').strftime('%b %Y')
            ticks.append(
                f'  <text x="{x:.1f}" y="218" text-anchor="{anchor}" font-family="{MONO}" '
                f'font-size="10.5" fill="{palette["muted"]}">{label.upper()}</text>'
            )
        tickMarkup = '\n'.join(ticks)

    peak = max(range(len(points)), key=lambda index: weeks[index]['count']) if weeks else 0
    cells = [
        ('CONTRIBUTIONS &#183; 1Y', f'{contributions["total"]:,}'),
        ('BEST WEEK', f'{weeks[peak]["count"]:,}' if weeks else '0'),
        ('BEST DAY', f'{contributions["bestDay"]:,}'),
    ]
    cellMarkup = []
    for index, (label, value) in enumerate(cells):
        cellX = 40 + index * 172
        cellMarkup.append(
            f'  <text x="{cellX}" y="234" font-family="{MONO}" font-size="11" '
            f'letter-spacing="0.9" fill="{palette["muted"]}">{label}</text>\n'
            f'  <text x="{cellX + 168}" y="234" text-anchor="end" font-family="{MONO}" '
            f'font-size="15" font-weight="600" fill="{palette["text"]}">{value}</text>'
        )
    figureGrid = '\n'.join(cellMarkup)

    svg = f'''<svg width="{ACTIVITY_CARD_WIDTH}" height="{ACTIVITY_CARD_HEIGHT}" viewBox="0 0 {ACTIVITY_CARD_WIDTH} {ACTIVITY_CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Weekly contributions over the last year, {contributions["total"]} in total">
  <defs>
    <linearGradient id="ga-area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{palette["glow"]}" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="{palette["glow"]}" stop-opacity="0"/>
    </linearGradient>
  </defs>

  <rect x="0" y="0" width="{ACTIVITY_CARD_WIDTH}" height="{ACTIVITY_CARD_HEIGHT}" rx="6" fill="{palette["ground"]}"/>

  <text x="40" y="44" font-family="{SERIF}" font-size="21" fill="{palette["accent"]}">Contribution activity</text>
  <text x="{ACTIVITY_CARD_WIDTH - 40}" y="44" text-anchor="end" font-family="{MONO}" font-size="12" fill="{palette["muted"]}">per week &#183; last 12 months</text>
  <line x1="40" y1="59" x2="{ACTIVITY_CARD_WIDTH - 40}" y2="59" stroke="{palette["line"]}" stroke-opacity="{palette["lineAlpha"]}"/>

  <polygon points="{area}" fill="url(#ga-area)"/>
  <polyline points="{line}" fill="none" stroke="{palette["accent"]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{points[peak][0]:.1f}" cy="{points[peak][1]:.1f}" r="3.4" fill="{palette["spark"]}"/>
  <line x1="40" y1="{baseline + 0.5}" x2="{ACTIVITY_CARD_WIDTH - 40}" y2="{baseline + 0.5}" stroke="{palette["line"]}" stroke-opacity="{palette["lineAlpha"]}"/>
{tickMarkup}

{figureGrid}

  <rect x="0.5" y="0.5" width="{ACTIVITY_CARD_WIDTH - 1}" height="{ACTIVITY_CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{palette["line"]}" stroke-opacity="{palette["edgeAlpha"]}"/>
</svg>'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f'Generated {path} ({theme}) — {contributions["total"]} contributions over {len(weeks)} weeks')

if __name__ == '__main__':
    stats = fetch_stats()
    for path, theme in CARDS:
        generate_svg(stats, theme, path)

    activity = fetch_commit_hours()
    for path, theme in HOURS_CARDS:
        generate_hours_svg(activity, theme, path)

    contributions = fetch_contributions()
    for path, theme in ACTIVITY_CARDS:
        generate_activity_svg(contributions, theme, path)
