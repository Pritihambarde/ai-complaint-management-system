"""AI engine: category (ML), priority (hybrid rules), sentiment, explainability, spam filter."""
import os, re, joblib
import sklearn

ML_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "ml")
MODEL_PATH = os.path.join(ML_DIR, "model.joblib")
VERSION_PATH = os.path.join(ML_DIR, "model.version")
DATA_PATH = os.path.join(ML_DIR, "data", "complaints.csv")
CONFIDENCE_THRESHOLD = 0.35        # below this -> "Other" (manual triage by the admin desk)

# Safety words use whole-word matching, so "firewall" or "beaten path" do not trigger a false alarm.
CRITICAL_RE = re.compile(r"\b(threat\w*|ragg\w*|harass\w*|assault\w*|abus\w*|fire|unsafe|suicid\w*|molest\w*|bull(?:y|ied|ying)|beat(?:s|ing|en)?|forc(?:e|ed|ing)|blackmail\w*|inappropriate)\b")
HIGH = ["electric", "shock", "short circuit", "theft", "stolen", "cheat", "plagiar", "hall ticket", "marks are missing",
        "marks missing", "not allowed to sit", "not allowed for the exam", "server is down", "server down", "data loss"]
LOW = ["suggest", "would like", "please consider", "request for", "requesting", "propose"]
DISTRESS = ["scared", "afraid", "fear", "threat", "unsafe", "suicide", "helpless", "harass", "bully", "abuse", "cry"]
ANGRY = ["worst", "pathetic", "useless", "fed up", "disgusting", "unacceptable", "angry", "ridiculous", "tired of"]
ABUSIVE = ["idiot", "stupid", "bastard", "damn", "fuck", "shit", "bitch", "asshole"]

FALLBACK = {      # used only if the trained model cannot run
    "Ragging & Harassment": ["ragging", "senior", "threat", "harass", "bully"],
    "Lab & Equipment": ["lab", "computer", "system", "software", "server", "printer"],
    "Teaching & Syllabus": ["lecture", "faculty", "professor", "syllabus", "teacher", "doubt"],
    "Timetable & Attendance": ["timetable", "attendance", "schedule", "clash", "batch"],
    "Exams & Marks": ["exam", "result", "hall ticket", "marks", "revaluation", "question paper"],
    "Projects & Placements": ["project", "guide", "placement", "internship", "company", "resume"],
    "Classroom Infrastructure": ["wifi", "projector", "toilet", "washroom", "classroom", "fan", "light", "bench"],
}

def _train():
    """Train TF-IDF + Logistic Regression from ml/data/complaints.csv (takes a few seconds)."""
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    df = pd.read_csv(DATA_PATH).dropna()
    m = Pipeline([("tfidf", TfidfVectorizer(lowercase=True, stop_words="english", ngram_range=(1, 2), sublinear_tf=True)),
                  ("clf", LogisticRegression(max_iter=2000, C=10))])
    m.fit(df.text, df.category)
    joblib.dump(m, MODEL_PATH)
    open(VERSION_PATH, "w").write(sklearn.__version__)
    print("AI model trained for this computer (scikit-learn", sklearn.__version__ + ")")
    return m

def _load_model():
    """Load the saved model; retrain automatically if it is missing or was built with another scikit-learn version."""
    try:
        same = os.path.exists(VERSION_PATH) and open(VERSION_PATH).read().strip() == sklearn.__version__
        if os.path.exists(MODEL_PATH) and same:
            return joblib.load(MODEL_PATH)
        return _train() if os.path.exists(DATA_PATH) else None
    except Exception as e:
        print("Could not load/train the AI model, using keyword fallback:", repr(e))
        return None

_model = _load_model()

def detect_priority(text: str) -> str:
    t = text.lower()
    if CRITICAL_RE.search(t): return "Critical"
    if any(k in t for k in HIGH): return "High"
    if any(k in t for k in LOW): return "Low"
    return "Medium"

def detect_sentiment(text: str) -> str:
    t = text.lower()
    if any(k in t for k in DISTRESS): return "Distressed"
    if any(k in t for k in ANGRY): return "Angry"
    return "Neutral"

def is_abusive(text: str) -> bool:
    return any(w in ABUSIVE for w in re.findall(r"[a-z]+", text.lower()))

def is_spam(text: str):
    """Returns a reason string if the text is abusive or gibberish, else None."""
    t = text.lower()
    words = re.findall(r"[a-z]+", t)
    if any(w in ABUSIVE for w in words):
        return "Please use respectful language in your complaint"
    if len(words) < 4:
        return "Please describe the problem in a few proper words"
    with_vowel = sum(1 for w in words if re.search(r"[aeiou]", w))
    if with_vowel / len(words) < 0.6 or re.search(r"(.)\1{5,}", t):
        return "Complaint text looks like gibberish"
    return None

def _explain(text: str, category: str, _model=None):
    if _model is None:
        return [k for k in FALLBACK.get(category, []) if k in text.lower()][:5]
    vec, clf = _model.named_steps["tfidf"], _model.named_steps["clf"]
    X = vec.transform([text])
    row = list(clf.classes_).index(category)
    contrib = X.multiply(clf.coef_[row]).tocoo()
    terms = vec.get_feature_names_out()
    top = sorted(zip(contrib.col, contrib.data), key=lambda x: -x[1])[:5]
    return [terms[i] for i, v in top if v > 0]

def predict(text: str) -> dict:
    try:
        return _predict(text, _model)
    except Exception as e:      # a model problem must never break complaint submission
        print("ML model failed, using keyword fallback:", repr(e))
        return _predict(text, None)

def _predict(text: str, _model) -> dict:
    if _model is not None:
        probs = _model.predict_proba([text])[0]
        i = probs.argmax()
        category, conf = str(_model.classes_[i]), float(probs[i])
    else:
        t = text.lower()
        scores = {c: sum(k in t for k in kws) for c, kws in FALLBACK.items()}
        category = max(scores, key=scores.get)
        conf = 0.8 if scores[category] else 0.0
    keywords = _explain(text, category, _model) if category in (list(_model.classes_) if _model else FALLBACK) else []
    if conf < CONFIDENCE_THRESHOLD:
        category = "Other"
    return {"category": category, "confidence": round(conf, 3), "priority": detect_priority(text),
            "sentiment": detect_sentiment(text), "keywords": keywords}


MISMATCH_CONFIDENCE = 0.6   # the AI must be at least this sure before it blocks a wrongly chosen problem type

def category_mismatch(text: str, chosen: str):
    """If the text clearly belongs to a different problem type than the one the student chose,
    return {"suggested": ..., "confidence": ...}; otherwise None (choice looks fine / AI unsure)."""
    r = predict(text)
    if r["category"] not in ("Other", chosen) and r["confidence"] >= MISMATCH_CONFIDENCE:
        return {"suggested": r["category"], "confidence": r["confidence"]}
    return None
