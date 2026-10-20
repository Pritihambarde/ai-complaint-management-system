"""Train TF-IDF + Logistic Regression. Test set holds out WHOLE base sentences (group split),
so accuracy is measured on complaints the model has never seen in any wording."""
import random
import pandas as pd, joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, ConfusionMatrixDisplay
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

random.seed(7)
df = pd.read_csv("data/complaints.csv").dropna()
if "group" not in df.columns:                       # real dataset without groups: fall back to row-level split
    df["group"] = range(len(df))
test_groups = set()
for _, g in df.groupby("category")["group"]:
    ug = list(g.unique()); test_groups |= set(random.sample(ug, max(1, len(ug) // 4)))
te = df[df.group.isin(test_groups)]; tr = df[~df.group.isin(test_groups)]

model = Pipeline([
    ("tfidf", TfidfVectorizer(lowercase=True, stop_words="english", ngram_range=(1, 2), sublinear_tf=True)),
    ("clf", LogisticRegression(max_iter=2000, C=10)),
])
model.fit(tr.text, tr.category)
pred = model.predict(te.text)

print(f"Train rows: {len(tr)}  Test rows: {len(te)} (unseen complaints)")
print("Accuracy:", round(accuracy_score(te.category, pred), 4))
print(classification_report(te.category, pred, zero_division=0))
fig, ax = plt.subplots(figsize=(9, 8))
ConfusionMatrixDisplay(confusion_matrix(te.category, pred, labels=model.classes_), display_labels=model.classes_).plot(ax=ax, xticks_rotation=45, colorbar=False)
plt.tight_layout(); plt.savefig("confusion_matrix.png", dpi=150)

model.fit(df.text, df.category)                     # final model uses all data
joblib.dump(model, "model.joblib"); import sklearn; open("model.version", "w").write(sklearn.__version__)
print("Saved model.joblib and confusion_matrix.png")
