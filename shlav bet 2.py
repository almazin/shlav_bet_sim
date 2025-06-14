import streamlit as st
import openai
import os
import uuid
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import requests

# Load environment variables from .env if present
load_dotenv()

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not set. Please set it in your .env file (locally) or Streamlit Cloud secrets.")
client = openai.OpenAI(api_key=api_key)

# --- Memory Store ---
if 'user_profile' not in st.session_state:
    st.session_state.user_profile = {}
if 'dialogue_history' not in st.session_state:
    st.session_state.dialogue_history = []
if 'current_case' not in st.session_state:
    st.session_state.current_case = ""
if 'evaluation' not in st.session_state:
    st.session_state.evaluation = {}
if 'case_log' not in st.session_state:
    st.session_state.case_log = []

GOOGLE_API_KEY = "AIzaSyAHrqfi4t6ajvYqMG2TAaIgBNV3tOoklZ8"  # Provided by user
GOOGLE_CX = "507139094c6134ea4"

def get_image_url(query, api_key=GOOGLE_API_KEY, cx=GOOGLE_CX):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "searchType": "image",
        "key": api_key,
        "cx": cx,
        "num": 1
    }
    response = requests.get(url, params=params)
    results = response.json()
    if "items" in results:
        return results["items"][0]["link"]
    return None

# --- Step 1: User Profile Form + Topic Selector ---
def user_profile_form():
    st.sidebar.header("📋 Your Profile")
    with st.sidebar.form("profile_form"):
        residency_year = st.selectbox("Residency Year", ["PGY1", "PGY2", "PGY3", "PGY4"])
        recent_rotations = st.multiselect("Recent Rotations",
                                          ["Cardiology", "Nephrology", "Hematology", "ICU", "ID", "Gastro"])
        strengths = st.text_area("Clinical Strengths")
        weaknesses = st.text_area("Weak Areas")
        learning_goals = st.text_area("Learning Goals")
        difficulty = st.selectbox("Preferred Difficulty", ["Easy", "Medium", "Hard"])
        topic = st.selectbox("Focus Topic",
                             ["Any", "Chest Pain", "Fever", "Shortness of Breath", "Abdominal Pain", "Anemia",
                              "Hypertension"])
        submit = st.form_submit_button("✅ Save Profile")
        if submit:
            st.session_state.user_profile = {
                "residency_year": residency_year,
                "recent_rotations": recent_rotations,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "learning_goals": learning_goals,
                "difficulty": difficulty,
                "topic": topic
            }
            st.success("Profile saved!")


# --- Agent 1: Case Generator ---
def generate_case(profile):
    system_prompt = f"""
You are a board-certified internal medicine specialist.
Generate a realistic, concise oral exam case for the Israeli 'Shlav Bet'.

Customize for this resident:
- Year: {profile['residency_year']}
- Rotations: {', '.join(profile['recent_rotations'])}
- Weak Areas: {profile['weaknesses']}
- Learning Goal: {profile['learning_goals']}
- Difficulty: {profile['difficulty']}
- Topic: {profile['topic']}

Include ONLY:
1. Chief complaint and history (max 3-4 sentences)
2. Vital signs

Keep the case brief and focused. Only output the case text.
"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()


# --- Agent 2: Patient Response ---
def get_patient_response(user_input, extra_data=None):
    case = st.session_state.current_case
    history = "\n".join([f"User: {q}\nPatient: {a}" for q, a in st.session_state.dialogue_history])
    difficulty = st.session_state.user_profile.get("difficulty", "Easy")

    # Determine if the user ordered a test (simple keyword check)
    test_keywords = ["ecg", "ekg", "ct", "mri", "x-ray", "xray", "eeg"]
    ordered_test = next((kw for kw in test_keywords if kw in user_input.lower()), None)
    image_url = None
    if ordered_test:
        # Use the test and case topic for a more relevant search
        topic = st.session_state.user_profile.get("topic", "")
        search_query = f"{ordered_test} {topic}"
        image_url = get_image_url(search_query)

    # Adjust system prompt for difficulty
    if difficulty.lower() in ["medium", "hard"]:
        system_prompt = f"""
