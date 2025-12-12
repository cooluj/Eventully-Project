# HCDE-310-Final-Eventully-P3-Project
A Flask web application that helps students find their community from over 1,231 UW clubs.

🎓 Eventully – AI-Powered Club Discovery for UW

A Flask web application that helps students find their community from over 1,231 UW clubs.

🌟 Overview

Eventully is a web platform designed to help University of Washington students discover clubs that align with their interests, major, and availability. UW has over 1,231 Registered Student Organizations, and many students often feel overwhelmed navigating outdated tools or incomplete information. Eventully solves this by combining real UW club data, data processing with Pandas, and a weighted matching algorithm to provide personalized recommendations.

The application includes a clean and modern UI, interactive filtering, event browsing, and personalized dashboards—all built with Flask, Pandas, and Tailwind CSS.

✨ Features
1. Personalized Club Matching

Weighted scoring algorithm:

50 points for category match

40 points for major alignment

10 points for time commitment

Generates match score, badge level, and reasons for recommendation.

2. Full-Club Directory

Browse all 1,231 UW clubs

Search by name or description

Filter by club category

Quick “View Details” links for each club

3. Event Browser

Shows events from various UW clubs (sample dataset)

Filter by category and weekday

Uses the Google Calendar URL API to create “Add to Calendar” links

4. Dashboard

Summary of clubs joined

Upcoming events

Personalized statistics for the user

5. Clean, Modern UI

Built using HTML + Tailwind CSS

Responsive design and animations

Card-based layouts and gradient accents

🧠 Data Processing

This project uses Pandas to load and process a real dataset of 1,231 UW clubs, each containing:

Club name

Description

Auto-generated category

Processing steps include:

Loading CSV data with Pandas

Filtering by category and keyword matching

Converting DataFrames into Python dictionaries

Computing recommendation scores

This data processing adds significant value by transforming raw club listings into personalized, ranked recommendations for students.

🧮 Matching Algorithm (High-Level)

Eventully uses a simple but effective weighted scoring model:

score =
    +50 if club category matches user preferences
    +40 if keywords align with user major
    +10 if club description matches time commitment preference


Badges are assigned:

Perfect Match (≥ 80)

Great Match (≥ 60)

Good Match (≥ 40)

If the user provides no preferences, Eventully falls back to browsing all clubs.

🧰 Technologies Used
Backend

Flask (routing, sessions, rendering templates)

Pandas (data loading, filtering, processing)

Frontend

Jinja2 Templates

Tailwind CSS

Responsive card-based UI

APIs

Google Calendar Event URL API
Used to generate one-click “Add to Calendar” links for events.

📁 Project Structure
eventully/
├── app.py
├── clubs_categorized.csv
├── requirements.txt
├── ai.txt
├── README.md
└── templates/
    ├── base.html
    ├── landing_polished.html
    ├── login_polished.html
    ├── onboarding_polished.html
    ├── recommendations_polished.html
    ├── clubs_polished.html
    ├── events_polished.html
    ├── dashboard_polished.html
    └── club_detail_polished.html

▶️ How to Run This Project
1. Install dependencies
pip install -r requirements.txt

2. Run the Flask server
python app.py

3. Open in browser

Visit:

http://127.0.0.1:5050

4. Login workflow

Enter any name + any email to begin.
