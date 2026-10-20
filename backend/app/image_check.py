"""Checks an uploaded evidence file BEFORE a complaint is saved.

1. Real file     - a genuine JPG/PNG/PDF that opens properly and is not tiny.
2. Not blank     - rejects empty / single-colour images and PDFs with no content.
3. Related       - the picture must match the problem type the student chose:
                     Lab & Equipment          -> computer, monitor, keyboard, mouse, printer, error screenshot ...
                     Classroom Infrastructure -> projector, fan, light, bench, board, washroom ...
                     Teaching / Timetable / Exams / Projects -> a document or screenshot (or a classroom / computer where it makes sense)
                   Ragging & Other are not restricted (any real, non-blank file is accepted), because
                   evidence for those can be anything (chat screenshots, photos, letters).

The "related" check uses CLIP zero-shot image classification (a free model that runs on this computer).
It needs:  pip install torch transformers pillow pypdf   (the first start downloads ~600 MB once).

Settings (backend/.env, all optional):
    IMAGE_RELEVANCE=clip          clip = check relevance (default) | off = only check real / not blank
    IMAGE_RELEVANCE_MIN=0.45      how much of the model's confidence must fall on the allowed things (0-1)
    CLIP_MODEL=openai/clip-vit-base-patch32
"""
import io, os, threading
from PIL import Image, ImageStat

PREFIX = "Attachment: "
MIN_SIDE = 120            # px - smaller than this is not usable evidence
IMAGE_FORMATS = {"JPEG", "PNG"}


class AttachmentError(ValueError):
    """The file was rejected; str(e) is the message shown to the student."""


def _err(msg):
    return AttachmentError(PREFIX + msg)


# ----------------------------------------------------------------------------- what counts as "related"
# prompt groups: lab / classroom / documents are "allowed" depending on the chosen problem type;
# "unrelated" is there so selfies, scenery, food, memes etc. are recognised and refused.
PROMPTS = {
    "lab": [
        "a photo of a desktop computer", "a photo of a computer monitor", "a photo of a computer keyboard",
        "a photo of a computer mouse", "a photo of a laptop", "a photo of a computer lab with rows of computers",
        "a photo of a computer CPU cabinet", "a photo of a printer", "a photo of a network switch with cables",
        "a photo of a wifi router", "a photo of a server rack", "a photo of a power extension board with cables",
        "a screenshot of a computer error message", "a photo of a computer screen showing an error",
        "a photo of a broken computer monitor", "a photo of a computer desk in a lab",
    ],
    "classroom": [
        "a photo of an empty classroom with benches and desks", "a photo of a classroom projector",
        "a photo of a ceiling fan", "a photo of a tube light on a ceiling", "a photo of a whiteboard",
        "a photo of a blackboard", "a photo of a wooden bench", "a photo of a washroom",
        "a photo of a water cooler", "a photo of a broken window", "a photo of a damaged wall",
        "a photo of water leakage on a ceiling", "a photo of an electrical switch board",
        "a photo of a corridor in a college building", "a photo of a broken door",
        "a photo of an air conditioner", "a photo of a dirty floor with garbage", "a photo of a drinking water tap",
    ],
    "documents": [
        "a photo of a printed document", "a photo of a handwritten notebook page", "a photo of a timetable chart",
        "a photo of an attendance sheet", "a photo of an exam question paper", "a photo of a marksheet or result",
        "a screenshot of a mobile phone app", "a screenshot of a website", "a photo of a printed notice or letter",
        "a screenshot of an email", "a photo of a project report", "a photo of a certificate",
        "a photo of a notice board",
    ],
    "unrelated": [
        "a selfie portrait of a person", "a photo of a group of people posing", "a landscape with trees and sky",
        "a photo of a plate of food", "a photo of a cat or a dog", "a photo of a car or a motorcycle",
        "a cartoon or a meme", "a movie poster", "a photo of a flower", "a photo of a beach",
        "a photo of a sports game", "a plain white or black background", "a very blurry photo",
    ],
}

# which prompt groups are acceptable for each problem type (None = no relevance check)
ALLOWED = {
    "Lab & Equipment": {"lab"},
    "Classroom Infrastructure": {"classroom"},
    "Teaching & Syllabus": {"documents", "classroom"},
    "Timetable & Attendance": {"documents"},
    "Exams & Marks": {"documents"},
    "Projects & Placements": {"documents", "lab"},
    "Ragging & Harassment": None,
    "Other": None,
}

REJECT_TEXT = {
    "Lab & Equipment": "this picture does not look related to a lab or computer problem. Please attach a clear photo of "
                       "the faulty item (for example the computer, monitor, keyboard, mouse or printer) or a screenshot of the error.",
    "Classroom Infrastructure": "this picture does not look related to a classroom problem. Please attach a clear photo of "
                                "the problem (for example the projector, fan, light, bench, board or washroom).",
}
REJECT_DOC = ("this picture does not look related to a '{cat}' problem. Please attach a clear photo or screenshot of the "
              "related document (for example the timetable, attendance sheet, question paper, marksheet or email).")


def _mode():
    return os.getenv("IMAGE_RELEVANCE", "clip").strip().lower()


def _min_score():
    try:
        return float(os.getenv("IMAGE_RELEVANCE_MIN", "0.45"))
    except ValueError:
        return 0.45


# ----------------------------------------------------------------------------- basic image checks
def _flatten(img):
    """Greyscale copy; transparent pixels count as white (so an empty transparent PNG is 'blank')."""
    if img.mode in ("RGBA", "LA", "P") and ("transparency" in img.info or img.mode in ("RGBA", "LA")):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        return bg.convert("L")
    return img.convert("L")


