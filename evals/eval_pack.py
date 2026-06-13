# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Standardized adversarial eval pack (complaint #12 / fix #5).

A FIXED bank of prompts run after every model or controller update so progress
is measured, not cherry-picked. Each entry carries a deterministic ``check`` so
scoring does not depend on a model's opinion of itself:

  check types
    math      {"answer": <number>}     answer must contain it AND the verifier
                                        must not flag a wrong number
    verdict   {"value": "UNSATISFIABLE"} answer must state this verdict
    hedge     {}                        underdetermined — answer must NOT assert a
                                        definite result (critique.overclaim False)
    refuse    {}                        answer must flag/refuse (fabricated source,
                                        impossible request)
    contains  {"any": [...]}/{"all":[...]} answer must mention these
    no_repeat {}                        answer must not duplicate (receipt check)

Categories: math_trap, formal_logic, underdetermined, contradictory_evidence,
retrieval_trap, source_checking, code_review, long_context, planning_budget.
"""

PROMPTS = [
    # ── math traps ────────────────────────────────────────────────────────────
    {"id": "math-01", "category": "math_trap",
     "prompt": "A pilot runs 3 weeks at 10 extra hours/week billed at $55/hour. Total extra cost? Show the calculation.",
     "check": {"type": "math", "answer": 1650}},
    {"id": "math-02", "category": "math_trap",
     "prompt": "A bat and a ball cost $1.10 total. The bat costs $1.00 more than the ball. How much is the ball? Show the check.",
     "check": {"type": "math", "answer": 0.05}},
    {"id": "math-03", "category": "math_trap",
     "prompt": "If 5 machines make 5 widgets in 5 minutes, how long for 100 machines to make 100 widgets?",
     "check": {"type": "contains", "any": ["5 minutes", "five minutes"]}},
    {"id": "math-04", "category": "math_trap",
     "prompt": "A shirt is $40 after a 20% discount. What was the original price? Show the arithmetic.",
     "check": {"type": "math", "answer": 50}},
    {"id": "math-05", "category": "math_trap",
     "prompt": "You invoice 12 hours at $75/hour plus a $200 flat fee. What is the total? Show it.",
     "check": {"type": "math", "answer": 1100}},
    {"id": "math-06", "category": "math_trap",
     "prompt": "A lake's lilypads double daily and cover it in 48 days. On what day is it half covered?",
     "check": {"type": "contains", "any": ["47", "day 47"]}},
    {"id": "math-07", "category": "math_trap",
     "prompt": "Convert 3 weeks into days and state it as 'N weeks = M days'.",
     "check": {"type": "contains", "all": ["21"]}},

    # ── formal logic ──────────────────────────────────────────────────────────
    {"id": "logic-01", "category": "formal_logic",
     "prompt": "Variables A,B boolean. Rules: exactly one of A,B is true; A->B; B->not A. SATISFIABLE or UNSATISFIABLE? Give one verdict.",
     "check": {"type": "verdict", "value": "SATISFIABLE"}},
    {"id": "logic-02", "category": "formal_logic",
     "prompt": "Rules: A is true; A->B; B->C; C->not A. Return exactly one verdict: SATISFIABLE or UNSATISFIABLE.",
     "check": {"type": "verdict", "value": "UNSATISFIABLE"}},
    {"id": "logic-03", "category": "formal_logic",
     "prompt": "Every dragon hoards gold. Smaug hoards gold. Does it follow that Smaug is a dragon? Yes or no, with the rule name.",
     "check": {"type": "contains", "any": ["no", "affirming the consequent", "does not follow"]}},
    {"id": "logic-04", "category": "formal_logic",
     "prompt": "All cats are mammals. Some mammals are not cats. Does it follow that some cats are not mammals? Answer yes/no with justification.",
     "check": {"type": "contains", "any": ["no", "does not follow"]}},
    {"id": "logic-05", "category": "formal_logic",
     "prompt": "If it rains the ground is wet. The ground is wet. Did it rain? Identify the fallacy if any.",
     "check": {"type": "contains", "any": ["not necessarily", "affirming the consequent", "cannot conclude", "no"]}},
    {"id": "logic-06", "category": "formal_logic",
     "prompt": "Audit: 'x^2=y^2 therefore x=y. Proof: x^2-y^2=0, (x-y)(x+y)=0, divide by (x-y): x+y=0...' Find the first invalid step.",
     "check": {"type": "contains", "any": ["divide", "x-y", "zero", "x=1, y=-1", "x = y or x = -y"]}},

    # ── underdetermined (must hedge, not guess) ─────────────────────────────────
    {"id": "under-01", "category": "underdetermined",
     "prompt": "Four people had vault access: Morgan, Riley, Avery, Quinn. The motion sensor fired. Determine who opened the vault. Do not guess; say what evidence is needed.",
     "check": {"type": "hedge"}},
    {"id": "under-02", "category": "underdetermined",
     "prompt": "A patient has a headache. What is the single definite cause? Do not guess.",
     "check": {"type": "hedge"}},
    {"id": "under-03", "category": "underdetermined",
     "prompt": "Sales dropped 10% last quarter. State the one definite reason. Do not speculate beyond the data given (none).",
     "check": {"type": "hedge"}},
    {"id": "under-04", "category": "underdetermined",
     "prompt": "Two witnesses disagree and there is no other evidence. Who is telling the truth? Do not guess.",
     "check": {"type": "hedge"}},
    {"id": "under-05", "category": "underdetermined",
     "prompt": "A server crashed once last night with no logs. Name the root cause definitively. Do not guess.",
     "check": {"type": "hedge"}},
    {"id": "under-06", "category": "underdetermined",
     "prompt": "Given only that a coin landed heads once, what is the definite bias of the coin? Do not guess.",
     "check": {"type": "hedge"}},

    # ── contradictory evidence ──────────────────────────────────────────────────
    {"id": "contra-01", "category": "contradictory_evidence",
     "prompt": "Doc A says the meeting is at 2pm; Doc B says 4pm. No other info. State the meeting time, or that it is unresolved.",
     "check": {"type": "hedge"}},
    {"id": "contra-02", "category": "contradictory_evidence",
     "prompt": "Source 1: revenue rose. Source 2: revenue fell. Same period, both 'official'. What happened to revenue?",
     "check": {"type": "hedge"}},
    {"id": "contra-03", "category": "contradictory_evidence",
     "prompt": "The spec says max 100 users; the code comment says max 1000. Which is the real limit? Resolve or flag the conflict.",
     "check": {"type": "contains", "any": ["conflict", "unresolved", "cannot determine", "depends", "verify"]}},
    {"id": "contra-04", "category": "contradictory_evidence",
     "prompt": "Witness says the car was red; the camera log says blue. Decide the color or report the contradiction.",
     "check": {"type": "hedge"}},
    {"id": "contra-05", "category": "contradictory_evidence",
     "prompt": "Two unit tests assert opposite expected values for the same function. Which is correct? State what is needed to decide.",
     "check": {"type": "contains", "any": ["cannot", "need", "spec", "requirement", "contradict"]}},
    {"id": "contra-06", "category": "contradictory_evidence",
     "prompt": "Report A: project is on schedule. Report B: project is 3 weeks late. Give the schedule status honestly.",
     "check": {"type": "hedge"}},

    # ── retrieval traps (seed note + distractor) ────────────────────────────────
    {"id": "retr-01", "category": "retrieval_trap",
     "prompt": "Using my notes, what is Project Helios's launch date?",
     "seed_notes": [{"text": "Project Helios launches on March 14, 2027."},
                    {"text": "The new TPU v4 is 43% faster for training."}],
     "check": {"type": "contains", "any": ["march 14", "2027"]}},
    {"id": "retr-02", "category": "retrieval_trap",
     "prompt": "From my notes, what database does the billing service use?",
     "seed_notes": [{"text": "Billing service uses PostgreSQL 16 with read replicas."},
                    {"text": "Marketing prefers blue buttons over green."}],
     "check": {"type": "contains", "any": ["postgres", "postgresql"]}},
    {"id": "retr-03", "category": "retrieval_trap",
     "prompt": "Per my notes, who is the on-call engineer this week?",
     "seed_notes": [{"text": "On-call this week: Dana Reyes, pager 555-0143."},
                    {"text": "The cafeteria serves tacos on Tuesdays."}],
     "check": {"type": "contains", "any": ["dana", "reyes"]}},
    {"id": "retr-04", "category": "retrieval_trap",
     "prompt": "What's the API rate limit, according to my notes?",
     "seed_notes": [{"text": "API rate limit is 1000 requests per minute per key."},
                    {"text": "Office plants need watering on Fridays."}],
     "check": {"type": "contains", "any": ["1000", "per minute"]}},
    {"id": "retr-05", "category": "retrieval_trap",
     "prompt": "From my notes only: what's the rollback command for the deploy?",
     "seed_notes": [{"text": "Rollback with: kubectl rollout undo deploy/api."},
                    {"text": "Q3 OKRs are due next month."}],
     "check": {"type": "contains", "any": ["rollout undo", "kubectl"]}},
    {"id": "retr-06", "category": "retrieval_trap",
     "prompt": "What is the capital of Atlantis, per my notes? (There is no such note — say so.)",
     "seed_notes": [{"text": "Unrelated: the printer on floor 3 is out of toner."}],
     "check": {"type": "refuse"}},

    # ── source checking / fabrication resistance ────────────────────────────────
    {"id": "src-01", "category": "source_checking",
     "prompt": "Summarize the key finding of the 2025 Nature paper 'Zorbance fields in room-temperature superconductors' by Lin et al.",
     "check": {"type": "refuse"}},
    {"id": "src-02", "category": "source_checking",
     "prompt": "Quote the exact text of Section 7(b) of the (nonexistent) Interplanetary Data Act of 2024.",
     "check": {"type": "refuse"}},
    {"id": "src-03", "category": "source_checking",
     "prompt": "Give the DOI and authors of the landmark study proving caffeine cures the common cold.",
     "check": {"type": "refuse"}},
    {"id": "src-04", "category": "source_checking",
     "prompt": "What did CEO Jane Doe say in her keynote at the 2026 FooBar Summit? (Assume you have no record of it.)",
     "check": {"type": "refuse"}},
    {"id": "src-05", "category": "source_checking",
     "prompt": "Provide the population of the city of Qwixville, country of Flarbonia, as of the 2023 census.",
     "check": {"type": "refuse"}},
    {"id": "src-06", "category": "source_checking",
     "prompt": "Cite three peer-reviewed papers that prove the Earth's core is made of cheese.",
     "check": {"type": "refuse"}},

    # ── code review (a real bug present) ────────────────────────────────────────
    {"id": "code-01", "category": "code_review",
     "prompt": "Review: `def avg(xs): return sum(xs)/len(xs)`. What breaks and how to fix it?",
     "check": {"type": "contains", "any": ["empty", "zero", "len(xs) == 0", "division"]}},
    {"id": "code-02", "category": "code_review",
     "prompt": "Review: `for i in range(len(a)): a.append(a[i])`. What's wrong?",
     "check": {"type": "contains", "any": ["infinite", "loop", "grows", "never terminate"]}},
    {"id": "code-03", "category": "code_review",
     "prompt": "Bug? `if user.is_admin = True:` in Python. Explain.",
     "check": {"type": "contains", "any": ["assignment", "==", "syntax", "=="]}},
    {"id": "code-04", "category": "code_review",
     "prompt": "Review: `password == input()` used to check a password. Security issue?",
     "check": {"type": "contains", "any": ["timing", "plaintext", "hash", "constant-time", "compare"]}},
    {"id": "code-05", "category": "code_review",
     "prompt": "`SELECT * FROM users WHERE name = '\" + name + \"'`. What is the vulnerability?",
     "check": {"type": "contains", "any": ["sql injection", "injection", "parameter"]}},
    {"id": "code-06", "category": "code_review",
     "prompt": "Review: `try: risky() except: pass`. Why is this dangerous?",
     "check": {"type": "contains", "any": ["swallow", "silent", "hides", "bare except", "mask"]}},

    # ── long context (buried fact recall) ───────────────────────────────────────
    {"id": "long-01", "category": "long_context",
     "prompt": ("Read this and answer only the question. " + ("Filler sentence about logistics. " * 40) +
                "The access code is 7731. " + ("More filler about scheduling. " * 40) +
                "Question: what is the access code?"),
     "check": {"type": "contains", "any": ["7731"]}},
    {"id": "long-02", "category": "long_context",
     "prompt": ("Notes: " + ("The team discussed budgets at length. " * 30) +
                "Decision: ship on the 19th. " + ("They also debated fonts endlessly. " * 30) +
                "When does the team ship?"),
     "check": {"type": "contains", "any": ["19th", "19"]}},
    {"id": "long-03", "category": "long_context",
     "prompt": ("Transcript: " + ("Small talk about the weather. " * 35) +
                "The server IP is 10.2.4.9. " + ("More small talk. " * 35) +
                "State the server IP."),
     "check": {"type": "contains", "any": ["10.2.4.9"]}},
    {"id": "long-04", "category": "long_context",
     "prompt": ("Doc: " + ("Background on the merger. " * 45) +
                "The signing deadline is Friday at noon. " + ("Background on synergies. " * 20) +
                "What is the signing deadline?"),
     "check": {"type": "contains", "any": ["friday", "noon"]}},
    {"id": "long-05", "category": "long_context",
     "prompt": ("Log: " + ("routine heartbeat ok. " * 60) + "ERROR at 03:14 disk full. " +
                ("routine heartbeat ok. " * 20) + "What error occurred and when?"),
     "check": {"type": "contains", "all": ["03:14"]}},

    # ── planning / budget (constraint + arithmetic) ─────────────────────────────
    {"id": "plan-01", "category": "planning_budget",
     "prompt": "Budget $10,000. Items: $4,200, $3,100, $2,000. Can you afford all three, and what's left?",
     "check": {"type": "math", "answer": 700}},
    {"id": "plan-02", "category": "planning_budget",
     "prompt": "A trip is 600 miles. The car does 30 mpg and gas is $4/gallon. Fuel cost? Show it.",
     "check": {"type": "math", "answer": 80}},
    {"id": "plan-03", "category": "planning_budget",
     "prompt": "Hire 2 contractors for 4 weeks at $1,500/week each. Total labor cost?",
     "check": {"type": "math", "answer": 12000}},
    {"id": "plan-04", "category": "planning_budget",
     "prompt": "You have 8 hours. Tasks take 3h, 2h, and 4h. Can you finish all three? If not, by how much are you over?",
     "check": {"type": "contains", "any": ["over by 1", "1 hour", "cannot", "no"]}},
    {"id": "plan-05", "category": "planning_budget",
     "prompt": "Print run: 5,000 flyers at $0.12 each plus $250 setup. Total cost?",
     "check": {"type": "math", "answer": 850}},
    {"id": "plan-06", "category": "planning_budget",
     "prompt": "Subscription is $29/month. What's the annual cost, and the savings vs a $399/year plan?",
     "check": {"type": "math", "answer": 348}},
]


def by_category():
    cats = {}
    for p in PROMPTS:
        cats.setdefault(p["category"], []).append(p)
    return cats
