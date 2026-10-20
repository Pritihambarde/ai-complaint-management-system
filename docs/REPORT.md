# Project Report — AI Complaint System for the Computer Science Department

## 1. Abstract
Students in a department raise problems through WhatsApp, paper or word of mouth. Complaints reach the wrong person, get lost, and nobody follows up.
This system lets a student write the problem in plain language. The software understands the text, decides the category and urgency, sends it to the
right coordinator, and escalates it to the HOD and then the Principal if it is not handled in time.

## 2. Users
| Role | Job |
|---|---|
| Student | Submits complaints, tracks them, rates the result, reopens within 7 days |
| Officer (Lab Assistant, Class / Timetable / Exam Coordinator, Project Placement Cell, Admin Desk) | Handles only complaints routed to their own office |
| HOD (Level 1) | Handles ragging complaints directly and anything escalated by officers; sees analytics |
| Principal (Level 2) | Final escalation level; sees analytics |
| Admin | Creates staff accounts, reassigns complaints, sees analytics and the audit log |

## 3. Workflow
1. Validation: length, abusive or gibberish text, file type and size.
2. Category (AI): TF-IDF + Logistic Regression over 8 categories.
3. Priority: safety keyword rules (Critical / High / Medium / Low). Rules are used on purpose so that a dangerous complaint is never missed because of a model mistake. Words are matched as whole words, so "firewall" does not trigger the word "fire".
4. Routing: category -> office -> officer. Ragging & Harassment goes directly to the HOD.
5. Deadline: Low 3 days, Medium 2 days, High/Critical 1 day; missed deadline -> HOD.
6. Escalation: a background job checks every minute. Officer -> HOD -> Principal. Everyone involved is notified.
7. Closing: officer resolves, student rates, student may reopen within 7 days.

## 4. Categories and routing
| Category | Example | Handled by |
|---|---|---|
| Lab & Equipment | Lab computers hanging, software missing | Lab Assistant |
| Classroom Infrastructure | Projector, wifi, fans | Class Incharge |
| Teaching & Syllabus | Faculty absent, syllabus not covered | Class Incharge |
| Timetable & Attendance | Wrong attendance, clashing timetable | Timetable Coordinator |
| Exams & Marks | Missing marks, hall ticket | Exam Coordinator |
| Projects & Placements | No project guide, placement training | Project Placement Cell |
| Ragging & Harassment | Threats, bullying | HOD (direct) |
| Other | Suggestions, certificates, or AI confidence below 35% | Admin Desk |

## 5. AI model
- Data: about 1,100 complaint sentences, written as 20 base complaints per category with wording variations (starter data).
- Model: TF-IDF (1-2 word groups) + Logistic Regression.
- Test: whole base sentences were held out, so accuracy is measured on complaints the model never saw in any wording. **Accuracy 85%** on 280 unseen rows (see `confusion_matrix.png`).
- Weakest categories: Other, Classroom Infrastructure and Projects & Placements are sometimes confused with neighbouring categories.
- Explainability: the complaint shows the key words that led to the category.
- Low-confidence handling: below 35% the complaint goes to the Admin Desk instead of guessing.
- The model retrains itself on first start if it is missing or was built with a different scikit-learn version.

## 6. Security
bcrypt password hashes; JWT tokens that expire in 60 minutes; role checks on every API; lockout for 15 minutes after 5 wrong passwords; OTP password reset; anonymous complaints hide the student's name from staff; validation in browser and server; audit log of important actions; rate limit of 5 complaints per 10 minutes.

## 7. Test cases (automated, 8 scenarios)
Registration rules; full complaint flow with role checks (Ragging -> HOD); spam, gibberish and bad file rejection; anonymity and attachment access; duplicate detection, rating and reopen; escalation Officer -> HOD -> Principal; admin actions, lockout and OTP reset; frontend served.

## 8. Limitations and future work
Small starter dataset and English only (train on real complaints and add Hindi / Marathi). One officer per office. Keyword rules for priority can over-flag. Admin sets staff passwords (an emailed "set your password" link would be better).

## 9. Viva questions
- **Why keyword rules for priority?** A wrong prediction on a threat or harassment case is dangerous, so safety words always win.
- **What if the AI is wrong?** Low-confidence cases go to the Admin Desk and the admin can reassign any complaint.
- **Why does ragging go straight to the HOD?** It is sensitive, and a small department has no separate committee.
- **Why can't officers register themselves?** Anyone could then claim to be the HOD. The admin creates staff accounts.
- **What is your accuracy and how was it measured?** 85%, on complaints held out from training. It is starter data, so real complaints are needed for a true figure.