def is_blank(img) -> bool:
    """True for empty pages / single-colour images (white, black or any flat colour)."""
    g = _flatten(img)
    g.thumbnail((256, 256))
    if ImageStat.Stat(g).stddev[0] < 6:
        return True
    hist = g.histogram()
    peak = max(range(256), key=hist.__getitem__)
    share = sum(hist[max(0, peak - 10):peak + 11]) / max(1, sum(hist))
    return share > 0.985          # 98.5%+ of the picture is one flat tone


def open_image(content: bytes):
    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        raise _err("the file is damaged or is not a real picture. Please take or choose the photo again.")
    if img.format not in IMAGE_FORMATS:
        raise _err("only JPG and PNG pictures are accepted.")
    if min(img.size) < MIN_SIDE:
        raise _err(f"the picture is too small ({img.size[0]}x{img.size[1]}). Please attach a clearer photo.")
    return img


# ----------------------------------------------------------------------------- CLIP relevance (lazy-loaded)
_clip = {"obj": None, "err": None}
_lock = threading.Lock()
_ORDER = [(g, p) for g, ps in PROMPTS.items() for p in ps]


def _load_clip():
    with _lock:
        if _clip["obj"] or _clip["err"]:
            return _clip["obj"]
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor
            name = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")
            model = CLIPModel.from_pretrained(name).eval()
            proc = CLIPProcessor.from_pretrained(name)
            text = proc(text=[p for _, p in _ORDER], return_tensors="pt", padding=True)
            _clip["obj"] = (torch, model, proc, text)
            print("[image_check] CLIP ready - evidence pictures are checked against the problem type")
        except Exception as e:      # not installed / no internet for the first download
            _clip["err"] = e
            print(f"[image_check] CLIP unavailable ({type(e).__name__}: {str(e)[:120]}). "
                  "Install with: pip install torch transformers   (or set IMAGE_RELEVANCE=off)")
        return _clip["obj"]


def warmup():
    """Load the model in the background at server start so the first upload is not slow."""
    if _mode() == "clip":
        threading.Thread(target=_load_clip, daemon=True).start()


def group_scores(img) -> dict:
    """{'lab': 0.71, 'classroom': 0.02, 'documents': 0.05, 'unrelated': 0.22} - shares of the model's confidence."""
    c = _load_clip()
    if not c:
        raise _err("picture checking is not set up on the server yet (the admin must run "
                   "'pip install -r requirements.txt'). You can submit the complaint without an attachment for now.")
    torch, model, proc, text = c
    inputs = proc(images=img.convert("RGB"), return_tensors="pt")
    with torch.no_grad():
        out = model(input_ids=text["input_ids"], attention_mask=text["attention_mask"], pixel_values=inputs["pixel_values"])
    probs = out.logits_per_image.softmax(dim=-1)[0].tolist()
    totals = {g: 0.0 for g in PROMPTS}
    for (g, _), p in zip(_ORDER, probs):
        totals[g] += p
    return totals


def is_related(img, category: str):
    """(ok, scores). Categories with no rule (Ragging, Other) always pass."""
    allowed = ALLOWED.get(category)
    if not allowed or _mode() != "clip":
        return True, {}
    s = group_scores(img)
    top = max(s, key=s.get)
    ok = top in allowed or sum(s[g] for g in allowed) >= _min_score()
    return ok, s


def _reject_related(category):
    return _err(REJECT_TEXT.get(category) or REJECT_DOC.format(cat=category))


def _check_picture(img, category):
    if is_blank(img):
        raise _err("the picture is blank or empty. Please attach a clear photo that shows the problem.")
    ok, _ = is_related(img, category)
    if not ok:
        raise _reject_related(category)


# ----------------------------------------------------------------------------- PDF
def _check_pdf(content: bytes, category: str):
    from pypdf import PdfReader
    try:
        rd = PdfReader(io.BytesIO(content))
        if rd.is_encrypted:
            raise _err("password-protected PDFs cannot be checked. Please upload an unlocked copy.")
        pages = rd.pages[:5]
        text = " ".join((p.extract_text() or "") for p in pages).strip()
        imgs = []
        for p in pages:
            try:
                for im in p.images:
                    imgs.append(im.image)
            except Exception:
                continue          # an image type pypdf cannot decode - ignore it, judge by the rest
    except AttachmentError:
        raise
    except Exception:
        raise _err("the PDF is damaged and cannot be read. Please upload it again.")

    if len(text) >= 25:                     # PDF with real text -> use the complaint classifier on that text
        if ALLOWED.get(category) is not None and _mode() == "clip":
            from . import ml
            mm = ml.category_mismatch(text[:3000], category)
            if mm:
                raise _err(f"the PDF content looks like a '{mm['suggested']}' matter, not '{category}'. "
                           "Please attach a PDF that is related to your complaint.")
        return
    usable = [im for im in imgs if min(im.size) >= MIN_SIDE and not is_blank(im)]
    if not usable:
        raise _err("the PDF is blank or has no readable content. Please attach a PDF that shows the problem, "
                   "or upload a photo (JPG/PNG) instead.")
    best = max(usable, key=lambda im: im.size[0] * im.size[1])
    ok, _ = is_related(best, category)
    if not ok:
        raise _reject_related(category)


# ----------------------------------------------------------------------------- entry point
def validate(content: bytes, ext: str, category: str) -> None:
    """Raise AttachmentError if the file should not be accepted for this complaint."""
    if not content:
        raise _err("the file is empty. Please choose a file that has content.")
    if ext == ".pdf":
        _check_pdf(content, category)
    else:
        _check_picture(open_image(content), category)
