"""
Eventully - Polished Version
Beautiful UI inspired by Figma design with all 1,231 real UW clubs
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import pandas as pd
import re
from urllib.parse import urlencode, quote_plus
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'eventully-polished-secret'

# Load real UW clubs
CLUBS_DF = pd.read_csv('clubs_categorized.csv')
CLUBS = CLUBS_DF.to_dict('records')

print(f"✅ Loaded {len(CLUBS)} real UW clubs")

# Sample events for demo
EVENTS = [
    {"id": 1, "name": "Intro to Machine Learning Workshop", "club": "Advanced Robotics at the University of Washington", "category": "Engineering/Tech", "weekday": "Monday", "time": "18:00", "location": "CSE 003", "is_public": True, "description": "Learn the basics of ML with hands-on coding", "attendees": 45, "capacity": 60, "image": "https://images.unsplash.com/photo-1555255707-c07966088b7b?w=800"},
    {"id": 2, "name": "Mental Health Awareness Fair", "club": "Active Minds at the University of Washington", "category": "Service/Volunteer", "weekday": "Tuesday", "time": "17:00", "location": "HUB 214", "is_public": True, "description": "Join us for activities and resources", "attendees": 78, "capacity": 100, "image": "https://images.unsplash.com/photo-1544027993-37dbfe43562a?w=800"},
    {"id": 3, "name": "Weekly Worship & Fellowship", "club": "Acts2Fellowship", "category": "Religious/Spiritual", "weekday": "Friday", "time": "19:00", "location": "Denny Hall 201", "is_public": True, "description": "Community gathering for prayer and friendship", "attendees": 32, "capacity": 50, "image": "https://images.unsplash.com/photo-1528605105345-5344ea20e269?w=800"},
    {"id": 4, "name": "Portfolio Showcase Night", "club": "Advancing Husky Artistry", "category": "Arts/Creative", "weekday": "Wednesday", "time": "16:00", "location": "Art Building 105", "is_public": True, "description": "Present your work and get feedback", "attendees": 28, "capacity": 40, "image": "https://images.unsplash.com/photo-1460661419201-fd4cecdf8a8b?w=800"},
    {"id": 5, "name": "Trading Competition Finals", "club": "Algorithmic Trading Club", "category": "Business/Entrepreneurship", "weekday": "Thursday", "time": "18:30", "location": "Paccar 291", "is_public": False, "description": "Championship round of our trading sim", "attendees": 24, "capacity": 30, "image": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800"},
    {"id": 6, "name": "Cultural Night Celebration", "club": "Afghanistan Student Union at the University of Washington", "category": "Cultural/Identity", "weekday": "Saturday", "time": "19:00", "location": "HUB Ballroom", "is_public": True, "description": "Food, music, and traditional performances", "attendees": 156, "capacity": 200, "image": "https://images.unsplash.com/photo-1533174072545-7a4b6ad7a6c3?w=800"},
    {"id": 7, "name": "MCAT Study Marathon", "club": "Alpha Epsilon Delta Pre-Health Honor Society", "category": "Pre-Health/Medical", "weekday": "Sunday", "time": "10:00", "location": "Savery 138", "is_public": False, "description": "All-day study session with practice tests", "attendees": 18, "capacity": 25, "image": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=800"},
    {"id": 8, "name": "Soccer Tournament", "club": "Women's Club Soccer at UW", "category": "Sports/Recreation", "weekday": "Saturday", "time": "14:00", "location": "IMA Field", "is_public": True, "description": "Spring championship games", "attendees": 89, "capacity": 150, "image": "https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=800"},
]

# In-memory storage
USERS = {}
MEMBERSHIPS = {}
USER_PREFERENCES = {}
POLLS = []

# ------------------------------------------------------------------------------
# SMART MATCH ALGORITHM
# ------------------------------------------------------------------------------

def smart_match_clubs(categories, major="", time_commitment=""):
    """Simple, reliable matching based on categories and major"""
    matches = []

    # If no filters at all, show all clubs
    if not categories and not major:
        for club in CLUBS:
            matches.append({
                'club': club,
                'score': 50,
                'reasons': ["Browse all UW clubs"],
                'badge': None
            })
        return matches

    for club in CLUBS:
        score = 0
        reasons = []
        club_text = f"{club['Club']} {club['Description']}".lower()

        # 1. Categories (50 points)
        if categories and club['Category'] in categories:
            score += 50
            reasons.append(f"{club['Category']} club")

        # 2. Major relevance (40 points)
        major_keywords = {
            'Computer Science': ['computer', 'software', 'coding', 'programming', 'tech', 'cs', 'algorithm', 'ai', 'data', 'cyber'],
            'Engineering': ['engineer', 'technical', 'robotics', 'design', 'build', 'mechanical', 'electrical'],
            'Business': ['business', 'entrepreneur', 'finance', 'marketing', 'consulting', 'management'],
            'Pre-Med': ['medicine', 'medical', 'health', 'pre-med', 'premed', 'clinical', 'hospital', 'dental'],
            'Biology': ['bio', 'science', 'research', 'lab', 'ecology', 'cell', 'molecular'],
            'Psychology': ['psych', 'mental', 'cognitive', 'behavior', 'counseling', 'wellness'],
            'Art': ['art', 'design', 'creative', 'visual', 'music', 'theater', 'dance', 'film'],
            'Communications': ['media', 'journalism', 'communication', 'broadcasting', 'writing'],
            'Economics': ['economic', 'finance', 'market', 'business'],
            'Political Science': ['political', 'policy', 'government', 'law', 'justice']
        }

        if major and major in major_keywords:
            for keyword in major_keywords[major]:
                if keyword in club_text:
                    score += 40
                    reasons.append(f"Great for {major} students")
                    break

        # 3. Time commitment (10 points)
        if time_commitment:
            commitment_keywords = {
                'low': ['casual', 'flexible', 'open', 'welcome'],
                'medium': ['weekly', 'regular', 'meeting'],
                'high': ['competitive', 'team', 'championship']
            }
            for keyword in commitment_keywords.get(time_commitment, []):
                if keyword in club_text:
                    score += 10
                    break

        # Badge
        badge = None
        if score >= 80:
            badge = 'perfect'
        elif score >= 60:
            badge = 'great'
        elif score >= 40:
            badge = 'good'

        if score > 0:
            matches.append({
                'club': club,
                'score': min(score, 100),
                'reasons': reasons if reasons else ["Matches your preferences"],
                'badge': badge
            })

    matches.sort(key=lambda x: x['score'], reverse=True)

    # Safety net
    if not matches and categories:
        for club in CLUBS:
            if club['Category'] in categories:
                matches.append({
                    'club': club,
                    'score': 50,
                    'reasons': [f"{club['Category']} club"],
                    'badge': 'good'
                })

    return matches

# ------------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------------

def get_current_user():
    return USERS.get(session.get('user_email'))

def is_member_of_club(user_email, club_name):
    return club_name in MEMBERSHIPS.get(user_email, [])

def build_calendar_link(event):
    title = f"{event['name']} · {event['club']}"
    details = f"{event['description']}\n\nClub: {event['club']}\nLocation: {event['location']}"
    params = {'action': 'TEMPLATE', 'text': title, 'details': details, 'location': event['location']}
    return f"https://calendar.google.com/calendar/u/0/r/eventedit?{urlencode(params, quote_via=quote_plus)}"

# ------------------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------------------

@app.route('/')
def index():
    user = get_current_user()
    if user:
        return redirect(url_for('dashboard'))

    category_counts = CLUBS_DF['Category'].value_counts().to_dict()
    top_categories = dict(list(category_counts.items())[:5])

    stats = {
        'total_clubs': len(CLUBS),
        'total_events': len(EVENTS),
        'categories': len(category_counts),
        'top_categories': top_categories,
        'active_students': 15000
    }
    return render_template('landing_polished.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        name = request.form.get('name', '').strip()

        if not email.endswith('.edu'):
            flash('Please use a .edu email address', 'error')
            return render_template('login_polished.html')

        if email not in USERS:
            USERS[email] = {'email': email, 'name': name, 'university': 'University of Washington', 'joined': datetime.now().strftime('%B %Y')}
            MEMBERSHIPS[email] = []

        session['user_email'] = email
        session['user_name'] = USERS[email]['name']
        return redirect(url_for('onboarding'))

    return render_template('login_polished.html')

@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if request.method == 'POST':
        categories = request.form.getlist('categories')
        major = request.form.get('major', '')
        time = request.form.get('time_commitment', '')

        USER_PREFERENCES[user['email']] = {
            'categories': categories,
            'major': major,
            'time_commitment': time
        }

        return redirect(url_for('recommendations'))

    categories = sorted(CLUBS_DF['Category'].unique())
    majors = ['Computer Science', 'Engineering', 'Business', 'Pre-Med', 'Biology',
              'Psychology', 'Art', 'Economics', 'Political Science', 'Communications', 'Other']

    return render_template('onboarding_polished.html', categories=categories, majors=majors)

@app.route('/recommendations')
def recommendations():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    prefs = USER_PREFERENCES.get(user['email'])
    if not prefs:
        return redirect(url_for('onboarding'))

    categories = prefs.get('categories', [])
    major = prefs.get('major', '')
    time_commitment = prefs.get('time_commitment', '')

    all_matches = smart_match_clubs(categories, major, time_commitment)

    page = int(request.args.get('page', 0))
    per_page = 20
    start = page * per_page
    end = start + per_page

    matches = all_matches[start:end]
    has_more = end < len(all_matches)

    return render_template(
        'recommendations_polished.html',
        matches=matches,
        total_matches=len(all_matches),
        current_page=page,
        has_more=has_more
    )

@app.route('/dashboard')
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    user_club_names = MEMBERSHIPS.get(user['email'], [])
    user_clubs = [c for c in CLUBS if c['Club'] in user_club_names]
    visible_events = [e for e in EVENTS if e['is_public'] or e['club'] in user_club_names]

    stats = {
        'clubs_joined': len(user_clubs),
        'events_upcoming': len([e for e in visible_events if e['weekday'] in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']]),
        'total_available': len(CLUBS),
        'new_this_week': 8
    }

    return render_template('dashboard_polished.html', user=user, clubs=user_clubs[:6], events=visible_events[:6], stats=stats)

@app.route('/clubs')
def clubs():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()

    filtered = CLUBS_DF.copy()
    if category != 'all':
        filtered = filtered[filtered['Category'] == category]
    if search:
        mask = filtered['Club'].str.contains(search, case=False, na=False) | filtered['Description'].str.contains(search, case=False, na=False)
        filtered = filtered[mask]

    clubs_list = filtered.to_dict('records')
    user_club_names = MEMBERSHIPS.get(user['email'], [])

    for club in clubs_list:
        club['is_member'] = club['Club'] in user_club_names

    categories = ['all'] + sorted(CLUBS_DF['Category'].unique())

    return render_template('clubs_polished.html', clubs=clubs_list[:50], categories=categories,
                           current_category=category, search_query=search, result_count=len(clubs_list))

@app.route('/events')
def events():
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    category = request.args.get('category', 'all')
    day = request.args.get('day', 'all')

    user_club_names = MEMBERSHIPS.get(user['email'], [])
    visible_events = [e for e in EVENTS if e['is_public'] or e['club'] in user_club_names]

    if category != 'all':
        visible_events = [e for e in visible_events if e['category'] == category]
    if day != 'all':
        visible_events = [e for e in visible_events if e['weekday'] == day]

    categories = ['all'] + sorted(list(set(e['category'] for e in EVENTS)))
    days = ['all', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    return render_template('events_polished.html', events=visible_events, categories=categories,
                           days=days, current_category=category, current_day=day)

@app.route('/club/<path:club_name>')
def club_detail(club_name):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    club = next((c for c in CLUBS if c['Club'] == club_name), None)
    if not club:
        flash('Club not found', 'error')
        return redirect(url_for('clubs'))

    club_events = [e for e in EVENTS if e['club'] == club_name]
    is_member = is_member_of_club(user['email'], club_name)
    similar = [c for c in CLUBS if c['Category'] == club['Category'] and c['Club'] != club_name][:4]

    return render_template('club_detail_polished.html', club=club, events=club_events,
                           is_member=is_member, similar_clubs=similar, build_calendar_link=build_calendar_link)

@app.route('/join/<path:club_name>')
def join_club(club_name):
    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    if club_name not in MEMBERSHIPS[user['email']]:
        MEMBERSHIPS[user['email']].append(club_name)
        flash('Successfully joined!', 'success')
    
    return redirect(url_for('club_detail', club_name=club_name))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    print("=" * 70)
    print("🎨 EVENTULLY POLISHED - BEAUTIFUL UI")
    print("=" * 70)
    print(f"\n✨ {len(CLUBS)} Real UW Clubs")
    print(f"🎯 {len(CLUBS_DF['Category'].unique())} Categories")
    print(f"📅 {len(EVENTS)} Featured Events")
    print("\n📱 http://127.0.0.1:5050")
    print("🔑 Login: demo@uw.edu\n")
    print("=" * 70)
    app.run(debug=True, port=5050)