You are a simulated patient case for a residency exam.
Respond ONLY in a clinical, third-person style (e.g., 'The CT scan shows...', 'The CO2 levels are...').
Do NOT use first person (do not say 'I', 'my', 'me', etc). Only provide information as if reporting results or findings.
If you provide diagnostic data (e.g., ECG, CT, EEG), ONLY describe the raw findings. Do NOT interpret or suggest what the findings mean (e.g., do not say 'ST elevation is indicative of MI').
Respond only with what the case allows: history, vitals, results of tests that have been ordered.
Do not give away the diagnosis. Keep it realistic.
"""
    else:
        system_prompt = f"""
You are a simulated patient case for a residency exam.
Respond ONLY in a clinical, third-person style (e.g., 'The CT scan shows...', 'The CO2 levels are...').
Do NOT use first person (do not say 'I', 'my', 'me', etc). Only provide information as if reporting results or findings.
Respond only with what the case allows: history, vitals, results of tests that have been ordered.
Do not give away the diagnosis. Keep it realistic.
"""

    if extra_data:
        user_input = f"{user_input}\n\nAdditional data provided: {extra_data}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Case: {case}\n\nHistory so far:\n{history}\n\nUser: {user_input}"}
    ]

    response = client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        temperature=0.5
    )
    reply = response.choices[0].message.content.strip()

    # Show the image if found, and debug output
    if image_url:
        st.image(image_url, caption=f"{ordered_test.upper()} result")
        st.write("Image URL:", image_url)
    else:
        if ordered_test:
            st.write("No image found for query:", search_query)
    return reply


# --- Agent 3: Evaluation ---
def evaluate_case():
    case = st.session_state.current_case
    history = "\n".join([f"User: {q}\nPatient: {a}" for q, a in st.session_state.dialogue_history])

    system_prompt = """
You are an internal medicine examiner.
Evaluate the resident's reasoning based on their responses.
Be strict: only give a high score if the resident made a correct, complete diagnosis and justified it well. If the diagnosis is missing or incorrect, score should be low (<60).
Only state what the user actually did. Do not assume a correct diagnosis if it was not made. If the user did not make a diagnosis, say so explicitly.
Score on differential diagnosis, test ordering, and final diagnosis.
Return a brief analysis with:
- score (0-100),
- strengths,
- weaknesses,
- final verdict,
- correct answer (diagnosis/title of the case, as a single line at the top labeled 'Correct Answer'),
- recommended treatment for the correct diagnosis (as a single line labeled 'Recommended Treatment').
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Case: {case}\n\nResident-Patient Dialogue:\n{history}"}
    ]

    response = client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        temperature=0.5
    )

    return response.choices[0].message.content.strip()


# --- Adaptive Case Generation ---
def get_adaptive_profile():
    # Use last evaluation and responses to adapt the next case
    profile = st.session_state.user_profile.copy()
    if st.session_state.case_log:
        last_case = st.session_state.case_log[-1]
        last_score = last_case["Score"]
        last_verdict = last_case["Verdict"].lower()
        # If user missed the diagnosis or scored low, lower difficulty or focus on weak areas
        if last_score < 60 or "incorrect" in last_verdict or "missed" in last_verdict:
            profile["difficulty"] = "Easy"
            # Optionally, focus on weak areas if provided
            if profile["weaknesses"]:
                profile["topic"] = profile["weaknesses"]
        # If user did well, increase difficulty
        elif last_score > 80:
            profile["difficulty"] = "Hard"
    return profile


# --- Analytics ---
def show_analytics():
    st.subheader("📈 Performance Analytics")
    if not st.session_state.case_log:
        st.info("No completed cases yet.")
        return

    df = pd.DataFrame(st.session_state.case_log)
    st.dataframe(df[['Topic', 'Score', 'Verdict']])

    st.line_chart(df.set_index("Case #")['Score'])

    avg_score = df["Score"].mean()
    st.metric("Average Score", f"{avg_score:.1f}")


# --- Main Streamlit App ---
st.title("🏥 Internal Medicine Oral Exam Simulator")
user_profile_form()

# --- Add a floating doctor profile icon to the top right corner ---
profile_icon_html = """
<style>
#custom-profile-icon {
    position: fixed;
    top: 3.5rem; /* Lowered from 1.2rem */
    right: 2rem;
    z-index: 9999;
    font-size: 2.2rem;
    background: #fff;
    border-radius: 50%;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    padding: 0.2em 0.35em;
    border: 1px solid #eee;
}
</style>
<div id=\"custom-profile-icon\">🧑‍⚕️</div>
"""
st.markdown(profile_icon_html, unsafe_allow_html=True)

# Remove the sidebar icon (do not add it)

# --- Add a refresh button to the sidebar ---
if st.sidebar.button("🔄 Refresh App"):
    st.rerun()

def handle_user_input():
    user_input = st.session_state.get("user_input", "")
    if user_input:
        with st.spinner("Simulating patient response..."):
            patient_reply = get_patient_response(user_input)
            st.session_state.dialogue_history.append((user_input, patient_reply))
            st.session_state["user_input"] = ""  # This is safe in a callback
        st.rerun()

if st.session_state.user_profile:
    st.header("🩺 Case Simulation")

    if not st.session_state.current_case:
        if st.button("🎲 Generate New Case"):
            with st.spinner("Generating personalized case..."):
                st.session_state.current_case = generate_case(st.session_state.user_profile)
                st.session_state.dialogue_history = []

    if st.session_state.current_case:
        st.subheader("📝 Case")
        st.markdown(st.session_state.current_case)

        st.subheader("💬 Dialogue History")
        for q, a in st.session_state.dialogue_history:
            st.markdown(f"**You:** {q}")
            st.markdown(f"**Patient:** {a}")

        # Only keep the user input for the next question or action
        with st.form("user_input_form", clear_on_submit=True):
            user_input = st.text_input("Your next question or action", key="user_input")
            submitted = st.form_submit_button("Send")
            if submitted and user_input:
                with st.spinner("Simulating patient response..."):
                    patient_reply = get_patient_response(user_input)
                    st.session_state.dialogue_history.append((user_input, patient_reply))
                st.rerun()

        if st.button("🧾 Evaluate Performance"):
            with st.spinner("Evaluating your clinical reasoning..."):
                evaluation_text = evaluate_case()
                st.session_state.evaluation = evaluation_text

                # Extract score from eval string
                import re

                score_match = re.search(r"score\s*[:\-]?\s*(\d+)", evaluation_text, re.IGNORECASE)
                score = int(score_match.group(1)) if score_match else 0
                verdict_match = re.search(r"verdict\s*[:\-]?\s*(.+)", evaluation_text, re.IGNORECASE)
                verdict = verdict_match.group(1).strip() if verdict_match else "N/A"

                st.session_state.case_log.append({
                    "Case #": len(st.session_state.case_log) + 1,
                    "Topic": st.session_state.user_profile["topic"],
                    "Score": score,
                    "Verdict": verdict
                })

    if st.session_state.evaluation:
        st.subheader("📊 Evaluation")
        st.markdown(st.session_state.evaluation)

        if st.button("🔁 New Adaptive Case"):
            st.session_state.current_case = ""
            st.session_state.dialogue_history = []
            st.session_state.evaluation = {}
            # Use adaptive profile for next case
            adaptive_profile = get_adaptive_profile()
            st.session_state.user_profile = adaptive_profile
            st.rerun()

    with st.expander("📚 View My Case Analytics"):
        show_analytics()

# --- Sidebar deployment instructions ---
st.sidebar.markdown("""
---
**Deployment:**
- To share this app, deploy it for free at [streamlit.io/cloud](https://streamlit.io/cloud) and share the link.
- Or, share your code and requirements.txt for others to run locally with Python and Streamlit.
""")
